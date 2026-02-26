from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
import os


def clip_single_highlight(input_path, highlight, index):
    """Clip a single highlight."""
    start = highlight["start"]
    end = highlight["end"]
    duration = end - start

    if duration <= 0:
        return None

    highlight_id = highlight.get("id", index)
    output_file = f"highlight_{highlight_id}.mp4"

    command = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start),  # ✅ BEFORE -i (fast seek)
        "-i",
        input_path,
        "-t",
        str(duration),
        "-vf",
        "scale=1280:720",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "21",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        output_file,
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
        print(f"✓ Created {output_file}")
        return output_file
    except Exception as e:
        print(f"✗ Failed {output_file}: {e}")
        return None


def clip_all_highlights_parallel(input_path, highlights, max_workers=3):
    """
    Clip highlights in parallel (best performance + reliability).

    Args:
        input_path: Path to input video
        highlights: List of highlight dicts
        max_workers: Number of parallel ffmpeg processes (default: 3)

    Returns:
        List of output file paths
    """
    output_files = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_highlight = {
            executor.submit(clip_single_highlight, input_path, h, i): h
            for i, h in enumerate(highlights)
        }

        # Collect results as they complete
        for future in as_completed(future_to_highlight):
            result = future.result()
            if result:
                output_files.append(result)

    return output_files
