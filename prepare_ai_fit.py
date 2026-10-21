import json
from pathlib import Path

try:
    import cv2
except ImportError:
    raise SystemExit("[ERROR] Missing opencv-python. Install it with: py -m pip install opencv-python")

INPUT_INDEX = Path("candidates/filtered_index.json")
OUTPUT_DIR = Path("candidates/ai_fit_frames")
OUTPUT_MANIFEST = Path("candidates/ai_fit_manifest.json")
FRAMES_PER_VIDEO = 4


def load_candidates(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"[ERROR] Missing {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("candidates", "posts", "items", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    raise SystemExit("[ERROR] Unsupported candidate index format")


def resolve_media_path(item: dict) -> Path | None:
    raw = item.get("media_path") or item.get("media") or item.get("file")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def safe_name(item: dict, position: int) -> str:
    source = (item.get("source") or item.get("channel") or "source").replace("@", "")
    source = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in source)
    message_id = item.get("message_id") or item.get("id") or position
    return f"{position:03d}_{source}_{message_id}"


def extract_frames(video_path: Path, out_dir: Path, count: int = FRAMES_PER_VIDEO) -> list[str]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    duration = total_frames / fps if fps > 0 and total_frames > 0 else None

    if total_frames <= 0:
        cap.release()
        return []

    # Avoid exact first/last frame, which are often black or transition frames.
    fractions = [(i + 1) / (count + 1) for i in range(count)]
    frame_numbers = [min(total_frames - 1, max(0, int(total_frames * f))) for f in fractions]

    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []

    for idx, frame_no in enumerate(frame_numbers, start=1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        # Keep files reasonably small for later vision-model calls.
        h, w = frame.shape[:2]
        max_side = max(h, w)
        if max_side > 1280:
            scale = 1280 / max_side
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)))

        frame_path = out_dir / f"frame_{idx:02d}.jpg"
        cv2.imwrite(str(frame_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        saved.append(str(frame_path.resolve()))

    cap.release()
    return saved, duration


def main() -> None:
    candidates = load_candidates(INPUT_INDEX)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = []
    failed = 0

    print(f"[*] Preparing {len(candidates)} candidates for AI fit")
    print(f"[*] Extracting {FRAMES_PER_VIDEO} frames per video\n")

    for position, item in enumerate(candidates, start=1):
        media = resolve_media_path(item)
        label = safe_name(item, position)
        item_dir = OUTPUT_DIR / label

        if not media or not media.exists():
            failed += 1
            print(f"[{position:02d}/{len(candidates):02d}] FAIL {label} missing media")
            continue

        result = extract_frames(media, item_dir)
        if not result:
            failed += 1
            print(f"[{position:02d}/{len(candidates):02d}] FAIL {label} unreadable video")
            continue

        frames, duration = result
        if not frames:
            failed += 1
            print(f"[{position:02d}/{len(candidates):02d}] FAIL {label} no frames")
            continue

        record = dict(item)
        record["ai_fit_frames"] = frames
        record["video_duration_seconds"] = round(duration, 2) if duration is not None else None
        manifest.append(record)
        print(f"[{position:02d}/{len(candidates):02d}] OK   {label} frames={len(frames)}")

    with OUTPUT_MANIFEST.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("\n[OK] AI-fit preparation complete.")
    print(f"     Prepared: {len(manifest)}")
    print(f"     Failed:   {failed}")
    print(f"     Manifest: {OUTPUT_MANIFEST.resolve()}")
    print(f"     Frames:   {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
