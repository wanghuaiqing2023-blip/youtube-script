import argparse
import json
import math
import re
from pathlib import Path


FINAL_PUNCT_RE = re.compile(r'[.!?]+["\')\]]*$')
SOFT_PUNCT_RE = re.compile(r'[,;:]+["\')\]]*$')
TRIM_RE = re.compile(r"^[^\w']+|[^\w']+$")

DEFAULT_PRE_PAD = 0.25
DEFAULT_POST_PAD = 0.35
DEFAULT_MIN_WORDS = 3
DEFAULT_PREFERRED_WORDS = 22
DEFAULT_MAX_WORDS = 42
DEFAULT_MAX_DURATION = 14.0

# This is a language-level safety list, not a video-topic vocabulary.
# It only prevents cuts after words that almost never complete an English unit.
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

BACKWARD_FRAGMENT_STARTS = {
    "at",
    "to",
    "of",
    "in",
    "on",
    "for",
    "from",
    "with",
    "without",
    "by",
    "as",
    "into",
    "onto",
    "about",
    "through",
    "between",
    "among",
    "under",
    "over",
    "than",
    "like",
    "instead",
    "compared",
    "closer",
    "appears",
    "would",
    "could",
    "should",
    "will",
    "can",
    "is",
    "are",
    "was",
    "were",
    "being",
    "learning",
}

FORWARD_FRAGMENT_ENDS = UNSAFE_END_WORDS | {
    "which",
    "who",
    "whose",
    "whom",
    "where",
    "why",
    "how",
    "sounds",
    "sound",
}

FINITE_VERB_HINTS = {
    "am",
    "is",
    "are",
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
    "say",
    "says",
    "said",
    "go",
    "goes",
    "went",
    "make",
    "makes",
    "made",
    "take",
    "takes",
    "took",
    "think",
    "thinks",
    "thought",
    "know",
    "knows",
    "knew",
    "mean",
    "means",
    "meant",
    "sound",
    "sounds",
    "sounded",
    "look",
    "looks",
    "looked",
    "want",
    "wants",
    "wanted",
    "need",
    "needs",
    "needed",
    "use",
    "uses",
    "used",
}

QUESTION_WORDS = {"what", "why", "how", "where", "when", "who", "which"}
AUXILIARY_WORDS = {
    "am",
    "is",
    "are",
    "was",
    "were",
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
}
PRONOUNS = {
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "me",
    "him",
    "her",
    "us",
    "them",
}

CLAUSE_STARTERS = {
    "again",
    "also",
    "and",
    "but",
    "so",
    "because",
    "when",
    "if",
    "while",
    "then",
    "now",
    "with",
    "in",
    "this",
    "that",
    "let's",
}

ABBREVIATIONS = {
    "mr.",
    "mrs.",
    "ms.",
    "dr.",
    "prof.",
    "sr.",
    "jr.",
    "st.",
    "vs.",
    "etc.",
    "e.g.",
    "i.e.",
    "u.s.",
    "u.k.",
}


def clamp(value, low, high):
    return max(low, min(high, value))


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def norm_word(value):
    return TRIM_RE.sub("", value).lower()


def has_final_punctuation(word):
    token = word.strip().lower()
    return bool(FINAL_PUNCT_RE.search(word)) and token not in ABBREVIATIONS


def has_soft_punctuation(word):
    return bool(SOFT_PUNCT_RE.search(word))


def starts_with_capital(value):
    stripped = value.lstrip('"\'([{')
    return bool(stripped[:1].isupper())


def starts_lowercase(value):
    stripped = value.lstrip('"\'([{')
    return bool(stripped[:1].islower())


def has_finite_verb_hint(words):
    tokens = [norm_word(word["word"]) for word in words]
    for token in tokens:
        if token in FINITE_VERB_HINTS:
            return True
        if len(token) > 4 and (token.endswith("ed") or token.endswith("n't")):
            return True
    return False


