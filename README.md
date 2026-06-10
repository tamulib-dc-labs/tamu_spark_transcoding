# tamu_spark_transcoding

GPU-accelerated video transcoding for [Avalon Media System](https://github.com/avalonmediasystem/avalon) on an NVIDIA DGX Spark. Produces the `high`, `medium`, and `low` MP4 variants that Avalon expects when **Skip Transcoding** is set to `Yes` in the batch ingest manifest.

## Output naming convention

Avalon requires a strict naming pattern. Given `myvideo.mp4` the tool produces:

```
myvideo.high.mp4
myvideo.medium.mp4
myvideo.low.mp4
```

No extra dots are allowed in the base filename — `myvideo.test.mp4` would yield invalid output names.

In your Avalon batch manifest set the **File** column to the base name (`content/myvideo.mp4`) and **Skip Transcoding** to `Yes`. Avalon will discover the quality variants automatically.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python project/runtime manager
- `ffmpeg` compiled with NVENC support (verify with `ffmpeg -encoders | grep nvenc`)
- NVIDIA driver ≥ 520 (CUDA 11.8+), confirmed working on DGX Spark with the bundled driver stack
- Python dependency: [`tqdm`](https://tqdm.github.io/) (installed automatically by `uv sync`)

## Parallel processing

By default the tool runs **3 workers** in parallel — one per quality level — so `high`, `medium`, and `low` for the same file encode simultaneously. You can tune this with `-j`:

```bash
# default: 3 workers (all three variants of one file at once)
uv run transcode /path/to/media/

# 6 workers: two files' worth of variants concurrently
uv run transcode /path/to/media/ -j 6

# sequential (useful for debugging)
uv run transcode /path/to/media/ -j 1
```

On a DGX Spark the NVENC engine handles multiple concurrent sessions comfortably. The CUDA core utilization shown by `nvidia-smi` will remain low regardless — NVENC/NVDEC are fixed-function silicon separate from the CUDA cores. Use `nvidia-smi --query-gpu=encoder.stats.sessionCount,encoder.stats.averageFps --format=csv` to see actual encoder activity.

## Progress display

A single progress bar tracks all (file × quality) jobs:

```
Found 4 file(s) → 12 transcode job(s) — 3 worker(s)
 58%|██████████████          | 7/12 [02:14<01:35, file=game_film.mp4, quality=low]
```

ffmpeg errors are written above the bar via `tqdm.write` so they don't corrupt the display. Logging output is suppressed by default — pass `-v` to enable debug output.

## Quick start

```bash
# Install dependencies and create the virtual environment
uv sync

# Transcode a single file (all three quality levels)
uv run transcode /path/to/myvideo.mp4

# Transcode an entire directory tree recursively
uv run transcode /path/to/media/

# Write output files to a separate directory
uv run transcode /path/to/media/ --output-dir /path/to/avalon-dropbox/

# Produce only high and medium variants
uv run transcode /path/to/media/ --qualities high medium

# Skip files that have already been transcoded
uv run transcode /path/to/media/ --skip-existing

# Preview commands without running ffmpeg
uv run transcode /path/to/media/ --dry-run

# Use a specific GPU (default: 0)
uv run transcode /path/to/media/ --gpu 1

# Verbose / debug logging
uv run transcode /path/to/media/ -v
```

## Encoding profiles

| Quality | Resolution | Video bitrate | Audio |
|---------|-----------|---------------|-------|
| high    | original  | 4 000 kbps    | AAC 128 kbps stereo |
| medium  | 1280×720  | 1 500 kbps    | AAC 128 kbps stereo |
| low     | 640×360   | 500 kbps      | AAC 96 kbps stereo  |

All profiles use `h264_nvenc` (NVIDIA NVENC) with hardware-accelerated decode (`-hwaccel cuda`). Frames stay on the GPU between decode and encode when no scaling is needed; the `scale_cuda` filter is used for the medium and low profiles to keep the pipeline fully on-GPU.

Profiles are defined in [`src/tamu_spark_transcoding/profiles.py`](src/tamu_spark_transcoding/profiles.py) — edit bitrates, presets, and resolutions there.

## Filename sanitization

Avalon does not allow extra dots in variant filenames. The tool automatically sanitizes stems before writing output:

| Rule | Example input stem | Result |
|------|--------------------|--------|
| `". "` (period-space) collapsed to `-` | `1. Film Title` | `1-Film_Title` |
| remaining spaces → `_` | `Film Title` | `Film_Title` |
| remaining periods → `-` | `film.title` | `film-title` |

A warning is logged whenever a name is changed. The sanitized name is what goes in your Avalon manifest.

## Avalon batch ingest manifest

After transcoding, build your manifest CSV. The key columns for pre-transcoded files:

| File | Skip Transcoding | … |
|------|-----------------|---|
| content/myvideo.mp4 | Yes | … |

Place `myvideo.high.mp4`, `myvideo.medium.mp4`, and `myvideo.low.mp4` alongside `myvideo.mp4` in the Avalon dropbox directory. Avalon resolves the variants automatically from the base filename.

## Project layout

```
tamu_spark_transcoding/
├── pyproject.toml                        # uv/hatch project config
├── src/
│   └── tamu_spark_transcoding/
│       ├── __init__.py
│       ├── profiles.py                   # encoding profile definitions
│       └── transcode.py                  # CLI entry point
└── README.md
```

## Development

```bash
uv sync
uv run pytest
```
