import argparse
import bisect
import json
import math
import re
from pathlib import Path

import stanza

from split_sentences_stanza_dp import (
    DEPENDENT_START_WORDS,
    UNSAFE_END_WORDS,
    WEAK_START_WORDS,
    build_segment_end_positions,
    compute_gaps,
    compute_pause_thresholds,
    flatten_words,
    has_final_punctuation,
    has_soft_punctuation,
    make_unit,
    norm_word,
    starts_lowercase,
)


FINAL_PUNCT_RE = re.compile(r'[.!?]+["\')\]]*$')
QUOTE_INTRODUCERS = {
    "say",
    "says",
    "said",
    "tell",
    "tells",
    "told",
    "ask",
    "asks",
    "asked",
    "mean",
    "means",
    "called",
    "like",
}
LIST_LEAD_RE = re.compile(
    r"\b("
    r"examples?|"
    r"for example|"
    r"let me give you|"
    r"take a look at|"
    r"list of|"
    r"try it|"
    r"listen|"
    r"what about"
    r")\b",
    re.IGNORECASE,
)
SECTION_START_RE = re.compile(
    r"^(now|today|next|the next|another thing|and the last|but one thing|let's look|let me know)\b",
    re.IGNORECASE,
)
CRITICAL_DEPRELS = {
    "acl",
    "advmod",
    "advcl",
    "amod",
    "aux",
    "case",
    "cc:preconj",
    "ccomp",
    "compound",
    "cop",
    "det",
    "fixed",
    "flat",
    "iobj",
    "mark",
    "nmod",
    "nmod:poss",
    "nsubj",
    "nummod",
    "obj",
    "obl",
    "xcomp",
}
TIGHT_DEPRELS = {"aux", "case", "cop", "det", "fixed", "flat", "mark"}
STRONG_CROSSING_DEPRELS = {
    "advmod",
    "aux",
    "case",
    "ccomp",
    "cop",
    "det",
    "fixed",
    "flat",
    "iobj",
    "mark",
    "nmod:poss",
    "nsubj",
    "obj",
    "xcomp",
}

# Closed-class English function words used only as generic fine-splitting
# boundary penalties. These are not topic/video vocabulary.
COORDINATING_CONJUNCTIONS = {
    "and",
    "but",
    "or",
    "nor",
    "for",
    "so",
    "yet",
}

SUBORDINATORS = {
    "after",
    "although",
    "as",
    "because",
    "before",
    "if",
    "lest",
    "once",
    "provided",
    "providing",
    "since",
    "than",
    "that",
    "though",
    "till",
    "unless",
    "until",
    "when",
    "whenever",
    "where",
    "whereas",
    "wherever",
    "whether",
    "while",
}

RELATIVE_WH_WORDS = {
    "what",
    "whatever",
    "when",
    "whenever",
    "where",
    "wherever",
    "which",
    "whichever",
    "who",
    "whoever",
    "whom",
    "whomever",
    "whose",
    "why",
    "how",
}

PREPOSITIONS = {
    "aboard",
    "about",
    "above",
    "across",
    "after",
    "against",
    "along",
    "alongside",
    "amid",
    "amidst",
    "among",
    "amongst",
    "around",
    "as",
    "at",
    "atop",
    "before",
    "behind",
    "below",
    "beneath",
    "beside",
    "besides",
    "between",
    "beyond",
    "but",
    "by",
    "concerning",
    "considering",
    "despite",
    "down",
    "during",
    "except",
    "excepting",
    "excluding",
    "following",
    "for",
    "from",
    "in",
    "including",
    "inside",
    "into",
    "like",
    "minus",
    "near",
    "nearer",
    "nearest",
    "notwithstanding",
    "of",
    "off",
    "on",
    "onto",
    "opposite",
    "out",
    "outside",
    "over",
    "past",
    "per",
    "plus",
    "regarding",
    "round",
    "sans",
    "save",
    "since",
    "through",
    "throughout",
    "till",
    "to",
    "toward",
    "towards",
    "under",
    "underneath",
    "unlike",
    "until",
    "unto",
    "up",
    "upon",
    "versus",
    "via",
    "with",
    "within",
    "without",
    "worth",
}

