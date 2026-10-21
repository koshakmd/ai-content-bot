import hashlib
import json
from pathlib import Path

CANDIDATES_INDEX = Path("candidates/index.json")
REFERENCES_INDEX = Path("references/index.json")
OUTPUT_INDEX = Path("candidates/filtered_index.json")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_media_path(item: dict) -> Path | None:
    raw = item.get("media_path") or item.get("media") or item.get("file")
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def main():
    if not CANDIDATES_INDEX.exists():
        raise SystemExit(f"[ERROR] Missing {CANDIDATES_INDEX}")

    candidates = load_json(CANDIDATES_INDEX)
    references = load_json(REFERENCES_INDEX) if REFERENCES_INDEX.exists() else []

    reference_hashes = set()
    reference_files = 0
    for item in references:
        media = resolve_media_path(item)
        if media and media.exists() and media.is_file():
            try:
                reference_hashes.add(sha256_file(media))
                reference_files += 1
            except OSError:
                pass

    seen_candidate_hashes = {}
    kept = []
    removed = []

    promo_removed = 0
    duplicate_candidate_removed = 0
    duplicate_reference_removed = 0
    missing_media_removed = 0

    for item in candidates:
        source = item.get("source") or item.get("channel") or "unknown"
        message_id = item.get("message_id") or item.get("id")

        if item.get("promotional") or item.get("promo") or item.get("is_promo"):
            removed.append({**item, "filter_reason": "promo"})
            promo_removed += 1
            continue

        media = resolve_media_path(item)
        if not media or not media.exists() or not media.is_file():
            removed.append({**item, "filter_reason": "missing_media"})
            missing_media_removed += 1
            continue

        try:
            digest = sha256_file(media)
        except OSError:
            removed.append({**item, "filter_reason": "missing_media"})
            missing_media_removed += 1
            continue

        if digest in reference_hashes:
            removed.append({**item, "sha256": digest, "filter_reason": "already_in_references"})
            duplicate_reference_removed += 1
            continue

        if digest in seen_candidate_hashes:
            removed.append({
                **item,
                "sha256": digest,
                "filter_reason": "duplicate_candidate",
                "duplicate_of": seen_candidate_hashes[digest],
            })
            duplicate_candidate_removed += 1
            continue

        key = f"{source}:{message_id}"
        seen_candidate_hashes[digest] = key
        kept.append({**item, "sha256": digest})

    OUTPUT_INDEX.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_INDEX.open("w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)

    removed_path = OUTPUT_INDEX.with_name("removed_index.json")
    with removed_path.open("w", encoding="utf-8") as f:
        json.dump(removed, f, ensure_ascii=False, indent=2)

    print(f"[*] Candidates loaded: {len(candidates)}")
    print(f"[*] Reference media hashed: {reference_files}")
    print()
    print(f"[OK] Kept: {len(kept)}")
    print(f"     Promo removed: {promo_removed}")
    print(f"     Duplicate candidates removed: {duplicate_candidate_removed}")
    print(f"     Already in references removed: {duplicate_reference_removed}")
    print(f"     Missing media removed: {missing_media_removed}")
    print()
    print(f"     Clean index:   {OUTPUT_INDEX.resolve()}")
    print(f"     Removed index: {removed_path.resolve()}")


if __name__ == "__main__":
    main()