def ends_with_incomplete_question_prefix(words):
    tokens = [norm_word(word["word"]) for word in words if norm_word(word["word"])]
    if len(tokens) >= 3 and tokens[-3] in QUESTION_WORDS and tokens[-2] in AUXILIARY_WORDS and tokens[-1] in PRONOUNS:
        return True
    if len(tokens) >= 2 and tokens[-2] in AUXILIARY_WORDS and tokens[-1] in PRONOUNS:
        return True
    return False


def starts_with_clause_marker(words):
    tokens = [norm_word(word["word"]) for word in words[:3] if norm_word(word["word"])]
    if not tokens:
        return False
    if len(tokens) >= 2 and tokens[0] == "for" and tokens[1] == "example":
        return True
    if len(tokens) >= 2 and tokens[0] == "by" and tokens[1] == "the":
        return True
    if tokens[0] in CLAUSE_STARTERS:
        return True
    return False


def flatten_words(data):
    words = []
    for index, word in enumerate(data["word_segments"]):
        item = dict(word)
        item["index"] = index
        words.append(item)
    return words


def segment_end_indices(segments):
    indices = set()
    cursor = 0
    for segment in segments:
        count = len(segment.get("words", []))
        if count:
            cursor += count
            indices.add(cursor - 1)
    return indices


def compute_pause_thresholds(words):
    gaps = [
        max(0.0, words[i + 1]["start"] - words[i]["end"])
        for i in range(len(words) - 1)
    ]
    positive = [gap for gap in gaps if gap > 0.02]
    medium = percentile(positive, 0.85)
    long = percentile(positive, 0.95)
    very_long = percentile(positive, 0.985)

    return {
        "medium": round(clamp(medium or 0.35, 0.25, 0.65), 3),
        "long": round(clamp(long or 0.65, 0.5, 1.1), 3),
        "very_long": round(clamp(very_long or 0.95, 0.75, 1.6), 3),
    }


def boundary_score(words, segment_ends, start, i, pause_thresholds, preferred_words):
    if i >= len(words) - 1:
        return None

    current = words[i]
    nxt = words[i + 1]
    current_norm = norm_word(current["word"])
    word_count = i - start + 1
    duration = current["end"] - words[start]["start"]
    gap = max(0.0, nxt["start"] - current["end"])

    score = 0.0
    reasons = []

    if has_soft_punctuation(current["word"]):
        score += 24.0
        reasons.append("soft_punctuation")

    if gap >= pause_thresholds["very_long"]:
        score += 30.0
        reasons.append("very_long_pause")
    elif gap >= pause_thresholds["long"]:
        score += 18.0
        reasons.append("long_pause")
    elif gap >= pause_thresholds["medium"]:
        score += 9.0
        reasons.append("medium_pause")

    if i in segment_ends:
        score += 6.0
        reasons.append("source_segment_boundary")

    if starts_with_capital(nxt["word"]):
        score += 4.0
        reasons.append("next_capitalized")

    if word_count >= 8 and duration >= 3.0:
        score += 3.0
        reasons.append("usable_length")

    if current_norm in UNSAFE_END_WORDS:
        score -= 35.0
        reasons.append("unsafe_ending")

    score -= abs(word_count - preferred_words) * 0.15

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


