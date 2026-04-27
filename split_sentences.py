import argparse
import json
import re
from pathlib import Path


FINAL_PUNCT_RE = re.compile(r'[.!?]+["\')\]]*$')
SOFT_PUNCT_RE = re.compile(r'[,;:]+["\')\]]*$')
TRAILING_PUNCT_RE = re.compile(r'^[^\w\']+|[^\w\']+$')

MIN_WORDS = 4
PREFERRED_WORDS = 20
MAX_WORDS = 34
MAX_DURATION = 11.5
PRE_PAD = 0.25
POST_PAD = 0.35

SENTENCE_OPENERS = {
    "i",
    "you",
    "we",
    "they",
    "he",
    "she",
    "it",
    "this",
    "that",
    "these",
    "those",
    "there",
    "then",
    "now",
    "also",
    "but",
    "and",
    "so",
    "if",
    "when",
    "because",
    "for",
    "let's",
    "maybe",
}

BAD_BOUNDARY_ENDINGS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "so",
    "if",
    "because",
    "when",
    "while",
    "that",
    "to",
    "of",
    "in",
    "on",
    "at",
    "for",
    "from",
    "with",
    "by",
    "as",
    "into",
    "about",
    "like",
    "than",
    "you're",
    "gonna",
    "wanna",
}


def norm_word(value):
    return TRAILING_PUNCT_RE.sub("", value).lower()


def starts_with_capital(value):
    stripped = value.lstrip('"\'([{')
    return bool(stripped[:1].isupper())


def build_segment_end_indices(segments):
    end_indices = set()
    cursor = 0
    for segment in segments:
        words = segment.get("words", [])
        if words:
            cursor += len(words)
            end_indices.add(cursor - 1)
    return end_indices


def candidate_score(words, segment_end_indices, sentence_start, i):
    if i >= len(words) - 1:
        return None

    current = words[i]
    nxt = words[i + 1]
    current_norm = norm_word(current["word"])
    word_count = i - sentence_start + 1
    if word_count < MIN_WORDS:
        return None

    gap = max(0.0, nxt["start"] - current["end"])
    duration = current["end"] - words[sentence_start]["start"]
    next_norm = norm_word(nxt["word"])
    score = 0.0
    reasons = []

    if SOFT_PUNCT_RE.search(current["word"]):
        score += 6.0
        reasons.append("soft_punctuation")

    if i in segment_end_indices:
        score += 3.0
        reasons.append("source_segment_boundary")

    if gap >= 0.65:
        score += 5.0
        reasons.append("long_pause")
    elif gap >= 0.4:
        score += 3.0
        reasons.append("pause")
    elif gap >= 0.22:
        score += 1.0
        reasons.append("short_pause")

    if starts_with_capital(nxt["word"]) and next_norm in SENTENCE_OPENERS:
        score += 3.0
        reasons.append("next_capitalized")

    if next_norm in SENTENCE_OPENERS:
        score += 1.5
        reasons.append("sentence_opener")

    if duration >= 4.0 and word_count >= 10:
        score += 0.75
        reasons.append("healthy_length")

    if current_norm in BAD_BOUNDARY_ENDINGS:
        score -= 8.0
        reasons.append("bad_boundary_ending")

    # Favor natural sentence lengths when force-splitting a long spoken run.
    score -= abs(word_count - PREFERRED_WORDS) * 0.08

    if not reasons:
        return None

    return {
        "index": i,
        "score": score,
        "reason": "+".join(reasons),
        "gap_after": round(gap, 3),
        "word_count": word_count,
        "duration": round(duration, 3),
    }


def split_words(words, segment_end_indices):
    sentences = []
    start = 0
    candidates = []

    for i, word in enumerate(words):
        if i < start:
            continue

        word_count = i - start + 1
        duration = word["end"] - words[start]["start"]
        final_punctuation = FINAL_PUNCT_RE.search(word["word"])

        candidate = candidate_score(words, segment_end_indices, start, i)
        if candidate:
            candidates.append(candidate)

        boundary = None
        reason = None

        if final_punctuation:
            boundary = i
            reason = "final_punctuation"
        elif i < len(words) - 1:
            gap = words[i + 1]["start"] - word["end"]
            if gap >= 0.9 and word_count >= 7:
                boundary = i
                reason = "very_long_pause"
            elif word_count >= MAX_WORDS or duration >= MAX_DURATION:
                usable = [
                    c
                    for c in candidates
                    if c["index"] >= start + MIN_WORDS - 1 and c["score"] > -2.0
                ]
                if usable:
                    boundary_candidate = max(usable, key=lambda c: c["score"])
                    boundary = boundary_candidate["index"]
                    reason = "forced_at_" + boundary_candidate["reason"]
                elif norm_word(word["word"]) in BAD_BOUNDARY_ENDINGS:
                    continue
                else:
                    boundary = i
                    reason = "forced_max_length"
        elif i == len(words) - 1:
            boundary = i
            reason = "end_of_transcript"

        if boundary is not None:
            sentences.append(
                {
                    "start_index": start,
                    "end_index": boundary,
                    "boundary_reason": reason,
                }
            )
            start = boundary + 1
            candidates = []

    return sentences


