from flask import Flask, request, jsonify
import os
import uuid

from video_utils import process_video

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/upload", methods=["POST"])
def upload_video():
    if "video" not in request.files:
        return jsonify({"error": "No video file provided"}), 400

    file = request.files["video"]

    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    # Generate a safe unique filename
    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    video_path = os.path.join(UPLOAD_FOLDER, filename)

    # Save file to disk
    file.save(video_path)

    # Now you can pass this path to OpenCV
    process_video(video_path)

    return jsonify({"message": "Upload successful", "video_path": video_path})
