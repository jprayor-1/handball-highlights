from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.errors import RateLimitExceeded
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import tempfile
import os
import time
import logging
import uuid


from clip_video import clip_all_highlights_parallel
from video_utils import process_video
from video_handle import download_file, delete_file, generate_presigned_upload_url


app = Flask(__name__)
CORS(app)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

redis_url = os.environ.get("REDIS_URL")

# Rate limiting configuration
limiter = Limiter(
    get_remote_address,  # uses client IP
    app=app,
    storage_uri=redis_url if redis_url else "memory://",
    default_limits=["100 per day", "10 per hour"],
)

# Flask confi for max upload size
app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024 * 1024  # 3GB

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
ALLOWED_MIME_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
}
MAX_FILE_SIZE = 1 * 1024 * 1024 * 1024  # 1GB
MAX_HIGHLIGHT_SIZE = 200 * 1024 * 1024  # 200 MB


# Test route, uploads video directly to the server
@app.route("/upload", methods=["POST"])
@limiter.limit("3 per day")
def upload_video():
    """ "
    Endpoint to upload video and get highlight segments
    args: None (expects 'video' file in form-data)
    returns: JSON with highlight segments
    [{
        'start': start,
        'end': end,
        'score': score,
        'formatted_start': format_time(start),
        'formatted_end': format_time(end)
    }]

    """
    if "video" not in request.files:
        return jsonify({"error": "No video file provided"}), 400

    file = request.files["video"]

    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    # Check file extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return (
            jsonify({"error": f"Invalid file type. Allowed: {ALLOWED_EXTENSIONS}"}),
            400,
        )

    # Check file size (you can also configure Flask's MAX_CONTENT_LENGTH)
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)  # Reset pointer

    if file_size > MAX_FILE_SIZE:
        return jsonify({"error": "File too large (max 1GB)"}), 413

    # Create temporary file that auto-deletes
    with tempfile.NamedTemporaryFile(delete=True, suffix=ext) as temp_video:
        try:
            # Save file to temp_location
            file.save(temp_video.name)

            # Now you can pass this path to OpenCV
            highlight_segments = process_video(temp_video.name)

            return jsonify({"highlights": highlight_segments})
        except Exception as e:
            logging.exception(
                {
                    "event": "upload_failed",
                    "error": str(e),
                    "filename": file.filename,
                    "size": file_size,
                    "ip": request.remote_addr,
                }
            )
            return jsonify({"error": str(e)}), 500


@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({"error": "File too large. Maximum upload size is 3GB"}), 413


@app.before_request
def log_request_start():
    request.start_time = time.time()
    logging.info(
        {
            "event": "request_start",
            "method": request.method,
            "path": request.path,
            "ip": request.remote_addr,
            "content_length": request.content_length,
            "user_agent": request.headers.get("User-Agent"),
        }
    )


@app.route("/api/process_video", methods=["POST"])
def process_video_from_r2():
    """
    Process a video already uploaded to R2.
    Expects JSON body:
    {
        "key": "uploads/raw/uuid_filename.mp4"
    }
    """

    data = request.get_json()
    if not data or "key" not in data:
        return jsonify({"error": "Missing 'key' in request body"}), 400

    key = data["key"]

    # Validate extension from key
    ext = os.path.splitext(key)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return (
            jsonify({"error": f"Invalid file type. Allowed: {ALLOWED_EXTENSIONS}"}),
            400,
        )

    try:
        # Create temp file for processing
        with tempfile.NamedTemporaryFile(delete=True, suffix=ext) as temp_video:
            # Download file from R2 into temp file
            download_file(key=key, destination_path=temp_video.name)

            logging.info(
                {
                    "event": "starting get highlights",
                }
            )

            # Process video
            highlight_segments = process_video(temp_video.name)

            logging.info(
                {"event": "list of highlights", "highlights": highlight_segments}
            )

            # Create highlight clips
            clipped_highlights = clip_all_highlights_parallel(
                temp_video.name, highlight_segments
            )

            logging.info(
                {"event": "clipped highlights", "highlights": clipped_highlights}
            )

            return (
                jsonify({"key": key, "highlights": clipped_highlights}),
                200,
            )

    except Exception as e:
        logging.exception(
            {
                "event": "process_video_failed",
                "error": str(e),
                "key": key,
                "ip": request.remote_addr,
            }
        )
        return jsonify({"error": "Failed to process video"}), 500


@app.route("/api/uploads", methods=["DELETE"])
def delete_upload():
    """
    Delete a file from R2.
    Expects JSON payload: { "key": "highlights/uuid-filename.mp4" }
    """
    data = request.get_json()

    key = data.get("key") if data else None

    if not key:
        return jsonify({"error": "Missing 'key' in request"}), 400

    try:
        delete_file(key)
        return jsonify({"deleted": key}), 200
    except Exception as e:
        logging.exception(
            {
                "event": "delete_from_r2_failed",
                "error": str(e),
                "key": key,
                "ip": request.remote_addr,
            }
        )
        return jsonify({"error": "Failed to delete file"}), 500


@app.route("/api/uploads/presign", methods=["POST"])
def presign_upload():
    """
    Generate a presigned URL for uploading a long video to R2
    Expects JSON body with:
    {
        "filename": "File name of video to upload",
        "filesize": "size of file in bytes",
        "content_type": "video/mp4"
    }
    """

    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing 'Video' in request body"}), 400

    filename = data.get("filename")
    filesize = data.get("filesize")
    content_type = data.get("content_type")

    if not filename or not filesize or not content_type:
        return (
            jsonify(
                {"error": "Missing required fields: filename, filesize, content_type"}
            ),
            400,
        )

    if not filesize or int(filesize) > MAX_FILE_SIZE:
        return jsonify({"error": "File too large (max 1GB)"}), 413

    if not content_type or content_type not in ALLOWED_MIME_TYPES:
        return (
            jsonify({"error": f"Invalid content type. Allowed: {ALLOWED_MIME_TYPES}"}),
            400,
        )

    # ensures uniqueness in key upload path
    key = f"uploads/raw/{uuid.uuid4()}_{filename}"
    try:
        url = generate_presigned_upload_url(key, content_type)
        return jsonify({"key": key, "url": url}), 200
    except Exception as e:
        logging.exception(
            {
                "event": "presign_failed",
                "error": str(e),
                "key": key,
                "ip": request.remote_addr,
            }
        )
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def root():
    return jsonify({"message": "Handball Highlights API"}), 200


@app.after_request
def log_request_end(response):
    start_time = getattr(request, "start_time", None)

    if start_time is not None:
        duration = round((time.time() - start_time) * 1000, 2)
        logging.info(
            {
                "event": "request_end",
                "method": request.method,
                "path": request.path,
                "duration_ms": duration,
            }
        )

    return response

    logging.info(
        {
            "method": request.method,
            "path": request.path,
            "status": response.status_code,
            "duration_ms": duration,
            "ip": request.remote_addr,
            "user_agent": request.headers.get("User-Agent"),
            "content_length": request.content_length,
        }
    )

    return response


@limiter.exempt
@app.route("/health", methods=["GET"])
def health_check():
    """Simple health check endpoint"""
    return jsonify({"status": "ok"})


@app.errorhandler(RateLimitExceeded)
def handle_rate_limit(e):
    return (
        jsonify(
            {
                "error": "Upload limit reached",
                "message": "You can only upload 3 videos per day in beta mode. Try again tomorrow.",
            }
        ),
        429,
    )


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    # Railway will use gunicorn, this is just for local dev
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
