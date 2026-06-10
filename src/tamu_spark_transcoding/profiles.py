"""Encoding profiles for Avalon Media System HLS variants."""

# All profiles use NVIDIA NVENC for GPU-accelerated H.264 encoding.
# Audio is re-encoded to AAC stereo at 128 kbps for broad compatibility.
PROFILES = {
    "high": {
        "video_codec": "h264_nvenc",
        "video_bitrate": "4000k",
        "maxrate": "4500k",
        "bufsize": "8000k",
        "audio_codec": "aac",
        "audio_bitrate": "128k",
        "audio_channels": 2,
        "preset": "p4",       # NVENC quality preset (p1 fastest … p7 slowest)
        "profile": "high",
        "level": "4.1",
        "scale": None,        # keep original resolution
    },
    "medium": {
        "video_codec": "h264_nvenc",
        "video_bitrate": "1500k",
        "maxrate": "1800k",
        "bufsize": "3000k",
        "audio_codec": "aac",
        "audio_bitrate": "128k",
        "audio_channels": 2,
        "preset": "p4",
        "profile": "main",
        "level": "3.1",
        "scale": "1280:720",  # 720p
    },
    "low": {
        "video_codec": "h264_nvenc",
        "video_bitrate": "500k",
        "maxrate": "600k",
        "bufsize": "1000k",
        "audio_codec": "aac",
        "audio_bitrate": "96k",
        "audio_channels": 2,
        "preset": "p4",
        "profile": "baseline",
        "level": "3.0",
        "scale": "640:360",   # 360p
    },
}