PARTICLES = {
    "aboard",
    "about",
    "across",
    "ahead",
    "along",
    "apart",
    "around",
    "aside",
    "away",
    "back",
    "by",
    "down",
    "forth",
    "forward",
    "in",
    "off",
    "on",
    "out",
    "over",
    "through",
    "together",
    "up",
}

ARTICLES = {"a", "an", "the"}

DETERMINERS = {
    "all",
    "another",
    "any",
    "both",
    "each",
    "either",
    "enough",
    "every",
    "few",
    "fewer",
    "less",
    "little",
    "many",
    "more",
    "most",
    "much",
    "neither",
    "no",
    "other",
    "several",
    "some",
    "such",
    "that",
    "these",
    "this",
    "those",
    "what",
    "whatever",
    "which",
    "whichever",
    "whose",
}

POSSESSIVE_DETERMINERS = {
    "her",
    "his",
    "its",
    "my",
    "our",
    "their",
    "your",
}

PERSONAL_PRONOUNS = {
    "he",
    "her",
    "hers",
    "herself",
    "him",
    "himself",
    "i",
    "it",
    "itself",
    "me",
    "myself",
    "ours",
    "ourselves",
    "she",
    "them",
    "themselves",
    "they",
    "us",
    "we",
    "you",
    "yourself",
    "yourselves",
}

BOUNDARY_WEAK_ADVERBS = {
    "also",
    "already",
    "even",
    "highly",
    "just",
    "maybe",
    "more",
    "only",
    "quite",
    "rather",
    "really",
    "so",
    "still",
    "then",
    "too",
    "very",
}

AUXILIARIES = {
    "am",
    "are",
    "be",
    "been",
    "being",
    "did",
    "do",
    "does",
    "had",
    "has",
    "have",
    "having",
    "is",
    "was",
    "were",
}

MODALS = {
    "can",
    "could",
    "dare",
    "may",
    "might",
    "must",
    "need",
    "ought",
    "shall",
    "should",
    "used",
    "will",
    "would",
}

NEGATORS = {"not", "n't"}

CONTRACTED_AUXILIARIES = {
    "ain't",
    "aren't",
    "can't",
    "cannot",
    "couldn't",
    "didn't",
    "doesn't",
    "don't",
    "hadn't",
    "hasn't",
    "haven't",
    "isn't",
    "mightn't",
    "mustn't",
    "needn't",
    "shan't",
    "shouldn't",
    "wasn't",
    "weren't",
    "won't",
    "wouldn't",
}

CLOSED_CLASS_BAD_START_WORDS = (
    COORDINATING_CONJUNCTIONS
    | SUBORDINATORS
    | RELATIVE_WH_WORDS
    | PREPOSITIONS
    | PARTICLES
    | AUXILIARIES
    | MODALS
    | NEGATORS
    | CONTRACTED_AUXILIARIES
)

CLOSED_CLASS_STRONG_BAD_START_WORDS = (
    SUBORDINATORS
    | RELATIVE_WH_WORDS
    | PREPOSITIONS
    | AUXILIARIES
    | MODALS
    | NEGATORS
    | CONTRACTED_AUXILIARIES
)

CLOSED_CLASS_BAD_END_WORDS = (
    COORDINATING_CONJUNCTIONS
    | SUBORDINATORS
    | RELATIVE_WH_WORDS
    | PREPOSITIONS
    | PARTICLES
    | ARTICLES
    | DETERMINERS
    | POSSESSIVE_DETERMINERS
    | AUXILIARIES
    | MODALS
    | NEGATORS
    | CONTRACTED_AUXILIARIES
    | BOUNDARY_WEAK_ADVERBS
)

CLOSED_CLASS_STRONG_BAD_END_WORDS = (
    PREPOSITIONS
    | PARTICLES
    | ARTICLES
    | POSSESSIVE_DETERMINERS
    | AUXILIARIES
    | MODALS
    | NEGATORS
    | CONTRACTED_AUXILIARIES
)

