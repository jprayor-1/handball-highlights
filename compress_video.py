import subprocess
import json
import os
import logging
import tempfile

logger = logging.getLogger(__name__)

TARGET_WIDTH = 1920
TARGET_HEIGHT = 1080
TARGET_BITRATE_KBPS = 4000  # compress if above this
TARGET_CRF = 23


def probe_video(video_path: str) -> dict:
    """
    Return the first video stream's metadata via ffprobe.
    Falls back to format-level bitrate if stream bitrate is missing.
    """
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        "-select_streams", "v:0",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    streams = data.get("streams", [])
    if not streams:
        raise ValueError(f"No video streams found in {video_path}")

    stream = streams[0]

    # Backfill bitrate from format if stream doesn't have it
    if not stream.get("bit_rate"):
        format_bitrate = data.get("format", {}).get("bit_rate")
        if format_bitrate:
            stream["bit_rate"] = format_bitrate

    return stream


def needs_compression(stream: dict) -> bool:
    """
    Return True if the video should be compressed.

    Compresses if:
    - Resolution exceeds 1080p, OR
    - Bitrate exceeds TARGET_BITRATE_KBPS (and is known), OR
    - Codec is not H.264
    """
    codec = stream.get("codec_name", "")
    width = int(stream.get("width", 0))
    height = int(stream.get("height", 0))
    bit_rate_kbps = int(stream.get("bit_rate", 0) or 0) // 1000

    above_1080p = width > TARGET_WIDTH or height > TARGET_HEIGHT
    high_bitrate = bit_rate_kbps > TARGET_BITRATE_KBPS  # False if bitrate unknown (0)
    non_h264 = codec != "h264"

    return above_1080p or high_bitrate or non_h264


def _run_ffmpeg_compress(input_path: str, output_path: str) -> None:
    """Run ffmpeg to compress video to 1080p H.264."""
    scale_filter = (
        f"scale='min({TARGET_WIDTH},iw)':'min({TARGET_HEIGHT},ih)'"
        ":force_original_aspect_ratio=decrease"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", scale_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", str(TARGET_CRF),
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def smart_compress(video_path: str, output_path: str | None = None) -> str:
    """
    Compress the video only if it doesn't already meet the target spec.

    Args:
        video_path:  Path to the input video.
        output_path: Where to write the compressed file. If None, a temp file
                     is created — the caller is responsible for deleting it.

    Returns:
        Path to the video to use for downstream processing.
        If no compression was needed, returns the original video_path unchanged.
        If compression ran, returns output_path (or the auto-created temp path).
    """
    try:
        stream = probe_video(video_path)
    except Exception as e:
        logger.warning(f"Could not probe video, skipping compression: {e}")
        return video_path

    if not needs_compression(stream):
        codec = stream.get("codec_name", "?")
        width = stream.get("width", "?")
        height = stream.get("height", "?")
        bit_rate_kbps = int(stream.get("bit_rate", 0) or 0) // 1000
        logger.info(
            f"Video already meets spec ({width}x{height} {codec} {bit_rate_kbps}kbps), "
            "skipping compression."
        )
        return video_path

    codec = stream.get("codec_name", "?")
    width = stream.get("width", "?")
    height = stream.get("height", "?")
    bit_rate_kbps = int(stream.get("bit_rate", 0) or 0) // 1000
    logger.info(
        f"Compressing video: {width}x{height} {codec} {bit_rate_kbps}kbps "
        f"→ {TARGET_WIDTH}x{TARGET_HEIGHT} h264 crf={TARGET_CRF}"
    )

    if output_path is None:
        ext = os.path.splitext(video_path)[1] or ".mp4"
        fd, output_path = tempfile.mkstemp(suffix=ext)
        os.close(fd)

    try:
        _run_ffmpeg_compress(video_path, output_path)
        compressed_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        logger.info(f"Compression complete: {output_path} ({compressed_size_mb:.1f} MB)")
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg compression failed: {e.stderr}")
        if os.path.exists(output_path):
            os.remove(output_path)
        raise
