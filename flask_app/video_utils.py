import cv2
import os

video_path = "/Users/jesaiahprayor/Downloads/jj_handball.mp4"
print('Does the video exist', os.path.exists(video_path))

cap = cv2.VideoCapture(video_path)

if not cap.isOpened():
    raise Exception("Could not open video")

fps = cap.get(cv2.CAP_PROP_FPS)
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
duration = total_frames / fps

frame_index = 0

while True:
    ret, frame = cap.read()

    if not ret:
        break

    timestamp = frame_index / fps
    frame_index += 1

cap.release()
