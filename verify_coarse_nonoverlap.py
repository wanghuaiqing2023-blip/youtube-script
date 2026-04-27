import argparse
import json
from pathlib import Path

import stanza

from split_sentences_grammar_coarse import (
    build_text_and_spans,
    repair_coarse_ranges,
    stanza_sentence_ranges,
    text_from_words,
)
from split_sentences_stanza_dp import flatten_words


def summarize_ranges(words, ranges):
    overlaps = []
    gaps = []
    for prev, current in zip(ranges, ranges[1:]):
        prev_end = prev[1]
        current_start = current[0]
        if current_start < prev_end:
            overlaps.append((prev, current))
        elif current_start > prev_end:
            gaps.append((prev_end, current_start))

    covered = sum(end - start for start, end, _ in ranges)
    return {
        "range_count": len(ranges),
        "word_count": len(words),
        "covered_word_count": covered,
        "starts_at_zero": bool(ranges and ranges[0][0] == 0),
        "ends_at_word_count": bool(ranges and ranges[-1][1] == len(words)),
        "has_overlap": bool(overlaps),
        "has_gap": bool(gaps),
        "overlap_count": len(overlaps),
        "gap_count": len(gaps),
        "max_words": max((end - start for start, end, _ in ranges), default=0),
        "max_duration": max((words[end - 1]["end"] - words[start]["start"] for start, end, _ in ranges), default=0),
        "overlaps": overlaps[:10],
        "gaps": gaps[:10],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="transcribe-whisperx_result.json")
    parser.add_argument("--model-dir", default="stanza_resources")
    parser.add_argument("--output", default="coarse_nonoverlap_report.json")
    parser.add_argument("--preview", type=int, default=12)
    parser.add_argument("--coarse-max-words", type=int, default=180)
    parser.add_argument("--coarse-max-duration", type=float, default=65.0)
    parser.add_argument("--merge-list-groups", action="store_true")
    parser.add_argument("--list-group-max-words", type=int, default=80)
    parser.add_argument("--list-group-max-duration", type=float, default=24.0)
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    words = flatten_words(data)
    text, spans = build_text_and_spans(words)

    nlp = stanza.Pipeline(
        "en",
        model_dir=args.model_dir,
        processors="tokenize,pos,lemma,depparse",
        use_gpu=False,
        verbose=False,
        download_method=None,
    )
    doc = nlp(text)

    raw_ranges = stanza_sentence_ranges(doc, spans, len(words))
    coarse_ranges = repair_coarse_ranges(words, raw_ranges, args)
    summary = summarize_ranges(words, coarse_ranges)

    preview = []
    for index, (start, end, reason) in enumerate(coarse_ranges[: args.preview], start=1):
        block_words = words[start:end]
        preview.append(
            {
                "id": index,
                "start_word_index": start,
                "end_word_index": end - 1,
                "word_count": end - start,
                "start": round(block_words[0]["start"], 3),
                "end": round(block_words[-1]["end"], 3),
                "duration": round(block_words[-1]["end"] - block_words[0]["start"], 3),
                "reason": reason,
                "text": text_from_words(block_words),
            }
        )

    report = {
        "input": args.input,
        "strategy": "stanza_sentence_ranges_plus_coarse_repairs",
        "summary": summary,
        "preview": preview,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {args.output}")
    print(f"coarse ranges: {summary['range_count']}")
    print(f"words covered: {summary['covered_word_count']}/{summary['word_count']}")
    print(f"starts at 0: {summary['starts_at_zero']}")
    print(f"ends at word count: {summary['ends_at_word_count']}")
    print(f"has overlap: {summary['has_overlap']} ({summary['overlap_count']})")
    print(f"has gap: {summary['has_gap']} ({summary['gap_count']})")
    print(f"max words: {summary['max_words']}")
    print(f"max duration: {summary['max_duration']:.3f}")
    print()
    for item in preview:
        text = item["text"]
        if len(text) > 160:
            text = text[:160] + "..."
        print(
            f"{item['id']:03d} words {item['start_word_index']}-{item['end_word_index']} "
            f"{item['duration']:.3f}s {item['word_count']}w :: {text}"
        )


if __name__ == "__main__":
    main()