DISFLUENCY_END_WORDS = {"uh", "um", "erm", "hmm"}
SUBJECT_PRONOUNS = {"i", "you", "he", "she", "we", "they", "it"}

HARD_INTERNAL_BAD_END_WORDS = (
    COORDINATING_CONJUNCTIONS
    | SUBORDINATORS
    | RELATIVE_WH_WORDS
    | PREPOSITIONS
    | PARTICLES
    | ARTICLES
    | POSSESSIVE_DETERMINERS
    | AUXILIARIES
    | MODALS
    | NEGATORS
    | CONTRACTED_AUXILIARIES
    | BOUNDARY_WEAK_ADVERBS
    | DISFLUENCY_END_WORDS
    | {"please"}
)

HARD_INTERNAL_BAD_START_WORDS = (
    PREPOSITIONS
    | PARTICLES
    | ARTICLES
    | POSSESSIVE_DETERMINERS
    | AUXILIARIES
    | MODALS
    | NEGATORS
    | CONTRACTED_AUXILIARIES
    | BOUNDARY_WEAK_ADVERBS
    | {"these", "those"}
)


def text_from_words(words):
    return " ".join(word["word"] for word in words).strip()


def build_text_and_spans(words):
    parts = []
    spans = []
    cursor = 0
    for index, word in enumerate(words):
        if index:
            parts.append(" ")
            cursor += 1
        value = word["word"]
        start = cursor
        parts.append(value)
        cursor += len(value)
        spans.append((start, cursor))
    return "".join(parts), spans


def char_to_word_start(spans, char_pos):
    ends = [end for _, end in spans]
    index = bisect.bisect_right(ends, char_pos)
    return min(index, len(spans) - 1)


def char_to_word_end(spans, char_pos):
    starts = [start for start, _ in spans]
    index = bisect.bisect_left(starts, char_pos) - 1
    return max(0, min(index, len(spans) - 1))


def token_word_index(token, spans):
    if token.start_char is None or token.end_char is None:
        return None
    start_index = char_to_word_start(spans, token.start_char)
    end_index = char_to_word_end(spans, token.end_char)
    if start_index == end_index:
        return start_index
    return start_index


def stanza_sentence_ranges(doc, spans, total_words):
    ranges = []
    last_end = 0
    for sentence in doc.sentences:
        sentence_tokens = [token for token in sentence.tokens if token.start_char is not None and token.end_char is not None]
        if not sentence_tokens:
            continue
        start_char = min(token.start_char for token in sentence_tokens)
        end_char = max(token.end_char for token in sentence_tokens)
        start = char_to_word_start(spans, start_char)
        end = char_to_word_end(spans, end_char) + 1
        start = max(last_end, start)
        end = max(start + 1, end)
        if start > last_end:
            ranges.append((last_end, start, "alignment_gap"))
        ranges.append((start, min(end, total_words), "stanza_sentence"))
        last_end = min(end, total_words)
    if last_end < total_words:
        ranges.append((last_end, total_words, "tail_gap"))
    return [(start, end, reason) for start, end, reason in ranges if start < end]


def coarse_should_merge(words, left, right, args):
    left_words = words[left[0] : left[1]]
    right_words = words[right[0] : right[1]]
    merged_duration = right_words[-1]["end"] - left_words[0]["start"]
    merged_words = len(left_words) + len(right_words)
    if merged_duration > args.coarse_max_duration or merged_words > args.coarse_max_words:
        return False

    left_last = left_words[-1]["word"]
    right_first = right_words[0]["word"]
    left_norm = norm_word(left_last)
    right_norm = norm_word(right_first)
    if left_norm in UNSAFE_END_WORDS:
        return True
    if has_soft_punctuation(left_last) and right_norm not in {"and", "but", "so", "now"}:
        return True
    if left_norm in QUOTE_INTRODUCERS and has_soft_punctuation(left_last):
        return True
    if right_norm in WEAK_START_WORDS and starts_lowercase(right_first):
        return True
    if right_norm in DEPENDENT_START_WORDS and starts_lowercase(right_first):
        return True
    return False


