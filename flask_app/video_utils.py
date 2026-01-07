import cv2
import numpy as np
import os
import matplotlib.pyplot as plt

video_path = "/Users/jesaiahprayor/Downloads/jj_handball.mp4"
if not os.path.exists(video_path):
    raise FileNotFoundError(f"Video file not found: {video_path}")

# Open the video file
cap = cv2.VideoCapture(video_path)

# Get frames-per-second (FPS) of the video
fps = cap.get(cv2.CAP_PROP_FPS)

# Decide how often to sample frames
# Example: fps // 3 means ~3 frames per second
sample_rate = max(1, int(fps // 3))

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
            # Get frame dimensions
            h, w = gray.shape

            # Define center crop (ignore edges)
            margin_h = int(h * 0.2)
            margin_w = int(w * 0.2)

            # Crop current and previous frames to center
            gray_center = gray[margin_h : h - margin_h, margin_w : w - margin_w]

            prev_gray_center = prev_gray[
                margin_h : h - margin_h, margin_w : w - margin_w
            ]

            diff_full = cv2.absdiff(gray, prev_gray)
            full_motion = np.mean(diff_full)

            # Center-frame motion
            diff_center = cv2.absdiff(gray_center, prev_gray_center)
            center_motion = np.mean(diff_center)

            ratio = center_motion / (full_motion + 1e-6)

            # Ratio test
            ratio_threshold = 0.7
            if ratio > ratio_threshold:
                # Reduce the entire diff image into one scalar value
                # This represents how much motion occurred between frames
                motion_intensity = center_motion

                # Convert frame index to timestamp (seconds)
                timestamp = frame_idx / fps

                # Store timestamp and motion score
                motion_scores.append((timestamp, motion_intensity))
            else:
                motion_intensity = 0.0  # remove sustained foreground walking

        # Update previous frame to current frame
        prev_gray = gray

    # Move to the next frame
    frame_idx += 1


# Release the video file
cap.release()

# Print the first 10 motion scores for inspection
print("First 10 motion scores:")
print(motion_scores[:10])

times = [t for t, m in motion_scores]
motions = [m for t, m in motion_scores]

raw = np.array(motions)

raw_cap = np.percentile(raw, 93)
raw_preclean = np.minimum(raw, raw_cap)


window = 5  # can tweak 3-10
motions_smooth = np.convolve(raw_preclean, np.ones(window) / window, mode="same")

median = np.median(motions_smooth)
mad = np.median(np.abs(motions_smooth - median))

# Controls how aggressive spike removal is
SPIKE_STRENGTH = 3
spike_threshold = median + SPIKE_STRENGTH * mad

gameplay_motion = motions_smooth.copy()
gameplay_motion[gameplay_motion > spike_threshold] = 0

MIN_EVENT_SECONDS = 1.1  # ignore spikes shorter than this
motions_used = gameplay_motion
threshold = np.percentile(motions_used, 90)

events = []
current_event_start = None

for t, motion in zip(times, motions_used):
    if motion > threshold:
        if current_event_start is None:
            current_event_start = t
    else:
        if current_event_start is not None:
            duration = t - current_event_start
            if duration >= MIN_EVENT_SECONDS:
                events.append((current_event_start, t))
            current_event_start = None

# Catch any event at the end
if current_event_start is not None:
    events.append((current_event_start, times[-1]))

print("Detected highlight events:")
for start, end in events:
    print(f"{start:.2f}s → {end:.2f}s")


plt.figure(figsize=(12, 5))

plt.plot(times, raw_preclean, alpha=0.3, label="Raw Pre Clean")
plt.plot(times, motions_smooth, alpha=0.6, label="Smoothed motion")
plt.plot(times, gameplay_motion, linewidth=2, label="Spike-removed motion")

plt.axhline(threshold, color="red", linestyle="--", label="Detection threshold")
plt.axhline(spike_threshold, color="black", linestyle=":", label="Spike threshold")

plt.xlabel("Time (seconds)")
plt.ylabel("Motion intensity")
plt.title("Motion Pipeline (Raw → Smoothed → Cleaned)")
plt.legend()
plt.show()