def split_words(
    words,
    segment_ends,
    pause_thresholds,
    min_words,
    preferred_words,
    max_words,
    max_duration,
):
    boundaries = []
    candidates = []
    start = 0

    for i, word in enumerate(words):
        if i < start:
            continue

        word_count = i - start + 1
        duration = word["end"] - words[start]["start"]
        candidate = boundary_score(
            words, segment_ends, start, i, pause_thresholds, preferred_words
        )
        if candidate and word_count >= min_words:
            candidates.append(candidate)

        boundary = None
        reason = None

        if has_final_punctuation(word["word"]):
            boundary = i
            reason = "final_punctuation"
        elif i == len(words) - 1:
            boundary = i
            reason = "end_of_transcript"
        elif word_count >= min_words:
            gap = max(0.0, words[i + 1]["start"] - word["end"])
            if gap >= pause_thresholds["very_long"] and word_count >= 6:
                boundary = i
                reason = "very_long_pause"
            elif word_count >= max_words or duration >= max_duration:
                usable = [
                    item
                    for item in candidates
                    if item["index"] >= start + min_words - 1 and item["score"] > -10
                ]
                if usable:
                    best = max(usable, key=lambda item: item["score"])
                    boundary = best["index"]
                    reason = "forced_at_" + best["reason"]
                elif norm_word(word["word"]) not in UNSAFE_END_WORDS:
                    boundary = i
                    reason = "forced_max_length"

        if boundary is not None:
            boundaries.append(
                {
                    "start_index": start,
                    "end_index": boundary,
                    "boundary_reason": reason,
                }
            )
            start = boundary + 1
            candidates = []

    return boundaries


def text_from_words(words):
    return " ".join(word["word"] for word in words).strip()


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


def merge_fragments(sentence_units, pre_pad, post_pad, max_merge_words, max_merge_duration):
    merged = []
    i = 0
    while i < len(sentence_units):
        words = list(sentence_units[i]["words"])
        reasons = [sentence_units[i]["boundary_reason"]]

        while i + 1 < len(sentence_units):
            text = text_from_words(words)
            duration_if_merged = sentence_units[i + 1]["end"] - words[0]["start"]
            words_if_merged = len(words) + sentence_units[i + 1]["word_count"]
            ends_with_soft = words[-1]["word"].rstrip().endswith((",", ";", ":"))
            incomplete_short = (
                len(words) <= 5
                and not has_final_punctuation(words[-1]["word"])
                and not sentence_units[i]["boundary_reason"].startswith("final_punctuation")
            )

            if not ends_with_soft and not incomplete_short:
                break
            if words_if_merged > max_merge_words or duration_if_merged > max_merge_duration:
                break

            i += 1
            words.extend(sentence_units[i]["words"])
            reasons.append(sentence_units[i]["boundary_reason"])

        reason = reasons[0] if len(reasons) == 1 else "merged:" + "|".join(reasons)
        merged.append(make_unit(0, words, reason, pre_pad, post_pad))
        i += 1

    for sentence_id, unit in enumerate(merged, start=1):
        unit["id"] = sentence_id
    return merged


def merge_close_units(sentence_units, pre_pad, post_pad, close_gap, max_words, max_duration):
    if not sentence_units:
        return []

    merged = []
    current_words = list(sentence_units[0]["words"])
    reasons = [sentence_units[0]["boundary_reason"]]

    for unit in sentence_units[1:]:
        gap = unit["start"] - current_words[-1]["end"]
        merged_word_count = len(current_words) + unit["word_count"]
        merged_duration = unit["end"] - current_words[0]["start"]

        should_merge = (
            gap <= close_gap
            and merged_word_count <= max_words
            and merged_duration <= max_duration
        )

        if should_merge:
            current_words.extend(unit["words"])
            reasons.append(unit["boundary_reason"])
            continue

        reason = reasons[0] if len(reasons) == 1 else "close_merged:" + "|".join(reasons)
        merged.append(make_unit(0, current_words, reason, pre_pad, post_pad))
        current_words = list(unit["words"])
        reasons = [unit["boundary_reason"]]

    reason = reasons[0] if len(reasons) == 1 else "close_merged:" + "|".join(reasons)
    merged.append(make_unit(0, current_words, reason, pre_pad, post_pad))

    for sentence_id, unit in enumerate(merged, start=1):
        unit["id"] = sentence_id
    return merged


def is_backward_fragment(unit):
    words = unit["words"]
    if not words:
        return False
    first = norm_word(words[0]["word"])
    if first in {
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
    } and starts_lowercase(words[0]["word"]):
        return True
    if first in BACKWARD_FRAGMENT_STARTS and starts_lowercase(words[0]["word"]) and (
        unit["word_count"] <= 12 or not has_finite_verb_hint(words)
    ):
        return True
    if starts_lowercase(words[0]["word"]) and unit["word_count"] <= 12:
        return True
    return False