def repair_coarse_ranges(words, ranges, args):
    repaired = []
    index = 0
    while index < len(ranges):
        current = ranges[index]
        while index + 1 < len(ranges) and coarse_should_merge(words, current, ranges[index + 1], args):
            current = (current[0], ranges[index + 1][1], current[2] + "+merged_" + ranges[index + 1][2])
            index += 1
        repaired.append(current)
        index += 1
    if args.merge_list_groups:
        return merge_list_like_ranges(words, repaired, args)
    return repaired


def range_words(words, item):
    return words[item[0] : item[1]]


def range_duration(words, item):
    item_words = range_words(words, item)
    return item_words[-1]["end"] - item_words[0]["start"]


def is_section_start(words, item):
    text = text_from_words(range_words(words, item)).strip()
    return bool(SECTION_START_RE.search(text))


def is_list_lead(words, item):
    text = text_from_words(range_words(words, item)).strip()
    return bool(LIST_LEAD_RE.search(text))


def unique_ratio(tokens):
    normalized = [token for token in tokens if token]
    if not normalized:
        return 1.0
    return len(set(normalized)) / len(normalized)


def is_list_like_item(words, item):
    item_words = range_words(words, item)
    count = len(item_words)
    duration = range_duration(words, item)
    tokens = [norm_word(word["word"]) for word in item_words]
    text = text_from_words(item_words)

    if count <= 3:
        return True
    if count <= 8 and duration <= 4.0:
        return True
    if count <= 25 and unique_ratio(tokens) <= 0.72:
        return True
    if count <= 10 and ("," in text or "?" in text):
        return True
    return False


def can_merge_list_group(words, current, nxt, args, already_grouping):
    merged_words = nxt[1] - current[0]
    merged_duration = words[nxt[1] - 1]["end"] - words[current[0]]["start"]
    if merged_words > args.list_group_max_words or merged_duration > args.list_group_max_duration:
        return False
    if is_section_start(words, nxt) and not is_list_like_item(words, nxt):
        return False

    current_is_item = is_list_like_item(words, current)
    next_is_item = is_list_like_item(words, nxt)
    if already_grouping and next_is_item:
        return True
    if is_list_lead(words, current) and next_is_item:
        return True
    if current_is_item and next_is_item:
        return True
    return False


def merge_list_like_ranges(words, ranges, args):
    merged = []
    index = 0
    while index < len(ranges):
        current = ranges[index]
        already_grouping = False
        while index + 1 < len(ranges) and can_merge_list_group(words, current, ranges[index + 1], args, already_grouping):
            current = (current[0], ranges[index + 1][1], current[2] + "+list_group_" + ranges[index + 1][2])
            already_grouping = True
            index += 1
        merged.append(current)
        index += 1
    return merged


def stanza_word_to_original_indexes(sentence, spans):
    indexes = {}
    for token in sentence.tokens:
        original_index = token_word_index(token, spans)
        if original_index is None:
            continue
        for word in token.words:
            indexes[word.id] = original_index
    return indexes


def dependency_boundary_penalties(doc, spans, total_words):
    penalties = {}
    for sentence in doc.sentences:
        indexes = stanza_word_to_original_indexes(sentence, spans)
        for word in sentence.words:
            deprel = word.deprel or ""
            base_deprel = deprel.split(":", 1)[0]
            if word.head == 0 or (
                deprel not in CRITICAL_DEPRELS and base_deprel not in CRITICAL_DEPRELS
            ):
                continue
            child = indexes.get(word.id)
            head = indexes.get(word.head)
            if child is None or head is None or child == head:
                continue
            lo = min(child, head) + 1
            hi = max(child, head) + 1
            distance = hi - lo
            is_strong_crossing = (
                deprel in STRONG_CROSSING_DEPRELS
                or base_deprel in STRONG_CROSSING_DEPRELS
                or deprel in TIGHT_DEPRELS
                or base_deprel in TIGHT_DEPRELS
            )
            if is_strong_crossing:
                weight = 1600.0
            elif distance <= 8:
                weight = 900.0
            elif distance <= 18:
                weight = 400.0
            else:
                weight = 120.0
            for boundary in range(max(1, lo), min(total_words, hi) + 1):
                penalties[boundary] = penalties.get(boundary, 0.0) + weight
    return penalties


