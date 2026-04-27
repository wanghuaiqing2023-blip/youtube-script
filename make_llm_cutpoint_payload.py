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


def build_indexed_token_view(words, style):
    """
    Build an LLM-friendly transcript string where every token carries
    its original absolute word index.
    """
    if style == "suffix":
        return " ".join(f"{item['w']}[{item['i']}]" for item in words)
    if style == "prefix":
        return " ".join(f"[{item['i']}]{item['w']}" for item in words)
    raise ValueError(f"Unsupported index style: {style}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="transcribe-whisperx_result.json")
    parser.add_argument("--output", default="llm_cutpoint_payload.json")
    parser.add_argument("--max-duration", type=float, default=18.0)
    parser.add_argument("--target-duration", type=float, default=8.0)
    parser.add_argument("--soft-max-duration", type=float, default=22.0)
    parser.add_argument(
        "--index-style",
        choices=["suffix", "prefix"],
        default="suffix",
        help="How to represent index-attached tokens in indexed_text.",
    )
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    words = flatten_words(data)
    indexed_text = build_indexed_token_view(words, args.index_style)
    payload = {
        "task": "Return timestamp-preserving semantic audio unit cut points for a WhisperX transcript.",
        "language": "English",
        "input_format": "Each item is one WhisperX word token with i=original word index, w=word text, s=start seconds, e=end seconds.",
        "indexed_text_format": f"Each token is annotated with its original index using {args.index_style} style.",
        "hard_rules": [
            "Return cut points only, not rewritten text.",
            "A cut point means cut AFTER the word with that original index.",
            "Use the attached token indices as the single source of truth when deciding cut positions.",
            "Do not omit, duplicate, reorder, or edit any word.",
            "Every word must belong to exactly one unit.",
            "Do not cut inside a grammatically dependent phrase or clause.",
            "Do not separate subject from predicate, auxiliary from verb, verb from required object/complement, preposition from object, or infinitive marker from verb/object.",
            "Do not separate quote/example introducers from the quoted/example content, for example: 'they would say, X' should stay together.",
            "Do not split fixed contrast/condition structures such as 'instead of X, Y', 'if X, Y', 'when X, Y', 'because X, Y'.",
            "Keep tightly related teaching examples, repeated pronunciation examples, and enumerated word lists together unless the group becomes too long.",
            "Semantic completeness is more important than duration.",
        ],
        "timing_rules": [
            f"Prefer units near {args.target_duration} seconds when safe.",
            f"Try not to exceed {args.max_duration} seconds.",
            f"If no safe cut exists, allow up to about {args.soft_max_duration} seconds instead of making a half sentence.",
            "Prefer cuts after complete clauses, complete examples, list groups, topic transitions, or clear pauses.",
        ],
        "output_schema": {
            "cut_after_word_indices": [
                "integer original word indices; sorted ascending; include the final word index"
            ],
            "notes": "optional very short string; no transcript text",
        },
        "indexed_text": indexed_text,
        "words": words,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"words: {len(words)}")
    print(f"first_index: {words[0]['i']}")
    print(f"last_index: {words[-1]['i']}")
    print(f"index_style: {args.index_style}")


if __name__ == "__main__":
    main()
