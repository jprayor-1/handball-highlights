import cv2  # OpenCV for video processing
import numpy as np  # Numerical operations
import os  # File system checks
import matplotlib.pyplot as plt  # Visualization
import uuid
from dataclasses import dataclass


@dataclass
class VideoConfig:
    threshold_percentile: int
    volley_tolerance: float
    variance_threshold: float
    ratio_threshold: float
    min_event_seconds: int
    ma_window: int
    spike_strength: int


SINGLES_CONFIG = VideoConfig(
    threshold_percentile=19,
    volley_tolerance=2.0,  # might need to experiment with this
    variance_threshold=50.0,
    ratio_threshold=0.7,
    min_event_seconds=11,
    ma_window=5,
    spike_strength=3,
)

DOUBLES_CONFIG = VideoConfig(
    threshold_percentile=25,  # more bodies = more baseline motion, raise threshold
    volley_tolerance=4,  # doubles rallies have more brief pauses
    variance_threshold=40.0,  # lower bar — motion is spread across more players
    ratio_threshold=0.6,  # slightly more edge motion acceptable
    min_event_seconds=11,
    ma_window=5,
    spike_strength=3,
)


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


def calculate_motion_variance(motion_scores, window_seconds=2.0):
    """
    Calculate variance of motion over a rolling time window.
    High variance = bursty motion (volleys)
    Low variance = steady motion (walking)

    Args:
        motion_scores: list of (timestamp, motion_intensity) tuples
        window_seconds: size of rolling window in seconds

    Returns:
        list of (timestamp, motion_intensity, variance) tuples
    """
    times = [t for t, m in motion_scores]
    motions = [m for t, m in motion_scores]

    motion_with_variance = []

    for i, (t, motion) in enumerate(motion_scores):
        # Find all samples within the time window
        window_start_time = t - window_seconds / 2
        window_end_time = t + window_seconds / 2

        # Get indices of samples in this window
        window_samples = []
        for j, time in enumerate(times):
            if window_start_time <= time <= window_end_time:
                window_samples.append(motions[j])

        # Calculate variance of motion in this window
        if len(window_samples) > 1:
            variance = np.var(window_samples)
        else:
            variance = 0

        motion_with_variance.append((t, motion, variance))

    return motion_with_variance