def segment_start_cost(words):
    first = norm_word(words[0]["word"])
    if first in CLOSED_CLASS_BAD_START_WORDS and starts_lowercase(words[0]["word"]):
        if first in CLOSED_CLASS_STRONG_BAD_START_WORDS:
            return 150.0
        return 80.0
    if first in WEAK_START_WORDS and starts_lowercase(words[0]["word"]):
        return 100.0
    if first in DEPENDENT_START_WORDS and starts_lowercase(words[0]["word"]):
        return 45.0
    return 0.0


def segment_end_cost(words):
    last = norm_word(words[-1]["word"])
    last_word = words[-1]["word"]
    if has_final_punctuation(last_word):
        return 0.0
    if last in CLOSED_CLASS_BAD_END_WORDS:
        if last in CLOSED_CLASS_STRONG_BAD_END_WORDS:
            return 220.0
        return 170.0
    if last in UNSAFE_END_WORDS:
        return 160.0
    if has_soft_punctuation(last_word):
        return 130.0
    return 0.0


def lexical_boundary_cost(words, boundary):
    if boundary <= 0 or boundary >= len(words):
        return 0.0
    left = words[boundary - 1]["word"]
    right = words[boundary]["word"]
    left_norm = norm_word(left)
    right_norm = norm_word(right)
    cost = 0.0
    if left_norm in CLOSED_CLASS_BAD_END_WORDS:
        if left_norm in CLOSED_CLASS_STRONG_BAD_END_WORDS:
            cost += 240.0
        else:
            cost += 170.0
    if left_norm in UNSAFE_END_WORDS:
        cost += 180.0
    if has_soft_punctuation(left):
        cost += 130.0
    if left_norm in QUOTE_INTRODUCERS and has_soft_punctuation(left):
        cost += 180.0
    if right_norm in CLOSED_CLASS_BAD_START_WORDS and starts_lowercase(right):
        if right_norm in CLOSED_CLASS_STRONG_BAD_START_WORDS:
            cost += 190.0
        else:
            cost += 110.0
    if right_norm in WEAK_START_WORDS and starts_lowercase(right):
        cost += 140.0
    if right_norm in DEPENDENT_START_WORDS and starts_lowercase(right):
        cost += 85.0
    if starts_lowercase(right) and not has_final_punctuation(left):
        cost += 25.0
    return cost


def forbidden_internal_boundary(words, boundary):
    if boundary <= 0 or boundary >= len(words):
        return False
    left_norm = norm_word(words[boundary - 1]["word"])
    right_norm = norm_word(words[boundary]["word"])
    if left_norm in HARD_INTERNAL_BAD_END_WORDS:
        return True
    if right_norm in HARD_INTERNAL_BAD_START_WORDS and starts_lowercase(words[boundary]["word"]):
        return True
    if right_norm in ARTICLES | POSSESSIVE_DETERMINERS and starts_lowercase(words[boundary]["word"]):
        return True
    if right_norm in COORDINATING_CONJUNCTIONS and starts_lowercase(words[boundary]["word"]):
        if boundary + 1 >= len(words):
            return True
        following_norm = norm_word(words[boundary + 1]["word"])
        allowed_after_coordinator = (
            SUBJECT_PRONOUNS
            | DETERMINERS
            | POSSESSIVE_DETERMINERS
            | PREPOSITIONS
            | RELATIVE_WH_WORDS
            | {"there"}
        )
        if following_norm not in allowed_after_coordinator:
            return True
    if left_norm in DISFLUENCY_END_WORDS and boundary >= 2:
        previous_norm = norm_word(words[boundary - 2]["word"])
        return previous_norm in COORDINATING_CONJUNCTIONS
    if boundary >= 2:
        previous_norm = norm_word(words[boundary - 2]["word"])
        if (
            left_norm in {"i", "you", "he", "she", "we", "they", "it"}
            and previous_norm in COORDINATING_CONJUNCTIONS | SUBORDINATORS
            and starts_lowercase(words[boundary]["word"])
        ):
            return True
        if previous_norm == "please" and starts_lowercase(words[boundary]["word"]):
            return True
    if (
        left_norm in SUBJECT_PRONOUNS
        and starts_lowercase(words[boundary]["word"])
    ):
        return True
    if (
        left_norm in SUBJECT_PRONOUNS
        and right_norm in AUXILIARIES | MODALS | CONTRACTED_AUXILIARIES | NEGATORS
    ):
        return True
    return False


