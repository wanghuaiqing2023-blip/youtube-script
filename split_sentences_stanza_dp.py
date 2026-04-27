import argparse
import json
import math
import re
from functools import lru_cache
from pathlib import Path


FINAL_PUNCT_RE = re.compile(r'[.!?]+["\')\]]*$')
SOFT_PUNCT_RE = re.compile(r'[,;:]+["\')\]]*$')
TRIM_RE = re.compile(r"^[^\w']+|[^\w']+$")
PUNCT_ONLY_RE = re.compile(r"^\W+$")

UNSAFE_END_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "so",
    "if",
    "because",
    "although",
    "though",
    "unless",
    "when",
    "while",
    "where",
    "before",
    "after",
    "that",
    "which",
    "who",
    "whose",
    "whom",
    "to",
    "of",
    "in",
    "on",
    "at",
    "for",
    "from",
    "with",
    "without",
    "by",
    "as",
    "into",
    "onto",
    "about",
    "around",
    "through",
    "between",
    "among",
    "under",
    "over",
    "than",
    "like",
    "is",
    "are",
    "am",
    "was",
    "were",
    "be",
    "been",
    "being",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "can",
    "could",
    "may",
    "might",
    "must",
    "shall",
    "should",
    "will",
    "would",
    "not",
    "n't",
    "lot",
    "just",
    "think",
}

WEAK_START_WORDS = {
    "of",
    "to",
    "than",
    "at",
    "on",
    "with",
    "without",
    "as",
    "instead",
    "compared",
    "closer",
    "appears",
    "would",
    "could",
    "should",
    "will",
    "is",
    "are",
    "was",
    "were",
    "being",
    "learning",
}

DEPENDENT_START_WORDS = {"and", "but", "because", "that", "which", "so"}
SAFE_SECTION_STARTS = {("for", "example"), ("by", "the"), ("in", "american"), ("in", "this")}
IGNORED_DEPRELS = {"punct", "cc", "discourse", "parataxis"}


def norm_word(value):
    return TRIM_RE.sub("", value).lower()


def text_from_words(words):
    return " ".join(word["word"] for word in words).strip()


def has_final_punctuation(word):
    return bool(FINAL_PUNCT_RE.search(word))


def has_soft_punctuation(word):
    return bool(SOFT_PUNCT_RE.search(word))


def starts_lowercase(value):
    stripped = value.lstrip('"\'([{')
    return bool(stripped[:1].islower())


def percentile(values, q, default):
    if not values:
        return default
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def flatten_words(data):
    return [{**word, "index": index} for index, word in enumerate(data["word_segments"])]


def build_segment_end_positions(segments):
    positions = set()
    cursor = 0
    for segment in segments:
        count = len(segment.get("words", []))
        if count:
            cursor += count
            positions.add(cursor)
    return positions


def compute_gaps(words):
    return [max(0.0, words[i + 1]["start"] - words[i]["end"]) for i in range(len(words) - 1)]


def compute_pause_thresholds(gaps):
    positive = [gap for gap in gaps if gap > 0.02]
    return {
        "medium": round(max(0.25, min(0.65, percentile(positive, 0.85, 0.35))), 3),
        "long": round(max(0.5, min(1.1, percentile(positive, 0.95, 0.65))), 3),
        "very_long": round(max(0.75, min(1.6, percentile(positive, 0.985, 0.95))), 3),
    }


def make_unit(sentence_id, unit_words, reason, pre_pad, post_pad):
    start = unit_words[0]["start"]
    end = unit_words[-1]["end"]
    cut_start = max(0.0, start - pre_pad)
    cut_end = end + post_pad
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
        "boundary_reason": reason,
        "words": unit_words,
    }


def start_penalty(words):
    first = norm_word(words[0]["word"])
    tokens = [norm_word(word["word"]) for word in words[:3] if norm_word(word["word"])]
    if tuple(tokens[:2]) in SAFE_SECTION_STARTS:
        return 0.0
    if first in WEAK_START_WORDS and starts_lowercase(words[0]["word"]):
        return 12.0
    if first in DEPENDENT_START_WORDS and starts_lowercase(words[0]["word"]):
        return 4.0
    return 0.0


def end_penalty(words):
    last = norm_word(words[-1]["word"])
    if has_final_punctuation(words[-1]["word"]):
        return 0.0
    if last in UNSAFE_END_WORDS:
        return 16.0
    return 0.0


