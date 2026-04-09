import os
import tempfile
import logging

from rq import get_current_job
from clip_video import clip_and_upload_pipelined
from video_utils import process_video
from video_handle import download_file, delete_file
from compress_video import smart_compress
from email_utils import send_job_complete_email, send_job_failed_email

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}


def run_video_processing(key: str, email: str | None = None, game_type: str = "singles") -> dict:
    ext = os.path.splitext(key)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Invalid file type: {ext}")

    try:
        with tempfile.NamedTemporaryFile(delete=True, suffix=ext) as temp_video:
            download_file(key=key, destination_path=temp_video.name)
            video_path = smart_compress(temp_video.name)

            logger.info({"event": "starting_get_highlights", "key": key})

            try:
                highlight_segments = process_video(video_path, game_type=game_type)
                limited_highlights = [
                    hl for hl in highlight_segments if hl["end"] - hl["start"] <= 80
                ]
                top_20_highlights = limited_highlights[:20]
                clipped_highlights = clip_and_upload_pipelined(
                    temp_video.name, top_20_highlights
                )
            finally:
                if video_path != temp_video.name and os.path.exists(video_path):
                    os.remove(video_path)

        logger.info(
            {
                "event": "clipped_highlights",
                "key": key,
                "count": len(clipped_highlights),
            }
        )

        delete_file(key)
        logger.info({"event": "original_deleted", "key": key})

        if email:
            job = get_current_job()
            job_id = job.id if job else "unknown"
            send_job_complete_email(email, len(clipped_highlights), job_id)

        return {"key": key, "highlights": clipped_highlights}
    except Exception:
        if email:
            send_job_failed_email(email)
        raise