def process_video(
    video_path="/Users/jesaiahprayor/Downloads/dboy_migz.mp4",
    config: VideoConfig = SINGLES_CONFIG,
    game_type: str = "singles",
):
    """
    Process a video to detect segments of high activity ("volleys") based on motion analysis.
    Args:
        video_path (str): Path to the input video file.
        config (VideoConfig): Tuning parameters — use SINGLES_CONFIG or DOUBLES_CONFIG.
        game_type (str): "singles" or "doubles". Overrides config if provided.
    Returns:
        list of dicts with highlight segments.
    """
    config = DOUBLES_CONFIG if game_type == "doubles" else SINGLES_CONFIG

    # Make sure the video file exists before continuing
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # Open the video file for frame-by-frame reading
    cap = cv2.VideoCapture(video_path)

    # Extract frames-per-second (FPS) so we can convert frames → time
    fps = cap.get(cv2.CAP_PROP_FPS)

    # Decide how often to sample frames
    # Example: fps // 3 means ~3 frames per second
    sample_rate = max(1, int(fps // 2))

    # Store the previous frame in grayscale for comparison
    prev_gray = None

    # List to store (timestamp, motion_score)
    motion_scores = []

    # Track which frame we are currently on
    frame_idx = 0

    # Loop through the video frame by frame
    while True:
        if frame_idx % sample_rate == 0:
            # Only decode frames we actually need; use grab() for the rest
            ret, frame = cap.read()
            if not ret:
                break

            # Convert to grayscale and resize to 320x180 — 16x fewer pixels,
            # same motion signal quality for volley detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (320, 180))

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

                # Reduce the entire diff image into one scalar value
                # This represents how much motion occurred between frames
                motion_intensity = center_motion

                # Convert frame index to timestamp (seconds)
                timestamp = frame_idx / fps

                # Store timestamp and motion score
                motion_scores.append((timestamp, motion_intensity, ratio))

            # Update previous frame to current frame
            prev_gray = gray
        else:
            # Advance position without decoding
            if not cap.grab():
                break

        # Move to the next frame
        frame_idx += 1

    # Release the video file
    cap.release()

    motion_with_variance = calculate_motion_variance(
        [(t, m) for t, m, r in motion_scores], window_seconds=2.0
    )

    times = []
    motions = []

    for i, (t, motion, variance) in enumerate(motion_with_variance):
        ratio = motion_scores[i][2]  # Get ratio from original list

        # Accept motion if:
        # 1. Ratio is good (center-focused), AND
        # 2. Variance is high (bursty, not steady walking)
        if ratio > config.ratio_threshold and variance > config.variance_threshold:
            times.append(t)
            motions.append(motion)
        else:
            # Optional: still add a dampened value to avoid timeline gaps
            times.append(t)
            motions.append(motion * 0.1)  # Heavily dampened

    # Apply moving average smoothing
    motions_ma = moving_average(motions, config.ma_window)

    median = np.median(motions_ma)
    mad = np.median(np.abs(motions_ma - median))

    # Motion above this is considered non-gameplay noise
    spike_threshold = median + config.spike_strength * mad

    # Remove spikes from the motion signal
    gameplay_motion = motions_ma.copy()
    gameplay_motion[gameplay_motion > spike_threshold] = 0

    # Minimum duration for a valid volley (seconds)
    # VISIT LATER --> MIN_EVENT_SECONDS = 3

    # Use cleaned motion signal for segmentation
    motions_used = gameplay_motion

    # Threshold defining "active play"
    threshold = np.percentile(motions_used, config.threshold_percentile)

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

    # Filter out short segments
    segments_filtered = []
    for start, end in segments:
        duration = end - start
        if duration >= config.min_event_seconds:
            segments_filtered.append((start, end))

    VALLEY_TOLERANCE = config.volley_tolerance

    merged_segments = []
    if segments_filtered:
        current_start, current_end = segments_filtered[0]

        for start, end in segments_filtered[1:]:
            # Check gap between current end and next start
            if start - current_end <= VALLEY_TOLERANCE and end - current_start <= 80:
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

    segments_no_timeouts = []
    TIMEOUT_INTENSITY_THRESHOLD = np.percentile(motions_ma, 40)

    for start, end in segments_padded:
        # Convert start/end times to indices
        start_idx = np.searchsorted(times, start)
        end_idx = np.searchsorted(times, end)

        segment_motion = motions_ma[start_idx:end_idx]

        avg_intensity = np.mean(segment_motion)
        max_intensity = np.max(segment_motion)

        if avg_intensity >= TIMEOUT_INTENSITY_THRESHOLD:
            segments_no_timeouts.append((start, end))
        else:
            print(
                f"Excluding segment {format_time(start)} → {format_time(end)} due to low intensity (avg={avg_intensity:.2f}, max={max_intensity:.2f})"
            )

    motions_score = moving_average(motions, 2)  # very light smoothing
    segment_scores = []
    for start, end in segments_no_timeouts:
        # Convert start/end times to indices
        start_idx = np.searchsorted(times, start)
        end_idx = np.searchsorted(times, end)

        segment_motion = motions_score[start_idx:end_idx]

        max_motion = np.max(segment_motion)
        p90 = np.percentile(segment_motion, 90)
        mean_motion = np.mean(segment_motion)

        burstiness = max_motion / (mean_motion + 1e-6)

        score = 0.5 * p90 + 0.3 * burstiness + 0.2 * max_motion

        segment_scores.append((start, end, score))

    # Sort descending: most exciting first
    segment_scores_sorted = sorted(segment_scores, key=lambda x: x[2], reverse=True)
    highlights = []
    for start, end, score in segment_scores_sorted:
        highlights.append(
            {"id": str(uuid.uuid4()), "start": start, "end": end, "score": score}
        )

    return highlights

    # print("Top volleys by excitement:")
    # for i, (start, end, score) in enumerate(segment_scores_sorted, 1):
    #     print(f"{i}: {format_time(start)} → {format_time(end)}, score={score:.2f}")

    # Diagram for all handball highlights, Helpful for debuggin
    # plt.figure(figsize=(12, 5))
    # plt.plot(times, motions_ma, linewidth=2, label="Moving average")
    # plt.axhline(threshold, color="red", linestyle="--", label="Threshold")

    # for start, end in segments_padded:
    #     plt.axvspan(start, end, color="green", alpha=0.2)

    # plt.xlabel("Time (seconds)")
    # plt.ylabel("Motion intensity")
    # plt.title("Detected Volleys with Threshold")
    # plt.legend()
    # plt.show()

    # # Variance diagnostics
    # variances = [v for t, m, v in motion_with_variance]
    # print(f"\nVariance stats:")
    # print(f"  Min: {np.min(variances):.2f}")
    # print(f"  25th percentile: {np.percentile(variances, 25):.2f}")
    # print(f"  Median: {np.median(variances):.2f}")
    # print(f"  75th percentile: {np.percentile(variances, 75):.2f}")
    # print(f"  90th percentile: {np.percentile(variances, 90):.2f}")
    # print(f"  Max: {np.max(variances):.2f}")

    # plt.figure(figsize=(12, 5))
    # plt.plot([t for t, m, v in motion_with_variance], variances, linewidth=2)
    # plt.axhline(
    #     VARIANCE_THRESHOLD,
    #     color="red",
    #     linestyle="--",
    #     label=f"Variance Threshold = {VARIANCE_THRESHOLD}",
    # )
    # plt.xlabel("Time (seconds)")
    # plt.ylabel("Motion Variance")
    # plt.title("Motion Variance Over Time")
    # plt.legend()
    # plt.show()
