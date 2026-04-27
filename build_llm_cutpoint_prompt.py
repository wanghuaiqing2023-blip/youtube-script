import argparse
import json
from pathlib import Path


def flatten_words(data):
    words = []
    for index, item in enumerate(data["word_segments"]):
        words.append(
            {
                "i": index,
                "w": item["word"],
                "s": round(float(item["start"]), 3),
                "e": round(float(item["end"]), 3),
            }
        )
    return words


def build_indexed_token_view(words, style="suffix"):
    if style == "suffix":
        return " ".join(f"{item['w']}[{item['i']}]" for item in words)
    if style == "prefix":
        return " ".join(f"[{item['i']}]{item['w']}" for item in words)
    raise ValueError(f"Unsupported index style: {style}")


def build_prompt(words, index_style, target_duration, max_duration, soft_max_duration):
    indexed_text = build_indexed_token_view(words, index_style)
    last_index = words[-1]["i"]

    prompt = f"""You are given a WhisperX transcript represented as index-annotated tokens.
Each token has a unique absolute word index.

Task:
Return semantic audio-unit cut points.
A cut point means CUT AFTER that index.

Hard rules:
1) Return cut points only, not rewritten transcript text.
2) Use token indices as the single source of truth.
3) Do not omit, duplicate, reorder, or edit words.
4) Every word must belong to exactly one unit.
5) Do not split inside strongly dependent grammar structures.
6) Keep quote/example introducers with their content.
7) Keep tightly related list/example groups together unless too long.
8) Include the final index {last_index} in cut_after_word_indices.

Timing preference:
- Prefer around {target_duration} seconds per unit when safe.
- Try not to exceed {max_duration} seconds.
- If needed for semantic completeness, allow up to about {soft_max_duration} seconds.

Output format (strict JSON):
{{
  "cut_after_word_indices": [<ascending integers, must include {last_index}>],
  "notes": "optional short note"
}}

Indexed transcript ({index_style} style):
{indexed_text}
"""
    return prompt


def main():
    parser = argparse.ArgumentParser(
        description="Convert transcribe-whisperx_result.json into an LLM prompt for cut-point generation."
    )
    parser.add_argument("--input", default="transcribe-whisperx_result.json")
    parser.add_argument("--output", default="llm_cutpoint_prompt.txt")
    parser.add_argument("--index-style", choices=["suffix", "prefix"], default="suffix")
    parser.add_argument("--target-duration", type=float, default=8.0)
    parser.add_argument("--max-duration", type=float, default=18.0)
    parser.add_argument("--soft-max-duration", type=float, default=22.0)
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    words = flatten_words(data)
    if not words:
        raise ValueError("No words found in input JSON.")

    prompt = build_prompt(
        words=words,
        index_style=args.index_style,
        target_duration=args.target_duration,
        max_duration=args.max_duration,
        soft_max_duration=args.soft_max_duration,
    )

    Path(args.output).write_text(prompt, encoding="utf-8")
    print(f"Wrote prompt: {args.output}")
    print(f"word_count: {len(words)}")
    print(f"first_index: {words[0]['i']}")
    print(f"last_index: {words[-1]['i']}")
    print(f"index_style: {args.index_style}")


if __name__ == "__main__":
    main()
