# -*- coding: utf-8 -*-
"""Score cleaned Telegram video candidates against channel references using a vision-capable LLM.

Inputs:
  references/reference_manifest.json
  candidates/ai_fit_manifest.json

Outputs:
  candidates/ai_fit_scores.json
  candidates/channel_style_profile.json

Provider selection:
  - If OPENAI_API_KEY is present, uses OpenAI directly.
  - Else if OPENROUTER_API_KEY is present, uses OpenRouter's OpenAI-compatible API.

Optional env vars:
  AI_FIT_MODEL        model name (defaults depend on provider)
  AI_FIT_LIMIT        score only first N candidates (0 = all)
  AI_FIT_MIN_SCORE    display threshold only; default 60

This script does NOT publish anything.
"""

import base64
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

REFERENCE_MANIFEST = Path("references/reference_manifest.json")
CANDIDATE_MANIFEST = Path("candidates/ai_fit_manifest.json")
PROFILE_PATH = Path("candidates/channel_style_profile.json")
SCORES_PATH = Path("candidates/ai_fit_scores.json")

LIMIT = int(os.getenv("AI_FIT_LIMIT", "0") or 0)
MIN_SCORE = int(os.getenv("AI_FIT_MIN_SCORE", "60") or 60)


def die(msg: str):
    raise SystemExit(f"[ERROR] {msg}")


def load_json(path: Path):
    if not path.exists():
        die(f"Missing {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def make_client():
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()

    if openai_key:
        model = os.getenv("AI_FIT_MODEL", "gpt-4.1-mini").strip()
        return OpenAI(api_key=openai_key), model, "openai"

    if openrouter_key:
        model = os.getenv("AI_FIT_MODEL", "openai/gpt-4.1-mini").strip()
        client = OpenAI(
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://github.com/koshakmd/ai-content-bot",
                "X-Title": "Koshak Content Lab",
            },
        )
        return client, model, "openrouter"

    die("No OPENAI_API_KEY or OPENROUTER_API_KEY found in .env")


def image_data_url(path: Path) -> str:
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64,{b64}"


def vision_message(text: str, image_paths: list[Path]):
    content = [{"type": "text", "text": text}]
    for p in image_paths:
        if p.exists() and p.is_file():
            content.append({
                "type": "image_url",
                "image_url": {"url": image_data_url(p), "detail": "low"},
            })
    return content


def call_text(client: OpenAI, model: str, messages, max_tokens=900) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def extract_json_object(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("No JSON object found")
    return json.loads(m.group(0))


def first_frame(ref: dict) -> Path | None:
    frames = ref.get("frame_paths") or []
    if not frames:
        return None
    p = Path(frames[0])
    return p if p.exists() else None


def build_style_profile(client: OpenAI, model: str, references: list[dict]) -> dict:
    if PROFILE_PATH.exists():
        try:
            cached = load_json(PROFILE_PATH)
            if cached.get("profile"):
                print("[*] Reusing existing channel style profile")
                return cached
        except Exception:
            pass

    usable = [r for r in references if first_frame(r)]
    if not usable:
        die("No usable reference frames")

    batch_summaries = []
    batch_size = 8
    print(f"[*] Building channel style profile from {len(usable)} references")

    for start in range(0, len(usable), batch_size):
        batch = usable[start:start + batch_size]
        paths = [first_frame(r) for r in batch]
        labels = []
        for r in batch:
            txt = (r.get("text") or "").replace("\n", " ").strip()
            labels.append(f"post {r.get('id')}: {txt[:180]}")

        prompt = (
            "These images are representative posts from a Telegram humor channel called "
            "«Нормально же общались». Describe the recurring content taste, not image quality. "
            "Focus on humor type, situations, social awkwardness, absurdity, people/animals, danger/fails, "
            "tone, what seems intentionally selected, and what would probably be off-brand. "
            "Be concise and concrete. Associated captions:\n" + "\n".join(labels)
        )

        summary = call_text(
            client,
            model,
            [{"role": "user", "content": vision_message(prompt, [p for p in paths if p])}],
            max_tokens=700,
        )
        batch_summaries.append(summary)
        print(f"    reference batch {start // batch_size + 1}: OK")

    synth_prompt = (
        "Synthesize these observations about one Telegram humor channel into a practical editorial profile. "
        "Return JSON only with keys: core_taste (array of 5-8 strings), avoid (array of 4-8 strings), "
        "caption_style (string), selection_rule (string). Do not invent demographic facts.\n\n" +
        "\n\n---\n\n".join(batch_summaries)
    )
    raw = call_text(client, model, [{"role": "user", "content": synth_prompt}], max_tokens=900)
    try:
        profile = extract_json_object(raw)
    except Exception:
        profile = {
            "core_taste": batch_summaries,
            "avoid": [],
            "caption_style": "",
            "selection_rule": "",
        }

    wrapped = {
        "model": model,
        "reference_count": len(usable),
        "profile": profile,
    }
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(wrapped, ensure_ascii=False, indent=2), encoding="utf-8")
    return wrapped


