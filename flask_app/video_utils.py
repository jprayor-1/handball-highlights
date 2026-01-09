import cv2  # OpenCV for video processing
import numpy as np  # Numerical operations
import os  # File system checks
import matplotlib.pyplot as plt  # Visualization


def format_time(seconds):
    """
    Convert seconds to 'MM:SS' format.
    """
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


def moving_average(signal, window_size):
    """
    Smooths a 1D signal using a simple moving average.

    Smaller window → more responsive, noisier

    Larger window → smoother, longer volleys

    Args:
        signal (np.array): raw motion signal
        window_size (int): number of samples to average over

    Returns:
        np.array: smoothed signal (same length as input)
    """
    # Create a normalized averaging window
    window = np.ones(window_size) / window_size

    # Convolve signal with window to smooth it
    return np.convolve(signal, window, mode="same")


# Absolute path to the input video file
video_path = "/Users/jesaiahprayor/Downloads/jj_handball.mp4"

# Make sure the video file exists before continuing
if not os.path.exists(video_path):
    raise FileNotFoundError(f"Video file not found: {video_path}")

# Open the video file for frame-by-frame reading
cap = cv2.VideoCapture(video_path)

# Extract frames-per-second (FPS) so we can convert frames → time
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

            # Ratio of center motion vs entire frame motion
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


times = [t for t, m in motion_scores]
motions = [m for t, m in motion_scores]


MA_WINDOW = 5
# Apply moving average smoothing
motions_ma = moving_average(motions, MA_WINDOW)


median = np.median(motions_ma)
mad = np.median(np.abs(motions_ma - median))

# Controls how aggressive spike removal is
SPIKE_STRENGTH = 3
# Motion above this is considered non-gameplay noise
spike_threshold = median + SPIKE_STRENGTH * mad

# Remove spikes from the motion signal
gameplay_motion = motions_ma.copy()
gameplay_motion[gameplay_motion > spike_threshold] = 0

# Minimum duration for a valid volley (seconds)
# VISIT LATER --> MIN_EVENT_SECONDS = 3

# Use cleaned motion signal for segmentation
motions_used = gameplay_motion

# Threshold defining "active play"
THRESHOLD_PERCENTILE = 20
threshold = np.percentile(motions_used, THRESHOLD_PERCENTILE)

segments = []
in_volley = False
volley_start_time = None

for t, motion in zip(times, motions_used):

    if not in_volley and motion > threshold:
        in_volley = True
        volley_start_time = t

    elif in_volley and motion <= threshold:
        in_volley = False
        segments.append((volley_start_time, t))

PRE_PADDING = 0.5  # seconds before volley start
POST_PADDING = 1.0  # seconds after volley end
video_end = times[-1]

MIN_EVENT_SECONDS = 12  # seconds

# Filter out short segments
segments_filtered = []
for start, end in segments:
    duration = end - start
    if duration >= MIN_EVENT_SECONDS:
        segments_filtered.append((start, end))

VALLEY_TOLERANCE = 2.0  # seconds

merged_segments = []
if segments_filtered:
    current_start, current_end = segments_filtered[0]

    for start, end in segments_filtered[1:]:
        # Check gap between current end and next start
        if start - current_end <= VALLEY_TOLERANCE:
            # Merge segments
            current_end = end
        else:
            merged_segments.append((current_start, current_end))
            current_start, current_end = start, end

    # Append last segment
    merged_segments.append((current_start, current_end))

# Create padded segments
segments_padded = []
for start, end in merged_segments:
    padded_start = max(0, start - PRE_PADDING)  # don’t go below 0
    padded_end = min(video_end, end + POST_PADDING)  # don’t exceed video length
    segments_padded.append((padded_start, padded_end))

segment_scores = []
for start, end in segments_padded:
    # Convert start/end times to indices
    start_idx = np.searchsorted(times, start)
    end_idx = np.searchsorted(times, end)
    
    segment_motion = motions_ma[start_idx:end_idx]
    
    max_motion = np.max(segment_motion)
    mean_motion = np.mean(segment_motion)
    duration = end - start
    
    # Example: combined score (you can tweak weights)
    score = max_motion * 0.6 + mean_motion * 0.3 + duration * 0.1
    segment_scores.append((start, end, score))

# Sort descending: most exciting first
segment_scores_sorted = sorted(segment_scores, key=lambda x: x[2], reverse=True)

print("Top volleys by excitement:")
for i, (start, end, score) in enumerate(segment_scores_sorted, 1):
    print(f"{i}: {format_time(start)} → {format_time(end)}, score={score:.2f}")

plt.figure(figsize=(12, 5))
plt.plot(times, motions_ma, linewidth=2, label="Moving average")
plt.axhline(threshold, color="red", linestyle="--", label="Threshold")

for start, end in segments_padded:
    plt.axvspan(start, end, color="green", alpha=0.2)  # shaded region

plt.xlabel("Time (seconds)")
plt.ylabel("Motion intensity")
plt.title("Threshold Crossing with Pre/Post Padding")
plt.legend()
plt.show()