def is_forward_fragment(unit):
    words = unit["words"]
    if not words:
        return False
    last = norm_word(words[-1]["word"])
    text = unit["text"].strip()
    if ends_with_incomplete_question_prefix(words):
        return True
    if has_final_punctuation(words[-1]["word"]):
        return False
    if last in FORWARD_FRAGMENT_ENDS:
        return True
    if text.endswith((",", ";", ":")):
        return True
    if unit["word_count"] <= 8 and not has_finite_verb_hint(words):
        return True
    return False


def is_safe_split(left_words, right_words, pre_pad, post_pad):
    if len(left_words) < DEFAULT_MIN_WORDS or len(right_words) < DEFAULT_MIN_WORDS:
        return False
    if norm_word(left_words[-1]["word"]) in UNSAFE_END_WORDS:
        return False

    right_unit = make_unit(0, right_words, "probe", pre_pad, post_pad)
    if is_forward_fragment(make_unit(0, left_words, "probe", pre_pad, post_pad)):
        return False
    if is_backward_fragment(right_unit) and not starts_with_clause_marker(right_words):
        return False
    return True


def split_long_unit_once(unit, pre_pad, post_pad, target_duration, target_words):
    words = unit["words"]
    if unit["duration"] <= target_duration and unit["word_count"] <= target_words:
        return [unit]

    target_end = words[0]["start"] + min(target_duration, unit["duration"] / 2)
    candidates = []

    for i in range(DEFAULT_MIN_WORDS - 1, len(words) - DEFAULT_MIN_WORDS):
        left_words = words[: i + 1]
        right_words = words[i + 1 :]
        if not is_safe_split(left_words, right_words, pre_pad, post_pad):
            continue

        gap = max(0.0, right_words[0]["start"] - left_words[-1]["end"])
        score = 0.0
        reason = None

        if has_final_punctuation(left_words[-1]["word"]):
            score += 100.0
            reason = "internal_final_punctuation"
        elif has_soft_punctuation(left_words[-1]["word"]):
            score += 45.0
            reason = "internal_soft_punctuation"
        elif starts_with_clause_marker(right_words):
            score += 35.0
            reason = "internal_clause_marker"

        if reason is None:
            continue

        score += min(gap, 1.0) * 20.0
        score -= abs(left_words[-1]["end"] - target_end) * 1.6
        score -= abs(len(left_words) - len(right_words)) * 0.05
        candidates.append((score, i, reason))

    if not candidates:
        return [unit]

    _, split_index, reason = max(candidates, key=lambda item: item[0])
    left = make_unit(
        0,
        words[: split_index + 1],
        "long_split:" + reason + "|" + unit["boundary_reason"],
        pre_pad,
        post_pad,
    )
    right = make_unit(
        0,
        words[split_index + 1 :],
        "long_split_remainder:" + reason + "|" + unit["boundary_reason"],
        pre_pad,
        post_pad,
    )
    return [left, right]


def split_long_units(sentence_units, pre_pad, post_pad, target_duration, target_words, max_passes):
    units = list(sentence_units)
    for _ in range(max_passes):
        changed = False
        next_units = []
        for unit in units:
            pieces = split_long_unit_once(unit, pre_pad, post_pad, target_duration, target_words)
            if len(pieces) > 1:
                changed = True
            next_units.extend(pieces)
        units = next_units
        if not changed:
            break

    for sentence_id, unit in enumerate(units, start=1):
        unit["id"] = sentence_id
    return units


