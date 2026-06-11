"""GPU-accelerated transcoding for Avalon Media System using NVENC on DGX Spark."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

from .profiles import PROFILES

log = logging.getLogger(__name__)

VALID_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".mxf", ".m4v"}


def sanitize_stem(stem: str) -> str:
    """Replace characters that break Avalon's quality-variant filename convention.

    Avalon parses quality variants by splitting on the *last* dot before the
    extension, so any extra dots in the stem make the variant unrecognizable.
    Spaces cause problems for some ingest tooling as well.

    Rules applied:
      - ". " (period-space, e.g. numbered titles) → hyphen, collapsed as a unit
      - remaining spaces → underscore
      - remaining periods → hyphen
    """
    stem = stem.replace(". ", "-")
    return stem.replace(" ", "_").replace(".", "-").replace("&", "and")


def build_ffmpeg_cmd(
    input_path: Path,
    output_path: Path,
    profile: dict,
    gpu_index: int = 0,
) -> list[str]:
    cmd = [
        "ffmpeg",
        "-y",                           # overwrite without prompting
        "-hwaccel", "cuda",
        "-hwaccel_device", str(gpu_index),
        "-hwaccel_output_format", "cuda",
        "-extra_hw_frames", "4",        # extra surfaces for scale_cuda filter pipeline
        "-threads", "1",                # prevent NVDEC surface exhaustion under parallel jobs
        "-fflags", "+discardcorrupt",   # skip corrupted packets rather than aborting
        "-i", str(input_path),
        "-c:v", profile["video_codec"],
        "-preset", profile["preset"],
        "-profile:v", profile["profile"],
        "-level:v", profile["level"],
        "-b:v", profile["video_bitrate"],
        "-maxrate", profile["maxrate"],
        "-bufsize", profile["bufsize"],
    ]

    if profile["scale"]:
        # scale_cuda keeps frames on the GPU; pad ensures even dimensions
        cmd += ["-vf", f"scale_cuda={profile['scale']}:force_original_aspect_ratio=decrease"]

    cmd += [
        "-c:a", profile["audio_codec"],
        "-b:a", profile["audio_bitrate"],
        "-ac", str(profile["audio_channels"]),
        str(output_path),
    ]
    return cmd


def output_path_for(input_path: Path, quality: str, output_dir: Path | None) -> Path:
    stem = sanitize_stem(input_path.stem)
    if stem != input_path.stem:
        tqdm.write(f"WARNING: sanitized '{input_path.stem}' → '{stem}'")
    dest_dir = output_dir if output_dir else input_path.parent
    return dest_dir / f"{stem}.{quality}.mp4"


def transcode_one(
    input_path: Path,
    quality: str,
    output_dir: Path | None,
    gpu_index: int,
    dry_run: bool,
    skip_existing: bool,
) -> tuple[Path, str, bool]:
    """Transcode a single (file, quality) pair. Returns (path, quality, success)."""
    out = output_path_for(input_path, quality, output_dir)

    if skip_existing and out.exists():
        log.debug("Skipping existing %s", out)
        return input_path, quality, True

    profile = PROFILES[quality]
    cmd = build_ffmpeg_cmd(input_path, out, profile, gpu_index)
    log.debug("Command: %s", " ".join(cmd))

    if dry_run:
        tqdm.write(f"DRY RUN: {' '.join(cmd)}")
        return input_path, quality, True

    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        tqdm.write(f"ERROR: ffmpeg failed — {input_path.name} [{quality}]")
        tqdm.write(proc.stderr.decode(errors="replace"))
        return input_path, quality, False

    return input_path, quality, True


def find_inputs(root: Path, recursive: bool) -> list[Path]:
    if root.is_file():
        return [root]
    pattern = "**/*" if recursive else "*"
    return sorted(
        p for p in root.glob(pattern)
        if p.is_file()
        and p.suffix.lower() in VALID_SUFFIXES
        # skip already-transcoded variants (check both raw and sanitized stem)
        and not any(p.stem.endswith(f".{q}") for q in PROFILES)
        and not any(sanitize_stem(p.stem).endswith(f"-{q}") for q in PROFILES)
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transcode video files for Avalon Media System using NVIDIA GPU on DGX Spark.",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Input file or directory to transcode.",
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: same directory as each input file).",
    )
    parser.add_argument(
        "-q", "--qualities",
        nargs="+",
        choices=list(PROFILES),
        default=list(PROFILES),
        metavar="QUALITY",
        help="Quality levels to produce: high medium low (default: all three).",
    )
    parser.add_argument(
        "-j", "--workers",
        type=int,
        default=3,
        metavar="N",
        help="Number of parallel ffmpeg workers (default: 3, one per quality level).",
    )
    parser.add_argument(
        "--gpu",
        type=int,
        default=0,
        metavar="N",
        help="GPU device index (default: 0).",
    )
    parser.add_argument(
        "--no-recurse",
        action="store_true",
        help="Do not recurse into subdirectories.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip output files that already exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print ffmpeg commands without executing them.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    inputs = find_inputs(args.input, recursive=not args.no_recurse)
    if not inputs:
        print(f"No valid input files found at: {args.input}", file=sys.stderr)
        sys.exit(1)

    # Build the full list of (file, quality) jobs
    jobs = [(path, quality) for path in inputs for quality in args.qualities]
    total_jobs = len(jobs)

    print(f"Found {len(inputs)} file(s) → {total_jobs} transcode job(s) — {args.workers} worker(s)")

    failures: list[tuple[Path, str]] = []

    with tqdm(total=total_jobs, unit="variant") as bar:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    transcode_one,
                    path, quality, args.output_dir,
                    args.gpu, args.dry_run, args.skip_existing,
                ): (path, quality)
                for path, quality in jobs
            }
            for future in as_completed(futures):
                path, quality, ok = future.result()
                if not ok:
                    failures.append((path, quality))
                bar.set_postfix(file=path.name, quality=quality)
                bar.update(1)

    if failures:
        print(f"\n{len(failures)} job(s) failed:", file=sys.stderr)
        for path, quality in failures:
            print(f"  {path} [{quality}]", file=sys.stderr)
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()
