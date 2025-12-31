import cv2
import numpy as np
import os

video_path = "/Users/jesaiahprayor/Downloads/jj_handball.mp4"
print('Does the video exist', os.path.exists(video_path))

# Open the video file
cap = cv2.VideoCapture(video_path)

# Get frames-per-second (FPS) of the video
fps = cap.get(cv2.CAP_PROP_FPS)

# Decide how often to sample frames
# Example: fps // 3 means ~3 frames per second
sample_rate = int(fps // 3)

# Store the previous frame in grayscale for comparison
prev_gray = None

# List to store (timestamp, motion_score)
motion_scores = []

# Track which frame we are currently on
frame_idx = 0

# Loop through the video frame by frame
while True:
    # Read the next frame from the video
    ret, frame = cap.read()

    # If no frame is returned, we reached the end of the video
    if not ret:
        break

    # Only process every Nth frame (frame skipping)
    if frame_idx % sample_rate == 0:

        # Convert the frame from color (BGR) to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Only compute motion if we have a previous frame
        if prev_gray is not None:

            # Compute absolute pixel difference between current and previous frame
            diff = cv2.absdiff(gray, prev_gray)

            # Reduce the entire diff image into one scalar value
            # This represents how much motion occurred between frames
            motion_intensity = np.mean(diff)

            # Convert frame index to timestamp (seconds)
            timestamp = frame_idx / fps

            # Store timestamp and motion score
            motion_scores.append((timestamp, motion_intensity))

        # Update previous frame to current frame
        prev_gray = gray

    # Move to the next frame
    frame_idx += 1

# Release the video file
cap.release()

# Print the first 10 motion scores for inspection
print("First 10 motion scores:")
print(motion_scores[:10])