def boundary_reward(words, gaps, segment_end_positions, pauses, boundary):
    if boundary <= 0 or boundary >= len(words):
        return 0.0
    left = words[boundary - 1]["word"]
    reward = 0.0
    if has_final_punctuation(left):
        reward += 90.0
    elif has_soft_punctuation(left):
        reward += 8.0
    gap = gaps[boundary - 1]
    if gap >= pauses["very_long"]:
        reward += 70.0
    elif gap >= pauses["long"]:
        reward += 40.0
    elif gap >= pauses["medium"]:
        reward += 12.0
    if boundary in segment_end_positions:
        reward += 6.0
    return reward


def unit_cost(words, start, end, gaps, segment_end_positions, pauses, dep_penalties, args, block_end):
    unit_words = words[start:end]
    word_count = end - start
    duration = unit_words[-1]["end"] - unit_words[0]["start"]
    cost = 0.0

    if duration < args.min_duration:
        cost += (args.min_duration - duration) * 10.0
    if duration > args.target_duration:
        cost += (duration - args.target_duration) * 4.0
    else:
        cost += (args.target_duration - duration) * 0.45
    if duration > args.max_duration:
        cost += 420.0 + (duration - args.max_duration) * 120.0

    if word_count < args.min_words and end != block_end:
        cost += 150.0
    if word_count > args.target_words:
        cost += (word_count - args.target_words) * 3.0
    if word_count > args.max_words:
        cost += 420.0 + (word_count - args.max_words) * 80.0

    cost += segment_start_cost(unit_words)
    cost += segment_end_cost(unit_words)

    if end != block_end:
        cost += dep_penalties.get(end, 0.0)
        cost += lexical_boundary_cost(words, end)
        cost -= boundary_reward(words, gaps, segment_end_positions, pauses, end)
    return cost


def fine_split_block(words, block_start, block_end, gaps, segment_end_positions, pauses, dep_penalties, args):
    block_word_count = block_end - block_start
    block_duration = words[block_end - 1]["end"] - words[block_start]["start"]
    if (
        block_word_count <= args.fine_split_word_threshold
        and block_duration <= args.fine_split_duration_threshold
    ):
        return [(block_start, block_end, "coarse_sentence")]

    dp = {block_start: 0.0}
    back = {}
    for end in range(block_start + 1, block_end + 1):
        best = None
        best_start = None
        lo = max(block_start, end - args.max_words - 18)
        hi = end - 1
        for start in range(lo, hi + 1):
            if start not in dp:
                continue
            if end != block_end and end - start < args.min_words:
                continue
            if end != block_end and forbidden_internal_boundary(words, end):
                continue
            if (
                end != block_end
                and args.hard_dep_boundary_threshold > 0
                and dep_penalties.get(end, 0.0) >= args.hard_dep_boundary_threshold
            ):
                continue
            duration = words[end - 1]["end"] - words[start]["start"]
            if duration > args.max_duration + 7 and end != block_end:
                continue
            score = dp[start] + unit_cost(
                words,
                start,
                end,
                gaps,
                segment_end_positions,
                pauses,
                dep_penalties,
                args,
                block_end,
            )
            if best is None or score < best:
                best = score
                best_start = start
        if best_start is not None:
            dp[end] = best
            back[end] = best_start

    if block_end not in back:
        return [(block_start, block_end, "coarse_sentence_unsplit")]

    pieces = []
    cursor = block_end
    while cursor > block_start:
        start = back[cursor]
        reason = "grammar_block_dp"
        if cursor == block_end:
            reason += "+coarse_end"
        pieces.append((start, cursor, reason))
        cursor = start
    pieces.reverse()
    return pieces