def merge_grammar_fragments(sentence_units, pre_pad, post_pad, max_words, max_duration):
    changed = True
    units = list(sentence_units)

    while changed:
        changed = False
        merged = []
        i = 0

        while i < len(units):
            current = units[i]

            if (
                merged
                and is_backward_fragment(current)
                and merged[-1]["word_count"] + current["word_count"] <= max_words
                and current["end"] - merged[-1]["start"] <= max_duration
            ):
                previous = merged.pop()
                words = previous["words"] + current["words"]
                reason = "grammar_merged:" + previous["boundary_reason"] + "|" + current["boundary_reason"]
                merged.append(make_unit(0, words, reason, pre_pad, post_pad))
                changed = True
                i += 1
                continue

            if (
                i + 1 < len(units)
                and is_forward_fragment(current)
                and current["word_count"] + units[i + 1]["word_count"] <= max_words
                and units[i + 1]["end"] - current["start"] <= max_duration
            ):
                nxt = units[i + 1]
                words = current["words"] + nxt["words"]
                reason = "grammar_merged:" + current["boundary_reason"] + "|" + nxt["boundary_reason"]
                merged.append(make_unit(0, words, reason, pre_pad, post_pad))
                changed = True
                i += 2
                continue

            merged.append(current)
            i += 1

        for sentence_id, unit in enumerate(merged, start=1):
            unit["id"] = sentence_id
        units = merged

    return units


def rebalance_tail_fragments(sentence_units, pre_pad, post_pad, max_words, max_duration, min_head_words):
    units = list(sentence_units)
    changed = True

    while changed:
        changed = False
        rebalanced = []
        i = 0

        while i < len(units):
            current = units[i]

            if i + 1 >= len(units) or not is_forward_fragment(current):
                rebalanced.append(current)
                i += 1
                continue

            words = current["words"]
            split_at = None
            for j in range(len(words) - 2, min_head_words - 1, -1):
                if has_final_punctuation(words[j]["word"]):
                    split_at = j
                    break

            if split_at is None:
                rebalanced.append(current)
                i += 1
                continue

            head_words = words[: split_at + 1]
            tail_words = words[split_at + 1 :]
            nxt = units[i + 1]
            merged_tail_words = tail_words + nxt["words"]
            merged_tail_duration = merged_tail_words[-1]["end"] - merged_tail_words[0]["start"]

            if (
                len(tail_words) >= 2
                and is_forward_fragment(make_unit(0, tail_words, current["boundary_reason"], pre_pad, post_pad))
                and len(merged_tail_words) <= max_words
                and merged_tail_duration <= max_duration
            ):
                rebalanced.append(
                    make_unit(
                        0,
                        head_words,
                        "tail_rebalanced_head:" + current["boundary_reason"],
                        pre_pad,
                        post_pad,
                    )
                )
                rebalanced.append(
                    make_unit(
                        0,
                        merged_tail_words,
                        "tail_rebalanced_fragment:" + current["boundary_reason"] + "|" + nxt["boundary_reason"],
                        pre_pad,
                        post_pad,
                    )
                )
                changed = True
                i += 2
                continue

            rebalanced.append(current)
            i += 1

        for sentence_id, unit in enumerate(rebalanced, start=1):
            unit["id"] = sentence_id
        units = rebalanced

    return units