def endpoint_reward(words, end_position, gaps, segment_end_positions, pauses):
    last = words[end_position - 1]["word"]
    reward = 0.0
    reasons = []
    if has_final_punctuation(last):
        reward += 26.0
        reasons.append("final_punctuation")
    elif has_soft_punctuation(last):
        reward += 9.0
        reasons.append("soft_punctuation")

    if end_position < len(words):
        gap = gaps[end_position - 1]
        if gap >= pauses["very_long"]:
            reward += 18.0
            reasons.append("very_long_pause")
        elif gap >= pauses["long"]:
            reward += 10.0
            reasons.append("long_pause")
        elif gap >= pauses["medium"]:
            reward += 4.0
            reasons.append("medium_pause")

    if end_position in segment_end_positions:
        reward += 3.0
        reasons.append("source_segment_boundary")
    return reward, "+".join(reasons) or "dp_boundary"


def segment_cost(words, start, end, gaps, segment_end_positions, pauses, args):
    unit_words = words[start:end]
    word_count = len(unit_words)
    duration = unit_words[-1]["end"] - unit_words[0]["start"]
    cost = 0.0

    if duration < args.min_duration:
        cost += (args.min_duration - duration) * 4.0
    cost += abs(duration - args.target_duration) * 0.8
    if duration > args.target_duration:
        cost += (duration - args.target_duration) * 1.2
    if duration > args.max_duration:
        cost += 250.0 + (duration - args.max_duration) * 80.0

    if word_count < args.min_words:
        cost += 80.0
    if word_count > args.target_words:
        cost += (word_count - args.target_words) * 1.5
    if word_count > args.max_words:
        cost += 250.0 + (word_count - args.max_words) * 40.0

    cost += start_penalty(unit_words)
    cost += end_penalty(unit_words)
    reward, reason = endpoint_reward(words, end, gaps, segment_end_positions, pauses)
    cost -= reward
    return cost, reason


