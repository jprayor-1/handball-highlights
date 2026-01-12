from flask import Flask, request, jsonify
from flask_cors import CORS
import tempfile
import os

from video_utils import process_video, format_time

app = Flask(__name__)
CORS(app)

# Flask confi for max upload size
app.config['MAX_CONTENT_LENGTH'] = 3 * 1024 * 1024 * 1024  # 3GB

ALLOWED_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv'}
MAX_FILE_SIZE = 3 * 1024 * 1024 * 1024  # 3GB

@app.route("/upload", methods=["POST"])
def upload_video():
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
            return jsonify({"error": str(e)}), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({"error": "File too large. Maximum upload size is 3GB"}), 413

@app.route("/health", methods=["GET"])
def health_check():
    """Simple health check endpoint"""
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    # Railway will use gunicorn, this is just for local dev
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
