# -*- coding: utf-8 -*-
"""Prepare visual reference frames from exported channel history.

Reads references/index.json produced by export_references.py.
For videos, extracts 4 representative frames.
For photos, writes one resized JPEG.
Outputs references/reference_manifest.json and references/reference_frames/.

Requires: opencv-python
"""

import json
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    raise SystemExit("[ERROR] Missing opencv-python. Install it with: py -m pip install opencv-python")

REFERENCES_INDEX = Path("references/index.json")
OUTPUT_DIR = Path("references/reference_frames")
MANIFEST_PATH = Path("references/reference_manifest.json")
FRAMES_PER_VIDEO = 4
MAX_WIDTH = 960
JPEG_QUALITY = 85


def load_posts(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        posts = data.get("posts")
        if isinstance(posts, list):
            return [x for x in posts if isinstance(x, dict)]
    raise SystemExit(f"[ERROR] Unsupported index format: {path}")


def resize_frame(frame):
    h, w = frame.shape[:2]
    if w <= MAX_WIDTH:
        return frame
    scale = MAX_WIDTH / float(w)
    return cv2.resize(frame, (MAX_WIDTH, max(1, int(h * scale))), interpolation=cv2.INTER_AREA)


def save_jpeg(frame, path: Path) -> bool:
    frame = resize_frame(frame)
    path.parent.mkdir(parents=True, exist_ok=True)
    return bool(cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]))


def extract_video_frames(media: Path, out_dir: Path) -> list[str]:
    cap = cv2.VideoCapture(str(media))
    if not cap.isOpened():
        return []

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if frame_count <= 0:
        cap.release()
        return []

    # Avoid the very first/last frame; sample across the useful interior.
    fractions = [0.10, 0.35, 0.65, 0.90]
    paths: list[str] = []

    for i, frac in enumerate(fractions[:FRAMES_PER_VIDEO], start=1):
        idx = min(frame_count - 1, max(0, int((frame_count - 1) * frac)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        dest = out_dir / f"frame_{i:02d}.jpg"
        if save_jpeg(frame, dest):
            paths.append(str(dest.resolve()))

    cap.release()
    return paths


def prepare_photo(media: Path, out_dir: Path) -> list[str]:
    # cv2.imread can fail on Windows paths containing Cyrillic characters.
    # Reading raw bytes first keeps Unicode paths working reliably.
    try:
        raw = np.fromfile(str(media), dtype=np.uint8)
    except OSError:
        return []
    if raw.size == 0:
        return []
    frame = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if frame is None:
        return []
    dest = out_dir / "frame_01.jpg"
    if save_jpeg(frame, dest):
        return [str(dest.resolve())]
    return []


def main() -> None:
    if not REFERENCES_INDEX.exists():
        raise SystemExit(f"[ERROR] Missing {REFERENCES_INDEX}")

    posts = load_posts(REFERENCES_INDEX)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    prepared = []
    failed = 0

    print(f"[*] Preparing {len(posts)} channel references for AI fit")
    print(f"[*] Videos: up to {FRAMES_PER_VIDEO} frames; photos: 1 frame\n")

    for pos, item in enumerate(posts, start=1):
        media_raw = item.get("media_path")
        media_type = (item.get("media_type") or "").lower()
        post_id = item.get("id", pos)
        out_dir = OUTPUT_DIR / str(post_id)

        frame_paths: list[str] = []
        if media_raw:
            media = Path(media_raw)
            if media.exists() and media.is_file():
                if media_type == "video" or media.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
                    frame_paths = extract_video_frames(media, out_dir)
                elif media_type == "photo" or media.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
                    frame_paths = prepare_photo(media, out_dir)

        if not frame_paths:
            failed += 1
            status = "SKIP"
        else:
            status = "OK"
            prepared.append({
                "id": post_id,
                "date": item.get("date"),
                "text": item.get("text", ""),
                "media_type": item.get("media_type"),
                "post_url": item.get("post_url"),
                "media_path": media_raw,
                "frame_paths": frame_paths,
            })

        print(f"[{pos:02d}/{len(posts):02d}] {status:<4} {post_id} frames={len(frame_paths)}")

    manifest = {
        "reference_count": len(prepared),
        "failed": failed,
        "references": prepared,
    }
    with MANIFEST_PATH.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("\n[OK] Reference preparation complete.")
    print(f"     Prepared: {len(prepared)}")
    print(f"     Failed:   {failed}")
    print(f"     Manifest: {MANIFEST_PATH.resolve()}")
    print(f"     Frames:   {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