def build_candidate_positions(words, gaps, segment_end_positions, pauses, args):
    positions = {0, len(words)}
    for index, word in enumerate(words):
        pos = index + 1
        if has_final_punctuation(word["word"]) or has_soft_punctuation(word["word"]):
            positions.add(pos)
        if pos in segment_end_positions:
            positions.add(pos)
        if index < len(gaps) and gaps[index] >= pauses["medium"]:
            positions.add(pos)

    # Add sparse fallback positions so the DP can still split transcripts with weak punctuation.
    for start in range(0, len(words), max(1, args.target_words // 2)):
        for pos in range(start + args.min_words, min(len(words), start + args.max_words) + 1):
            if pos >= len(words):
                positions.add(len(words))
                break
            duration = words[pos - 1]["end"] - words[start]["start"]
            if duration >= args.target_duration:
                positions.add(pos)
                break

    return sorted(positions)


def dp_split(words, gaps, segment_end_positions, pauses, args):
    candidates = build_candidate_positions(words, gaps, segment_end_positions, pauses, args)
    candidate_set = set(candidates)
    n = len(words)
    dp = {0: 0.0}
    back = {}

    for end in candidates[1:]:
        best = None
        best_start = None
        best_reason = None
        for start in candidates:
            if start >= end or start not in dp:
                continue
            word_count = end - start
            if word_count > args.max_words + 20:
                continue
            if word_count < args.min_words and end != n:
                continue
            duration = words[end - 1]["end"] - words[start]["start"]
            if duration > args.max_duration + 10:
                continue
            cost, reason = segment_cost(words, start, end, gaps, segment_end_positions, pauses, args)
            total = dp[start] + cost
            if best is None or total < best:
                best = total
                best_start = start
                best_reason = reason
        if best is not None:
            dp[end] = best
            back[end] = (best_start, best_reason)

    if n not in back:
        # Last-resort fallback: preserve all words even if candidate generation failed.
        return [(0, n, "fallback_all")]

    boundaries = []
    cursor = n
    while cursor > 0:
        start, reason = back[cursor]
        boundaries.append((start, cursor, reason))
        cursor = start
    boundaries.reverse()
    return boundaries


def load_stanza(args):
    if args.no_stanza:
        return None
    try:
        import stanza
    except Exception as exc:
        print(f"Stanza unavailable, skipping NLP repair: {exc}")
        return None
    return stanza.Pipeline(
        "en",
        model_dir=args.model_dir,
        processors="tokenize,pos,lemma,depparse",
        use_gpu=False,
        verbose=False,
        download_method=None,
    )


def stanza_word_count(nlp, text):
    doc = nlp(text)
    return sum(len(sentence.words) for sentence in doc.sentences)


def dependency_crossings(nlp, left_text, right_text):
    left_count = stanza_word_count(nlp, left_text)
    combined = nlp(left_text + " " + right_text)
    crossings = []
    offset = 0
    for sentence in combined.sentences:
        for word in sentence.words:
            global_id = offset + word.id
            if word.head == 0 or word.deprel in IGNORED_DEPRELS:
                continue
            head_global_id = offset + word.head
            word_side = "left" if global_id <= left_count else "right"
            head_side = "left" if head_global_id <= left_count else "right"
            if word_side != head_side and not PUNCT_ONLY_RE.match(word.text):
                crossings.append((word.text, word.upos, word.deprel))
        offset += len(sentence.words)
    return crossings


def repair_crossing_boundaries(units, nlp, args):
    if nlp is None:
        return units

    changed = True
    passes = 0
    while changed and passes < args.repair_passes:
        passes += 1
        changed = False
        repaired = []
        i = 0
        while i < len(units):
            if i + 1 >= len(units):
                repaired.append(units[i])
                i += 1
                continue

            left = units[i]
            right = units[i + 1]
            merged_duration = right["end"] - left["start"]
            merged_words = left["word_count"] + right["word_count"]
            if merged_duration > args.repair_max_duration or merged_words > args.repair_max_words:
                repaired.append(left)
                i += 1
                continue

            crossings = dependency_crossings(nlp, left["text"], right["text"])
            strong_crossings = [
                item
                for item in crossings
                if item[1] not in {"INTJ", "PUNCT"} and item[2] not in {"cc", "discourse"}
            ]
            if strong_crossings:
                merged_words_list = left["words"] + right["words"]
                repaired.append(
                    make_unit(
                        0,
                        merged_words_list,
                        "stanza_dependency_repair:" + left["boundary_reason"] + "|" + right["boundary_reason"],
                        args.pre_pad,
                        args.post_pad,
                    )
                )
                changed = True
                i += 2
            else:
                repaired.append(left)
                i += 1

        for sentence_id, unit in enumerate(repaired, start=1):
            unit["id"] = sentence_id
        units = repaired
    return units


def build_output(data, args):
    words = flatten_words(data)
    gaps = compute_gaps(words)
    pauses = compute_pause_thresholds(gaps)
    segment_end_positions = build_segment_end_positions(data.get("segments", []))
    boundaries = dp_split(words, gaps, segment_end_positions, pauses, args)

    units = [
        make_unit(i, words[start:end], reason, args.pre_pad, args.post_pad)
        for i, (start, end, reason) in enumerate(boundaries, start=1)
    ]

    nlp = load_stanza(args)
    units = repair_crossing_boundaries(units, nlp, args)

    assigned = sum(unit["word_count"] for unit in units)
    return {
        "metadata": {
            "source": args.input,
            "strategy": "dynamic_programming_with_optional_stanza_dependency_repair",
            "uses_llm": False,
            "uses_stanza": nlp is not None,
            "sentence_count": len(units),
            "word_count": len(words),
            "assigned_word_count": assigned,
            "all_words_assigned": assigned == len(words),
            "pause_thresholds_seconds": pauses,
            "limits": {
                "min_duration": args.min_duration,
                "target_duration": args.target_duration,
                "max_duration": args.max_duration,
                "target_words": args.target_words,
                "max_words": args.max_words,
                "repair_max_duration": args.repair_max_duration,
                "repair_max_words": args.repair_max_words,
            },
            "padding": {
                "pre_seconds": args.pre_pad,
                "post_seconds": args.post_pad,
            },
        },
        "sentences": units,
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="transcribe-whisperx_result.json")
    parser.add_argument("--output", default="sentence_units_stanza_dp.json")
    parser.add_argument("--model-dir", default="stanza_resources")
    parser.add_argument("--no-stanza", action="store_true")
    parser.add_argument("--min-words", type=int, default=3)
    parser.add_argument("--target-words", type=int, default=28)
    parser.add_argument("--max-words", type=int, default=58)
    parser.add_argument("--min-duration", type=float, default=1.0)
    parser.add_argument("--target-duration", type=float, default=8.0)
    parser.add_argument("--max-duration", type=float, default=18.0)
    parser.add_argument("--repair-max-words", type=int, default=75)
    parser.add_argument("--repair-max-duration", type=float, default=24.0)
    parser.add_argument("--repair-passes", type=int, default=2)
    parser.add_argument("--pre-pad", type=float, default=0.25)
    parser.add_argument("--post-pad", type=float, default=0.35)
    return parser.parse_args()


def main():
    args = parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = build_output(data, args)
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    metadata = output["metadata"]
    print(f"Wrote {args.output}")
    print(f"sentences: {metadata['sentence_count']}")
    print(f"words assigned: {metadata['assigned_word_count']}/{metadata['word_count']}")
    print(f"all words assigned: {metadata['all_words_assigned']}")
    print(f"uses stanza: {metadata['uses_stanza']}")


if __name__ == "__main__":
    main()