def rebalance_head_fragments(sentence_units, pre_pad, post_pad, max_words, max_duration, min_head_words):
    units = list(sentence_units)
    changed = True

    while changed:
        changed = False
        rebalanced = []
        i = 0

        while i < len(units):
            if i + 1 >= len(units) or not is_backward_fragment(units[i + 1]):
                rebalanced.append(units[i])
                i += 1
                continue

            previous = units[i]
            current = units[i + 1]
            combined_words = previous["words"] + current["words"]
            combined_duration = combined_words[-1]["end"] - combined_words[0]["start"]

            if len(combined_words) <= max_words and combined_duration <= max_duration:
                rebalanced.append(
                    make_unit(
                        0,
                        combined_words,
                        "head_rebalanced_whole:" + previous["boundary_reason"] + "|" + current["boundary_reason"],
                        pre_pad,
                        post_pad,
                    )
                )
                changed = True
                i += 2
                continue

            split_at = None
            for j in range(len(previous["words"]) - 2, min_head_words - 1, -1):
                if has_final_punctuation(previous["words"][j]["word"]):
                    split_at = j
                    break

            if split_at is None:
                rebalanced.append(previous)
                i += 1
                continue

            head_words = previous["words"][: split_at + 1]
            tail_words = previous["words"][split_at + 1 :]
            merged_tail_words = tail_words + current["words"]
            merged_tail_duration = merged_tail_words[-1]["end"] - merged_tail_words[0]["start"]

            if (
                len(head_words) >= min_head_words
                and len(tail_words) >= 2
                and len(merged_tail_words) <= max_words
                and merged_tail_duration <= max_duration
            ):
                rebalanced.append(
                    make_unit(
                        0,
                        head_words,
                        "head_rebalanced_head:" + previous["boundary_reason"],
                        pre_pad,
                        post_pad,
                    )
                )
                rebalanced.append(
                    make_unit(
                        0,
                        merged_tail_words,
                        "head_rebalanced_fragment:" + previous["boundary_reason"] + "|" + current["boundary_reason"],
                        pre_pad,
                        post_pad,
                    )
                )
                changed = True
                i += 2
                continue

            rebalanced.append(previous)
            i += 1

        if i < len(units):
            rebalanced.extend(units[i:])

        for sentence_id, unit in enumerate(rebalanced, start=1):
            unit["id"] = sentence_id
        units = rebalanced

    return units