def text_from_words(words):
    return " ".join(word["word"] for word in words).strip()


def make_sentence_unit(sentence_id, unit_words, boundary_reason):
    start = unit_words[0]["start"]
    end = unit_words[-1]["end"]
    cut_start = max(0.0, start - PRE_PAD)
    cut_end = end + POST_PAD
    scores = [word.get("score") for word in unit_words if word.get("score") is not None]

    return {
        "id": sentence_id,
        "start": round(start, 3),
        "end": round(end, 3),
        "cut_start": round(cut_start, 3),
        "cut_end": round(cut_end, 3),
        "duration": round(end - start, 3),
        "cut_duration": round(cut_end - cut_start, 3),
        "text": text_from_words(unit_words),
        "word_count": len(unit_words),
        "avg_score": round(sum(scores) / len(scores), 3) if scores else None,
        "boundary_reason": boundary_reason,
        "words": unit_words,
    }


def merge_sentence_units(sentence_units):
    merged = []
    i = 0

    while i < len(sentence_units):
        current = sentence_units[i]
        current_words = list(current["words"])
        reasons = [current["boundary_reason"]]

        while (
            i + 1 < len(sentence_units)
            and current_words[-1]["word"].rstrip().endswith((",", ";", ":"))
            and len(current_words) <= 12
        ):
            i += 1
            current_words.extend(sentence_units[i]["words"])
            reasons.append(sentence_units[i]["boundary_reason"])

        starts_with_connector = norm_word(current_words[0]["word"]) in {
            "and",
            "but",
            "or",
            "so",
            "because",
            "when",
            "if",
        }
        if (
            merged
            and starts_with_connector
            and len(current_words) <= 7
            and not merged[-1]["boundary_reason"].startswith("final_punctuation")
        ):
            previous = merged.pop()
            current_words = previous["words"] + current_words
            reasons = [previous["boundary_reason"]] + reasons

        merged.append(make_sentence_unit(0, current_words, "merged:" + "|".join(reasons) if len(reasons) > 1 else reasons[0]))
        i += 1

    for sentence_id, unit in enumerate(merged, start=1):
        unit["id"] = sentence_id
    return merged


def build_output(data):
    words = []
    for i, word in enumerate(data["word_segments"]):
        item = dict(word)
        item["index"] = i
        words.append(item)

    segment_end_indices = build_segment_end_indices(data.get("segments", []))
    boundaries = split_words(words, segment_end_indices)

    sentence_units = []
    for sentence_id, boundary in enumerate(boundaries, start=1):
        unit_words = words[boundary["start_index"] : boundary["end_index"] + 1]
        sentence_units.append(make_sentence_unit(sentence_id, unit_words, boundary["boundary_reason"]))

    sentence_units = merge_sentence_units(sentence_units)

    assigned_word_count = sum(unit["word_count"] for unit in sentence_units)
    return {
        "metadata": {
            "source": "transcribe-whisperx_result.json",
            "sentence_count": len(sentence_units),
            "word_count": len(words),
            "assigned_word_count": assigned_word_count,
            "all_words_assigned": assigned_word_count == len(words),
            "padding": {
                "pre_seconds": PRE_PAD,
                "post_seconds": POST_PAD,
                "note": "cut_start/cut_end intentionally add room for audio slicing; words still belong to exactly one sentence.",
            },
            "split_policy": {
                "primary": "sentence-ending punctuation",
                "fallback": "source segment boundaries, pauses, capitalization, sentence openers, and max length/duration for long spoken runs",
                "max_words": MAX_WORDS,
                "max_duration_seconds": MAX_DURATION,
            },
        },
        "sentences": sentence_units,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="transcribe-whisperx_result.json",
        help="WhisperX JSON file with word_segments.",
    )
    parser.add_argument(
        "--output",
        default="sentence_units.json",
        help="Output JSON file with sentence units.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    data = json.loads(input_path.read_text(encoding="utf-8"))
    output = build_output(data)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    metadata = output["metadata"]
    print(f"Wrote {output_path}")
    print(f"sentences: {metadata['sentence_count']}")
    print(f"words assigned: {metadata['assigned_word_count']}/{metadata['word_count']}")
    print(f"all words assigned: {metadata['all_words_assigned']}")


if __name__ == "__main__":
    main()
