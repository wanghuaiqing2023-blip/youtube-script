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
from verify_coarse_nonoverlap import summarize_ranges


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="transcribe-whisperx_result.json")
    parser.add_argument("--model-dir", default="stanza_resources")
    parser.add_argument("--output", default="coarse_blocks_pure_grammar.json")
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

    blocks = []
    for block_id, (start, end, reason) in enumerate(coarse_ranges, start=1):
        block_words = words[start:end]
        blocks.append(
            {
                "id": block_id,
                "start_word_index": start,
                "end_word_index": end - 1,
                "word_count": end - start,
                "start": round(block_words[0]["start"], 3),
                "end": round(block_words[-1]["end"], 3),
                "duration": round(block_words[-1]["end"] - block_words[0]["start"], 3),
                "reason": reason,
                "text": text_from_words(block_words),
                "words": block_words,
            }
        )

    output = {
        "metadata": {
            "source": args.input,
            "strategy": "pure_grammar_coarse_blocks",
            "merge_list_groups": args.merge_list_groups,
            "summary": summarize_ranges(words, coarse_ranges),
        },
        "blocks": blocks,
    }
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = output["metadata"]["summary"]
    print(f"Wrote {args.output}")
    print(f"blocks: {len(blocks)}")
    print(f"words covered: {summary['covered_word_count']}/{summary['word_count']}")
    print(f"has overlap: {summary['has_overlap']} ({summary['overlap_count']})")
    print(f"has gap: {summary['has_gap']} ({summary['gap_count']})")
    print(f"max words: {summary['max_words']}")
    print(f"max duration: {summary['max_duration']:.3f}")


if __name__ == "__main__":
    main()
