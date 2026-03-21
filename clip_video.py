from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
import os
import logging
from video_handle import upload_clip
from threading import Thread
import queue

logger = logging.getLogger(__name__)

R2_PUBLIC_URL = os.getenv(
    "R2_PUBLIC_URL", "https://pub-c14ece83a7684bd0b4dde59409667543.r2.dev"
)


def clip_and_upload_pipelined(input_path, highlights, max_workers=1):
    """
    Pipeline clipping and uploading for maximum speed.

    While clip N is uploading, clip N+1 is being created.
    """
    upload_queue = queue.Queue()
    results = []
    results_lock = __import__("threading").Lock()

    def upload_worker():
        """Background worker that uploads clips as they're ready."""
        while True:
            item = upload_queue.get()
            if item is None:  # Poison pill to stop worker
                break

            highlight_id, output_file, r2_key, highlight_info = item

            try:
                # Upload to R2
                upload_clip(output_file, r2_key)
                logger.info(f"✓ Uploaded {highlight_id} to R2")

                # Add URL to result
                highlight_info["url"] = f"{R2_PUBLIC_URL}/{r2_key}"

                with results_lock:
                    results.append(highlight_info)

                # Clean up local file
                if os.path.exists(output_file):
                    os.remove(output_file)

            except Exception as e:
                logger.error(f"✗ Upload failed for {highlight_id}: {e}")
                if os.path.exists(output_file):
                    os.remove(output_file)

            upload_queue.task_done()

    # Start upload worker thread
    upload_thread = Thread(target=upload_worker, daemon=True)
    upload_thread.start()

    def clip_single(highlight, index):
        """Clip video and queue for upload."""
        start = highlight["start"]
        end = highlight["end"]
        score = highlight["score"]
        duration = end - start

        if duration <= 0:
            return None

        highlight_id = highlight.get("id", f"highlight_{index}")
        output_file = f"/tmp/highlight_{highlight_id}.mp4"

        # Black bars (letterbox): preserve full width, pad top/bottom with black
        shorts_filter = (
            "scale=1080:1920:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
        )

        command = [
            "ffmpeg",
            "-y",
            "-ss", str(start),
            "-i", input_path,
            "-t", str(duration),
            "-vf", shorts_filter,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "21",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_file,
        ]

        try:
            # Clip video — allow 2s per second of clip plus 30s overhead
            encode_timeout = int(duration * 2) + 30
            subprocess.run(
                command, check=True, capture_output=True, text=True, timeout=encode_timeout
            )
            logger.info(f"✓ Clipped {highlight_id}: {duration:.1f}s")

            # Queue for upload (happens in background)
            r2_key = f"highlights/{highlight_id}.mp4"
            highlight_info = {
                "id": highlight_id,
                "start": start,
                "end": end,
                "score": score,
            }

            upload_queue.put((highlight_id, output_file, r2_key, highlight_info))
            return True

        except Exception as e:
            logger.error(f"✗ Failed to clip {highlight_id}: {e}")
            if os.path.exists(output_file):
                os.remove(output_file)
            return None

    # Clip all videos in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(clip_single, h, i) for i, h in enumerate(highlights)]

        # Wait for all clipping to finish
        for future in as_completed(futures):
            future.result()

    # Wait for all uploads to finish
    upload_queue.join()

    # Stop upload worker
    upload_queue.put(None)
    upload_thread.join()

    # Sort by start time
    results.sort(key=lambda x: x["start"])

    logger.info(f"✓ Processed {len(results)}/{len(highlights)} highlights")

    return results