def build_output(data, args):
    words = flatten_words(data)
    pauses = compute_pause_thresholds(words)
    segment_ends = segment_end_indices(data.get("segments", []))
    boundaries = split_words(
        words=words,
        segment_ends=segment_ends,
        pause_thresholds=pauses,
        min_words=args.min_words,
        preferred_words=args.preferred_words,
        max_words=args.max_words,
        max_duration=args.max_duration,
    )

    sentence_units = []
    for sentence_id, boundary in enumerate(boundaries, start=1):
        unit_words = words[boundary["start_index"] : boundary["end_index"] + 1]
        sentence_units.append(
            make_unit(
                sentence_id,
                unit_words,
                boundary["boundary_reason"],
                args.pre_pad,
                args.post_pad,
            )
        )

    sentence_units = merge_fragments(
        sentence_units,
        args.pre_pad,
        args.post_pad,
        args.max_merge_words,
        args.max_merge_duration,
    )

    if not args.no_grammar_merge:
        sentence_units = merge_grammar_fragments(
            sentence_units,
            args.pre_pad,
            args.post_pad,
            args.grammar_merge_max_words,
            args.grammar_merge_max_duration,
        )

    close_gap = args.close_gap
    if close_gap is None:
        close_gap = pauses["medium"]
    if not args.no_close_merge:
        sentence_units = merge_close_units(
            sentence_units,
            args.pre_pad,
            args.post_pad,
            close_gap,
            args.close_merge_max_words,
            args.close_merge_max_duration,
        )

    if not args.no_grammar_merge:
        sentence_units = rebalance_tail_fragments(
            sentence_units,
            args.pre_pad,
            args.post_pad,
            args.grammar_merge_max_words,
            args.grammar_merge_max_duration,
            args.min_words,
        )
        sentence_units = rebalance_head_fragments(
            sentence_units,
            args.pre_pad,
            args.post_pad,
            args.grammar_merge_max_words,
            args.grammar_merge_max_duration,
            args.min_words,
        )

    if not args.no_long_split:
        sentence_units = split_long_units(
            sentence_units,
            args.pre_pad,
            args.post_pad,
            args.long_split_target_duration,
            args.long_split_target_words,
            args.long_split_passes,
        )

    assigned = sum(unit["word_count"] for unit in sentence_units)

    return {
        "metadata": {
            "source": args.input,
            "sentence_count": len(sentence_units),
            "word_count": len(words),
            "assigned_word_count": assigned,
            "all_words_assigned": assigned == len(words),
            "pause_thresholds_seconds": pauses,
            "padding": {
                "pre_seconds": args.pre_pad,
                "post_seconds": args.post_pad,
                "note": "Use cut_start/cut_end for audio slicing. Words still belong to exactly one sentence.",
            },
            "split_policy": {
                "primary": "sentence-ending punctuation",
                "fallback": "adaptive pauses, soft punctuation, source segment boundaries, capitalization, max length, and max duration",
                "close_merge": not args.no_close_merge,
                "close_gap_seconds": close_gap,
                "close_merge_max_words": args.close_merge_max_words,
                "close_merge_max_duration_seconds": args.close_merge_max_duration,
                "grammar_fragment_merge": not args.no_grammar_merge,
                "grammar_merge_max_words": args.grammar_merge_max_words,
                "grammar_merge_max_duration_seconds": args.grammar_merge_max_duration,
                "long_split": not args.no_long_split,
                "long_split_target_words": args.long_split_target_words,
                "long_split_target_duration_seconds": args.long_split_target_duration,
                "min_words": args.min_words,
                "preferred_words": args.preferred_words,
                "max_words": args.max_words,
                "max_duration_seconds": args.max_duration,
                "uses_llm": False,
            },
        },
        "sentences": sentence_units,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Split WhisperX word timestamps into sentence-like audio units without using an LLM."
    )
    parser.add_argument("--input", default="transcribe-whisperx_result.json")
    parser.add_argument("--output", default="sentence_units_general.json")
    parser.add_argument("--min-words", type=int, default=DEFAULT_MIN_WORDS)
    parser.add_argument("--preferred-words", type=int, default=DEFAULT_PREFERRED_WORDS)
    parser.add_argument("--max-words", type=int, default=DEFAULT_MAX_WORDS)
    parser.add_argument("--max-duration", type=float, default=DEFAULT_MAX_DURATION)
    parser.add_argument("--pre-pad", type=float, default=DEFAULT_PRE_PAD)
    parser.add_argument("--post-pad", type=float, default=DEFAULT_POST_PAD)
    parser.add_argument("--max-merge-words", type=int, default=55)
    parser.add_argument("--max-merge-duration", type=float, default=18.0)
    parser.add_argument(
        "--close-gap",
        type=float,
        default=None,
        help="Merge adjacent units when the gap is at or below this value. Defaults to the video's adaptive medium pause threshold.",
    )
    parser.add_argument("--close-merge-max-words", type=int, default=55)
    parser.add_argument("--close-merge-max-duration", type=float, default=18.0)
    parser.add_argument(
        "--no-close-merge",
        action="store_true",
        help="Keep stricter sentence-level output without merging close adjacent units.",
    )
    parser.add_argument("--grammar-merge-max-words", type=int, default=140)
    parser.add_argument("--grammar-merge-max-duration", type=float, default=50.0)
    parser.add_argument(
        "--no-grammar-merge",
        action="store_true",
        help="Disable the rule-based pass that merges likely grammatical fragments.",
    )
    parser.add_argument("--long-split-target-words", type=int, default=55)
    parser.add_argument("--long-split-target-duration", type=float, default=18.0)
    parser.add_argument("--long-split-passes", type=int, default=4)
    parser.add_argument(
        "--no-long-split",
        action="store_true",
        help="Disable safe clause-level splitting for long merged units.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = build_output(data, args)
    Path(args.output).write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    metadata = output["metadata"]
    print(f"Wrote {args.output}")
    print(f"sentences: {metadata['sentence_count']}")
    print(f"words assigned: {metadata['assigned_word_count']}/{metadata['word_count']}")
    print(f"all words assigned: {metadata['all_words_assigned']}")
    print(f"adaptive pause thresholds: {metadata['pause_thresholds_seconds']}")


if __name__ == "__main__":
    main()
