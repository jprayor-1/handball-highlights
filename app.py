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


from video_utils import process_video, format_time

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
    get_remote_address, # uses client IP
    app=app,
    storage_uri=redis_url if redis_url else "memory://",
    default_limits=["100 per day", "10 per hour"] 
)

# Flask confi for max upload size
app.config['MAX_CONTENT_LENGTH'] = 3 * 1024 * 1024 * 1024  # 3GB

ALLOWED_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv'}
MAX_FILE_SIZE = 3 * 1024 * 1024 * 1024  # 3GB

@app.route("/upload", methods=["POST"])
@limiter.limit("3 per day")
def upload_video():
    """"
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
        return jsonify({"error": f"Invalid file type. Allowed: {ALLOWED_EXTENSIONS}"}), 400
    
    # Check file size (you can also configure Flask's MAX_CONTENT_LENGTH)
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)  # Reset pointer

    if file_size > MAX_FILE_SIZE:
        return jsonify({"error": "File too large (max 3GB)"}), 413

    # Create temporary file that auto-deletes
    with tempfile.NamedTemporaryFile(delete=True, suffix=ext) as temp_video:
        try:
            # Save file to temp_location
            file.save(temp_video.name)

            # Now you can pass this path to OpenCV
            highlight_segments = process_video(temp_video.name)

            return jsonify({
                'highlights': [
                    {
                        'start': start,
                        'end': end,
                        'score': score,
                        'formatted_start': format_time(start),
                        'formatted_end': format_time(end)
                    }
                    for start, end, score in highlight_segments
                ]
            })
        except Exception as e:
            logging.exception({
                "event": "upload_failed",
                "error": str(e),
                "filename": file.filename,
                "size": file_size,
                "ip": request.remote_addr,
            })
            return jsonify({"error": str(e)}), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({"error": "File too large. Maximum upload size is 3GB"}), 413

@app.before_request
def log_request_start():
    request.start_time = time.time()
    logging.info({
        "event": "request_start",
        "method": request.method,
        "path": request.path,
        "ip": request.remote_addr,
        "content_length": request.content_length,
        "user_agent": request.headers.get("User-Agent"),
    })

@app.route("/", methods=["GET"])
def root():
    return jsonify({"message": "Handball Highlights API"}), 200


@app.after_request
def log_request_end(response):
    duration = round((time.time() - request.start_time) * 1000, 2)

    logging.info({
        "method": request.method,
        "path": request.path,
        "status": response.status_code,
        "duration_ms": duration,
        "ip": request.remote_addr,
        "user_agent": request.headers.get("User-Agent"),
        "content_length": request.content_length,
    })

    return response

@limiter.exempt
@app.route("/health", methods=["GET"])
def health_check():
    """Simple health check endpoint"""
    return jsonify({"status": "ok"})

@app.errorhandler(RateLimitExceeded)
def handle_rate_limit(e):
    return jsonify({
        "error": "Upload limit reached",
        "message": "You can only upload 3 videos per day. Try again tomorrow."
    }), 429

if __name__ == "__main__":
    # Railway will use gunicorn, this is just for local dev
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