def build_output(data, args):
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
    coarse_ranges = stanza_sentence_ranges(doc, spans, len(words))
    coarse_ranges = repair_coarse_ranges(words, coarse_ranges, args)
    dep_penalties = dependency_boundary_penalties(doc, spans, len(words))

    gaps = compute_gaps(words)
    pauses = compute_pause_thresholds(gaps)
    segment_end_positions = build_segment_end_positions(data.get("segments", []))
    boundaries = []
    for start, end, reason in coarse_ranges:
        pieces = fine_split_block(words, start, end, gaps, segment_end_positions, pauses, dep_penalties, args)
        if len(pieces) == 1:
            boundaries.append((pieces[0][0], pieces[0][1], reason))
        else:
            boundaries.extend(pieces)

    units = [
        make_unit(sentence_id, words[start:end], reason, args.pre_pad, args.post_pad)
        for sentence_id, (start, end, reason) in enumerate(boundaries, start=1)
    ]
    assigned = sum(unit["word_count"] for unit in units)
    coarse_durations = [round(words[end - 1]["end"] - words[start]["start"], 3) for start, end, _ in coarse_ranges]
    coarse_words = [end - start for start, end, _ in coarse_ranges]
    return {
        "metadata": {
            "source": args.input,
            "strategy": "grammar_first_coarse_blocks_then_dp_inside_blocks",
            "uses_llm": False,
            "uses_stanza": True,
            "sentence_count": len(units),
            "word_count": len(words),
            "assigned_word_count": assigned,
            "all_words_assigned": assigned == len(words),
            "coarse_block_count": len(coarse_ranges),
            "coarse_max_duration": max(coarse_durations) if coarse_durations else 0,
            "coarse_max_words": max(coarse_words) if coarse_words else 0,
            "pause_thresholds_seconds": pauses,
            "limits": {
                "min_duration": args.min_duration,
                "target_duration": args.target_duration,
                "max_duration": args.max_duration,
                "target_words": args.target_words,
                "max_words": args.max_words,
                "coarse_max_duration": args.coarse_max_duration,
                "coarse_max_words": args.coarse_max_words,
            },
            "padding": {"pre_seconds": args.pre_pad, "post_seconds": args.post_pad},
        },
        "sentences": units,
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="transcribe-whisperx_result.json")
    parser.add_argument("--output", default="sentence_units_grammar_coarse_test.json")
    parser.add_argument("--model-dir", default="stanza_resources")
    parser.add_argument("--min-words", type=int, default=3)
    parser.add_argument("--target-words", type=int, default=28)
    parser.add_argument("--max-words", type=int, default=56)
    parser.add_argument("--fine-split-word-threshold", type=int, default=30)
    parser.add_argument("--fine-split-duration-threshold", type=float, default=18.0)
    parser.add_argument("--min-duration", type=float, default=1.0)
    parser.add_argument("--target-duration", type=float, default=8.0)
    parser.add_argument("--max-duration", type=float, default=16.0)
    parser.add_argument("--hard-dep-boundary-threshold", type=float, default=0.0)
    parser.add_argument("--coarse-max-words", type=int, default=180)
    parser.add_argument("--coarse-max-duration", type=float, default=65.0)
    parser.add_argument("--merge-list-groups", action="store_true")
    parser.add_argument("--list-group-max-words", type=int, default=80)
    parser.add_argument("--list-group-max-duration", type=float, default=24.0)
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
    print(f"coarse blocks: {metadata['coarse_block_count']}")
    print(f"sentences: {metadata['sentence_count']}")
    print(f"words assigned: {metadata['assigned_word_count']}/{metadata['word_count']}")
    print(f"all words assigned: {metadata['all_words_assigned']}")
    print(f"max duration: {max(unit['duration'] for unit in output['sentences']):.3f}")
    print(f"max words: {max(unit['word_count'] for unit in output['sentences'])}")


if __name__ == "__main__":
    main()