def score_candidate(client: OpenAI, model: str, profile: dict, item: dict) -> dict:
    frames = [Path(p) for p in (item.get("frame_paths") or []) if Path(p).exists()]
    if not frames:
        raise ValueError("No frames")

    text = (item.get("text") or "").strip()
    source = item.get("source") or item.get("channel") or "unknown"
    profile_text = json.dumps(profile.get("profile", {}), ensure_ascii=False)

    prompt = f"""You are selecting content for the Telegram humor channel «Нормально же общались».

Editorial profile:
{profile_text}

Candidate source: {source}
Candidate caption: {text[:600]}

Look at ALL supplied frames as one video candidate. Score editorial fit, not technical video quality.
Return JSON only:
{{
  "score": integer 0-100,
  "verdict": "strong" | "maybe" | "skip",
  "reason": "one short Russian sentence",
  "tags": ["2-5 short Russian tags"]
}}

Score guide:
80-100: very likely the channel owner would post it.
60-79: plausible, worth human review.
40-59: weak fit.
0-39: off-brand, promotional, boring, newsy, or wrong humor.
"""

    raw = call_text(
        client,
        model,
        [{"role": "user", "content": vision_message(prompt, frames[:4])}],
        max_tokens=350,
    )
    data = extract_json_object(raw)
    try:
        score = int(data.get("score", 0))
    except Exception:
        score = 0
    data["score"] = max(0, min(100, score))
    return data


def main():
    refs_data = load_json(REFERENCE_MANIFEST)
    cand_data = load_json(CANDIDATE_MANIFEST)

    references = refs_data.get("references", []) if isinstance(refs_data, dict) else refs_data
    candidates = cand_data.get("candidates", []) if isinstance(cand_data, dict) else cand_data
    if not isinstance(references, list) or not isinstance(candidates, list):
        die("Unsupported manifest format")

    if LIMIT > 0:
        candidates = candidates[:LIMIT]

    client, model, provider = make_client()
    print(f"[*] Provider: {provider}")
    print(f"[*] Model:    {model}")
    print(f"[*] Candidates to score: {len(candidates)}")

    profile = build_style_profile(client, model, references)
    print("[*] Channel style profile ready\n")

    results = []
    for i, item in enumerate(candidates, start=1):
        candidate_id = item.get("candidate_id") or item.get("id") or item.get("message_id") or i
        try:
            rating = score_candidate(client, model, profile, item)
            row = {**item, **rating}
            results.append(row)
            print(f"[{i:02d}/{len(candidates):02d}] {candidate_id} score={rating['score']:3d} {rating.get('verdict', '')}")
        except Exception as exc:
            results.append({**item, "score": None, "verdict": "error", "reason": str(exc), "tags": []})
            print(f"[{i:02d}/{len(candidates):02d}] {candidate_id} ERROR {exc}")

        # Save after every candidate so an interrupted run can still be inspected.
        ranked = sorted(results, key=lambda x: (x.get("score") is not None, x.get("score") or -1), reverse=True)
        SCORES_PATH.write_text(json.dumps({
            "provider": provider,
            "model": model,
            "scored": len(results),
            "min_review_score": MIN_SCORE,
            "results": ranked,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    ranked = sorted(results, key=lambda x: (x.get("score") is not None, x.get("score") or -1), reverse=True)
    review = [x for x in ranked if isinstance(x.get("score"), int) and x["score"] >= MIN_SCORE]

    print("\n[OK] AI-fit scoring complete.")
    print(f"     Scored: {len(results)}")
    print(f"     Review candidates >= {MIN_SCORE}: {len(review)}")
    print(f"     Scores: {SCORES_PATH.resolve()}")
    print(f"     Profile: {PROFILE_PATH.resolve()}")


if __name__ == "__main__":
    main()
