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
import shutil


from redis import Redis
from rq import Queue
from rq.job import Job, NoSuchJobError

from video_utils import process_video
from video_handle import (
    delete_file,
    generate_presigned_upload_url,
    create_multipart_upload,
    presign_upload_part,
    complete_multipart_upload,
    abort_multipart_upload,
)


app = Flask(__name__)
CORS(app)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

logging.info({"ffmpeg_path": shutil.which("ffmpeg")})
logging.info({"rate_limit_storage": "redis" if os.environ.get("REDIS_URL") else "memory (NOT shared across workers!)"})

redis_url = os.environ.get("REDIS_URL")

EXEMPT_IPS = set(ip.strip() for ip in os.environ.get("RATE_LIMIT_EXEMPT_IPS", "").split(",") if ip.strip())
logging.info({"rate_limit_exempt_ips": list(EXEMPT_IPS) if EXEMPT_IPS else "none"})

if redis_url:
    redis_conn = Redis.from_url(redis_url)
    task_queue = Queue("video", connection=redis_conn, default_timeout=1200)
else:
    redis_conn = None
    task_queue = None

# Rate limiting configuration
def get_rate_limit_key():
    ip = get_remote_address()
    if ip in EXEMPT_IPS:
        return None  # Flask-Limiter skips the limit when key is None
    return ip

limiter = Limiter(
    get_rate_limit_key,
    app=app,
    storage_uri=redis_url if redis_url else "memory://",
    default_limits=["3 per day"],
)

# Flask confi for max upload size
app.config["MAX_CONTENT_LENGTH"] = 35 * 1024 * 1024 * 1024  # 35GB

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
ALLOWED_MIME_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
}
MAX_FILE_SIZE = 35 * 1024 * 1024 * 1024  # 35GB
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
        return jsonify({"error": "File too large (max 35GB)"}), 413

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
    return jsonify({"error": "File too large. Maximum upload size is 35GB"}), 413


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
@limiter.limit("3 per day")
def process_video_from_r2():
    """
    Enqueue a video processing job for a video already uploaded to R2.
    Expects JSON body: { "key": "uploads/raw/uuid_filename.mp4" }
    Returns: { "job_id": "... ", "status": "queued" }
    Poll GET /api/jobs/<job_id> for results.
    """
    if task_queue is None:
        return jsonify(
            {"error": "Job queue unavailable: REDIS_URL not configured"}
        ), 503

    data = request.get_json()
    if not data or "key" not in data:
        return jsonify({"error": "Missing 'key' in request body"}), 400

    key = data["key"]
    email = data.get("email") or None
    game_type = data.get("game_type", "singles")
    if game_type not in ("singles", "doubles"):
        game_type = "singles"

    ext = os.path.splitext(key)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify(
            {"error": f"Invalid file type. Allowed: {ALLOWED_EXTENSIONS}"}
        ), 400

    from tasks import run_video_processing

    job = task_queue.enqueue(
        run_video_processing, key, email, game_type, result_ttl=3600, failure_ttl=86400
    )

    logging.info(
        {"event": "job_queued", "job_id": job.id, "key": key, "ip": request.remote_addr}
    )

    return jsonify({"job_id": job.id, "status": "queued"}), 202


@limiter.exempt
@app.route("/api/jobs/<job_id>", methods=["GET"])
def get_job_status(job_id):
    """Poll for the status and result of a video processing job."""
    if redis_conn is None:
        return jsonify(
            {"error": "Job queue unavailable: REDIS_URL not configured"}
        ), 503

    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except NoSuchJobError:
        return jsonify({"error": "Job not found"}), 404

    try:
        status = job.get_status()
        status_str = status.value if hasattr(status, "value") else status
        response = {"job_id": job_id, "status": status_str}

        if status_str == "finished":
            response["result"] = job.return_value()
        elif status_str == "failed":
            response["error"] = str(job.exc_info) if job.exc_info else "Unknown error"

        return jsonify(response), 200
    except Exception as e:
        logging.exception({"event": "get_job_status_failed", "job_id": job_id, "error": str(e)})
        return jsonify({"error": str(e)}), 500


@limiter.exempt
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
@limiter.limit("3 per day")
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
        return jsonify({"error": "File too large (max 35GB)"}), 413

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


@app.route("/api/uploads/multipart/initiate", methods=["POST"])
@limiter.limit("3 per day")
def initiate_multipart():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    filename = data.get("filename")
    filesize = data.get("filesize")
    content_type = data.get("content_type")

    if not filename or not filesize or not content_type:
        return jsonify({"error": "Missing required fields: filename, filesize, content_type"}), 400

    if int(filesize) > MAX_FILE_SIZE:
        return jsonify({"error": f"File too large (max 35GB)"}), 413

    if content_type not in ALLOWED_MIME_TYPES:
        return jsonify({"error": f"Invalid content type. Allowed: {ALLOWED_MIME_TYPES}"}), 400

    key = f"uploads/raw/{uuid.uuid4()}_{filename}"
    try:
        upload_id = create_multipart_upload(key, content_type)
        return jsonify({"key": key, "upload_id": upload_id}), 200
    except Exception as e:
        logging.exception({"event": "multipart_initiate_failed", "error": str(e)})
        return jsonify({"error": str(e)}), 500


@limiter.exempt
@app.route("/api/uploads/multipart/presign-part", methods=["POST"])
def multipart_presign_part():
    data = request.get_json()
    key = data.get("key")
    upload_id = data.get("upload_id")
    part_number = data.get("part_number")

    if not key or not upload_id or not part_number:
        return jsonify({"error": "Missing required fields: key, upload_id, part_number"}), 400

    try:
        url = presign_upload_part(key, upload_id, int(part_number))
        return jsonify({"url": url}), 200
    except Exception as e:
        logging.exception({"event": "multipart_presign_part_failed", "error": str(e)})
        return jsonify({"error": str(e)}), 500


@limiter.exempt
@app.route("/api/uploads/multipart/complete", methods=["POST"])
def multipart_complete():
    data = request.get_json()
    key = data.get("key")
    upload_id = data.get("upload_id")
    parts = data.get("parts")  # [{"PartNumber": 1, "ETag": "..."}]

    if not key or not upload_id or not parts:
        return jsonify({"error": "Missing required fields: key, upload_id, parts"}), 400

    try:
        complete_multipart_upload(key, upload_id, parts)
        return jsonify({"key": key}), 200
    except Exception as e:
        logging.exception({"event": "multipart_complete_failed", "error": str(e)})
        return jsonify({"error": str(e)}), 500


@limiter.exempt
@app.route("/api/uploads/multipart/abort", methods=["POST"])
def multipart_abort():
    data = request.get_json()
    key = data.get("key")
    upload_id = data.get("upload_id")

    if not key or not upload_id:
        return jsonify({"error": "Missing required fields: key, upload_id"}), 400

    try:
        abort_multipart_upload(key, upload_id)
        return jsonify({"aborted": True}), 200
    except Exception as e:
        logging.exception({"event": "multipart_abort_failed", "error": str(e)})
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def root():
    return jsonify({"message": "Handball Highlights API"}), 200


@app.after_request
def log_request_end(response):
    start_time = getattr(request, "start_time", None)
    duration = None
    if start_time:
        duration = round((time.time() - float(start_time)) * 1000, 2)

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
    logging.exception({"event": "unhandled_500", "error": str(e)})
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    # Railway will use gunicorn, this is just for local dev
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
