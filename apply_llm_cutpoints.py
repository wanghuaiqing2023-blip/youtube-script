import argparse
import json
from pathlib import Path

from split_sentences_stanza_dp import flatten_words, make_unit


def load_cutpoints(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data["cut_after_word_indices"], data.get("notes")
    return data, None


def validate_cutpoints(cutpoints, word_count):
    issues = []
    if not cutpoints:
        issues.append("empty_cutpoints")
        return issues
    if cutpoints != sorted(cutpoints):
        issues.append("not_sorted")
    if len(cutpoints) != len(set(cutpoints)):
        issues.append("duplicate_cutpoints")
    if cutpoints[-1] != word_count - 1:
        issues.append("missing_final_word_index")
    for index in cutpoints:
        if not isinstance(index, int):
            issues.append("non_integer_cutpoint")
            break
        if index < 0 or index >= word_count:
            issues.append("out_of_range_cutpoint")
            break
    return issues


def build_units(words, cutpoints, args):
    units = []
    start = 0
    for sentence_id, cutpoint in enumerate(cutpoints, start=1):
        end = cutpoint + 1
        if end <= start:
            continue
        units.append(make_unit(sentence_id, words[start:end], "llm_one_shot_cutpoint", args.pre_pad, args.post_pad))
        start = end
    return units


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="transcribe-whisperx_result.json")
    parser.add_argument("--cutpoints", default="llm_cutpoints_one_shot.json")
    parser.add_argument("--output", default="sentence_units_llm_one_shot.json")
    parser.add_argument("--pre-pad", type=float, default=0.25)
    parser.add_argument("--post-pad", type=float, default=0.35)
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    words = flatten_words(data)
    cutpoints, notes = load_cutpoints(args.cutpoints)
    issues = validate_cutpoints(cutpoints, len(words))
    units = build_units(words, cutpoints, args)
    assigned = sum(unit["word_count"] for unit in units)

    output = {
        "metadata": {
            "source": args.input,
            "strategy": "llm_one_shot_cutpoints",
            "uses_llm": True,
            "uses_stanza": False,
            "notes": notes,
            "sentence_count": len(units),
            "word_count": len(words),
            "assigned_word_count": assigned,
            "all_words_assigned": assigned == len(words),
            "cutpoint_count": len(cutpoints),
            "cutpoint_issues": issues,
            "padding": {"pre_seconds": args.pre_pad, "post_seconds": args.post_pad},
        },
        "sentences": units,
    }
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    durations = [unit["duration"] for unit in units]
    word_counts = [unit["word_count"] for unit in units]
    print(f"Wrote {args.output}")
    print(f"cutpoints: {len(cutpoints)}")
    print(f"units: {len(units)}")
    print(f"words assigned: {assigned}/{len(words)}")
    print(f"all words assigned: {assigned == len(words)}")
    print(f"cutpoint issues: {issues or 'none'}")
    print(f"duration min/max/avg: {min(durations):.3f}/{max(durations):.3f}/{sum(durations)/len(durations):.3f}")
    print(f"words min/max/avg: {min(word_counts)}/{max(word_counts)}/{sum(word_counts)/len(word_counts):.2f}")


if __name__ == "__main__":
    main()
