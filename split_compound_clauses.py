import argparse
import bisect
import json
import math
import re
from pathlib import Path

import stanza


FINAL_PUNCT_RE = re.compile(r'[.!?]+["\')\]]*$')
SOFT_PUNCT_RE = re.compile(r'[,;:]+["\')\]]*$')
TRIM_RE = re.compile(r"^[^\w']+|[^\w']+$")

COORDINATORS = {"and", "but", "or", "so", "yet"}
CLAUSE_START_WORDS = {
    "i",
    "i'm",
    "i'll",
    "i've",
    "you",
    "you're",
    "you'll",
    "we",
    "we're",
    "they",
    "they're",
    "he",
    "she",
    "it",
    "it's",
    "this",
    "that",
    "there",
    "let's",
}
CONTRACTION_PREDICATE_HINTS = {
    "i'm",
    "i'll",
    "i've",
    "you're",
    "you'll",
    "you've",
    "we're",
    "we'll",
    "we've",
    "they're",
    "they'll",
    "they've",
    "he's",
    "she's",
    "it's",
    "that's",
}
OBJECT_PRONOUNS = {"me", "him", "her", "us", "them", "it"}
TEMPORAL_CLAUSE_STARTS = {
    ("the", "first", "time"),
    ("the", "second", "time"),
    ("next", "time"),
    ("this", "time"),
}
PURPOSE_CLAUSE_STARTS = {
    ("to", "make"),
    ("to", "show"),
    ("to", "help"),
    ("to", "practice"),
    ("to", "understand"),
}
SUBORDINATORS = {
    "after",
    "although",
    "as",
    "because",
    "before",
    "if",
    "once",
    "since",
    "than",
    "that",
    "though",
    "unless",
    "until",
    "when",
    "where",
    "whereas",
    "whether",
    "while",
}
RELATIVE_WORDS = {"that", "which", "who", "whom", "whose", "where", "when", "why"}
PREPOSITIONS = {
    "about",
    "above",
    "across",
    "after",
    "against",
    "around",
    "as",
    "at",
    "before",
    "behind",
    "below",
    "between",
    "by",
    "during",
    "for",
    "from",
    "in",
    "inside",
    "into",
    "like",
    "near",
    "of",
    "off",
    "on",
    "onto",
    "out",
    "outside",
    "over",
    "through",
    "to",
    "under",
    "until",
    "up",
    "with",
    "without",
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
    "many",
    "more",
    "most",
    "much",
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
    "which",
    "whose",
}
POSSESSIVE_DETERMINERS = {"her", "his", "its", "my", "our", "their", "your"}
SUBJECT_PRONOUNS = {"i", "you", "he", "she", "we", "they", "it"}
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
    "is",
    "was",
    "were",
}
MODALS = {
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
NEGATORS = {"not", "n't"}
CONTRACTED_AUX = {
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
    "shouldn't",
    "wasn't",
    "weren't",
    "won't",
    "wouldn't",
}
BAD_END_WORDS = (
    COORDINATORS
    | SUBORDINATORS
    | RELATIVE_WORDS
    | PREPOSITIONS
    | ARTICLES
    | DETERMINERS
    | POSSESSIVE_DETERMINERS
    | AUXILIARIES
    | MODALS
    | NEGATORS
    | CONTRACTED_AUX
)
STRONG_BAD_END_WORDS = (
    PREPOSITIONS
    | ARTICLES
    | POSSESSIVE_DETERMINERS
    | AUXILIARIES
    | MODALS
    | NEGATORS
    | CONTRACTED_AUX
)
BAD_START_WORDS = (
    SUBORDINATORS
    | RELATIVE_WORDS
    | PREPOSITIONS
    | ARTICLES
    | POSSESSIVE_DETERMINERS
    | AUXILIARIES
    | MODALS
    | NEGATORS
    | CONTRACTED_AUX
)
CLAUSE_DEPRELS = {"root", "cop", "xcomp", "ccomp", "conj", "advcl", "acl", "parataxis"}
SUBJECT_DEPRELS = {"nsubj", "csubj", "expl"}
TIGHT_DEPRELS = {"aux", "case", "cop", "det", "fixed", "flat", "mark"}
CORE_CROSSING_DEPRELS = {"nsubj", "obj", "iobj", "xcomp", "ccomp", "obl", "nmod"}
IGNORED_CROSSING_DEPRELS = {"punct", "cc", "discourse", "parataxis"}

FINITE_VERB_HINTS = {
    "am",
    "are",
    "is",
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
    "need",
    "needs",
    "needed",
    "go",
    "goes",
    "went",
    "gone",
    "gonna",
    "want",
    "wants",
    "wanted",
    "say",
    "says",
    "said",
    "mean",
    "means",
    "called",
} | CONTRACTION_PREDICATE_HINTS


def starts_with_any(tokens, start, phrases):
    for phrase in phrases:
        if tuple(tokens[start : start + len(phrase)]) == phrase:
            return True
    return False


def ends_with_any(tokens, phrases):
    for phrase in phrases:
        if len(tokens) >= len(phrase) and tuple(tokens[-len(phrase) :]) == phrase:
            return True
    return False


def norm_word(value):
    return TRIM_RE.sub("", value).lower()


def text_from_words(words):
    return " ".join(word["word"] for word in words).strip()


def has_final_punctuation(value):
    return bool(FINAL_PUNCT_RE.search(value.strip()))


def has_soft_punctuation(value):
    return bool(SOFT_PUNCT_RE.search(value.strip()))


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


def parse_unit_words(nlp, words):
    text, spans = build_text_and_spans(words)
    doc = nlp(text)
    infos = [[] for _ in words]
    for sentence in doc.sentences:
        id_to_index = {}
        for token in sentence.tokens:
            original_index = token_word_index(token, spans)
            if original_index is None:
                continue
            for stanza_word in token.words:
                id_to_index[stanza_word.id] = original_index
        for stanza_word in sentence.words:
            original_index = id_to_index.get(stanza_word.id)
            if original_index is None:
                continue
            head_index = id_to_index.get(stanza_word.head)
            infos[original_index].append(
                {
                    "text": stanza_word.text,
                    "lemma": stanza_word.lemma or "",
                    "upos": stanza_word.upos or "",
                    "deprel": stanza_word.deprel or "",
                    "head": head_index,
                }
            )
    return infos


def deprel_base(deprel):
    return (deprel or "").split(":", 1)[0]


def span_infos(infos, start, end):
    result = []
    for index in range(start, end):
        result.extend(infos[index])
    return result


def has_predicate_span(words, infos, start, end):
    tokens = [norm_word(word["word"]) for word in words[start:end]]
    for token in tokens:
        if token in FINITE_VERB_HINTS:
            return True
        if len(token) > 4 and (token.endswith("ed") or token.endswith("n't")):
            return True
    for info in span_infos(infos, start, end):
        base = deprel_base(info["deprel"])
        if info["upos"] in {"VERB", "AUX"} and base in CLAUSE_DEPRELS:
            return True
    return False


def has_subject_span(infos, start, end):
    return any(deprel_base(info["deprel"]) in SUBJECT_DEPRELS for info in span_infos(infos, start, end))


def word_has_subject_role(infos, index):
    return any(deprel_base(info["deprel"]) in SUBJECT_DEPRELS for info in infos[index])


def plausible_clause_start(words, infos, start):
    if start >= len(words):
        return False
    tokens = [norm_word(word["word"]) for word in words]
    token = tokens[start]
    if starts_with_any(tokens, start, TEMPORAL_CLAUSE_STARTS | PURPOSE_CLAUSE_STARTS):
        return True
    if token not in CLAUSE_START_WORDS:
        return False
    if start + 1 < len(words) and tokens[start + 1] in CLAUSE_START_WORDS:
        return False
    if token in OBJECT_PRONOUNS and not word_has_subject_role(infos, start):
        return False
    return has_predicate_span(words, infos, start, min(len(words), start + 8))


def is_imperative_like(words, infos, start, end):
    if start >= end:
        return False
    first = norm_word(words[start]["word"])
    if first in {"listen", "look", "try", "take", "let", "remember", "notice", "watch", "repeat"}:
        return True
    for info in infos[start]:
        if info["upos"] == "VERB" and deprel_base(info["deprel"]) in {"root", "conj"}:
            return True
    return False


def is_clause_like(words, infos, start, end):
    count = end - start
    if count <= 4:
        return True
    tokens = [norm_word(word["word"]) for word in words[start:end]]
    if starts_with_any(tokens, 0, TEMPORAL_CLAUSE_STARTS):
        return has_predicate_span(words, infos, start, end)
    if starts_with_any(tokens, 0, PURPOSE_CLAUSE_STARTS):
        return True
    if not has_predicate_span(words, infos, start, end):
        return False
    if has_subject_span(infos, start, end):
        return True
    if is_imperative_like(words, infos, start, end):
        return True
    first = norm_word(words[start]["word"])
    return first in {"what", "why", "how", "where", "when", "who"}


def forbidden_boundary(words, boundary):
    if boundary <= 0 or boundary >= len(words):
        return True
    left = norm_word(words[boundary - 1]["word"])
    right = norm_word(words[boundary]["word"])
    tokens = [norm_word(word["word"]) for word in words]
    left_tokens = tokens[:boundary]
    if left in COORDINATORS | SUBORDINATORS | RELATIVE_WORDS:
        return True
    if ends_with_any(left_tokens, TEMPORAL_CLAUSE_STARTS):
        return True
    if left in STRONG_BAD_END_WORDS:
        return True
    if right in SUBORDINATORS | RELATIVE_WORDS and starts_lowercase(words[boundary]["word"]) and not has_final_punctuation(words[boundary - 1]["word"]):
        return True
    if right in ARTICLES | POSSESSIVE_DETERMINERS and not starts_with_any(tokens, boundary, TEMPORAL_CLAUSE_STARTS):
        return True
    if right in AUXILIARIES | MODALS | NEGATORS | CONTRACTED_AUX:
        return True
    if left in SUBJECT_PRONOUNS and starts_lowercase(words[boundary]["word"]):
        previous = norm_word(words[boundary - 2]["word"]) if boundary >= 2 else ""
        if not (left == "it" and right in CLAUSE_START_WORDS) and previous not in PREPOSITIONS:
            return True
    if boundary >= 2:
        previous = norm_word(words[boundary - 2]["word"])
        if previous in PREPOSITIONS and left in ARTICLES | POSSESSIVE_DETERMINERS:
            return True
    return False


def dependency_crossing_cost(infos, boundary):
    cost = 0.0
    for child_index, child_infos in enumerate(infos):
        for info in child_infos:
            head = info.get("head")
            if head is None or head == child_index:
                continue
            child_left = child_index < boundary
            head_left = head < boundary
            if child_left == head_left:
                continue
            base = deprel_base(info["deprel"])
            if base in IGNORED_CROSSING_DEPRELS:
                continue
            distance = abs(child_index - head)
            if base in TIGHT_DEPRELS:
                cost += 1000.0
            elif base in CORE_CROSSING_DEPRELS:
                cost += 360.0 if distance <= 10 else 160.0
            else:
                cost += 90.0
    return cost


def boundary_cost(words, infos, boundary):
    if forbidden_boundary(words, boundary):
        return float("inf")

    left_word = words[boundary - 1]["word"]
    right_word = words[boundary]["word"]
    left = norm_word(left_word)
    right = norm_word(right_word)
    left_tokens = [norm_word(word["word"]) for word in words[:boundary]]
    all_tokens = [norm_word(word["word"]) for word in words]
    starts_temporal_clause = starts_with_any(all_tokens, boundary, TEMPORAL_CLAUSE_STARTS)
    cost = dependency_crossing_cost(infos, boundary)

    if ends_with_any(left_tokens, TEMPORAL_CLAUSE_STARTS):
        cost += 350.0
    if left in BAD_END_WORDS:
        cost += 180.0 if left in STRONG_BAD_END_WORDS else 90.0
    if right in BAD_START_WORDS and starts_lowercase(right_word) and not starts_temporal_clause:
        cost += 130.0
    if right in SUBORDINATORS | RELATIVE_WORDS and starts_lowercase(right_word):
        cost += 80.0
    if right in OBJECT_PRONOUNS and not word_has_subject_role(infos, boundary):
        cost += 420.0
    if starts_lowercase(right_word) and not has_final_punctuation(left_word):
        cost += 12.0
    if starts_temporal_clause:
        cost -= 170.0

    if has_final_punctuation(left_word):
        cost -= 120.0
    elif ";" in left_word or ":" in left_word:
        cost -= 80.0
    elif "," in left_word:
        cost -= 45.0

    if right in COORDINATORS:
        if is_clause_like(words, infos, boundary, len(words)):
            cost -= 35.0
        else:
            cost += 160.0

    if not is_clause_like(words, infos, 0, boundary) and boundary >= 6:
        cost += 120.0
    if not is_clause_like(words, infos, boundary, len(words)) and len(words) - boundary >= 6:
        cost += 120.0

    return cost


def boundary_reason(words, boundary):
    left = words[boundary - 1]["word"]
    right = norm_word(words[boundary]["word"])
    reasons = []
    if has_final_punctuation(left):
        reasons.append("final_punctuation")
    elif ";" in left:
        reasons.append("semicolon")
    elif ":" in left:
        reasons.append("colon")
    elif "," in left:
        reasons.append("comma")
    if right in COORDINATORS:
        reasons.append("coordinator")
    if right in SUBORDINATORS:
        reasons.append("subordinator")
    if right in RELATIVE_WORDS:
        reasons.append("relative")
    return "+".join(reasons) or "clause_boundary"


def candidate_boundaries(words, infos, args):
    candidates = {0, len(words)}
    tokens = [norm_word(word["word"]) for word in words]
    for index, word in enumerate(words[:-1]):
        pos = index + 1
        if pos < args.min_words or len(words) - pos < args.min_words:
            continue
        value = word["word"]
        right = norm_word(words[pos]["word"])
        left = norm_word(words[pos - 1]["word"])
        if has_final_punctuation(value) or has_soft_punctuation(value):
            candidates.add(pos)
        if right in COORDINATORS | SUBORDINATORS:
            candidates.add(pos)
        if starts_with_any(tokens, pos, TEMPORAL_CLAUSE_STARTS | PURPOSE_CLAUSE_STARTS):
            candidates.add(pos)
        if (
            right in CLAUSE_START_WORDS
            and left not in PREPOSITIONS | ARTICLES | DETERMINERS | POSSESSIVE_DETERMINERS | AUXILIARIES | MODALS
            and plausible_clause_start(words, infos, pos)
        ):
            candidates.add(pos)
        for info in infos[pos]:
            if deprel_base(info["deprel"]) in {"advcl", "ccomp", "conj", "parataxis"}:
                candidates.add(pos)

    safe = {0, len(words)}
    for boundary in candidates:
        if boundary in {0, len(words)} or boundary_cost(words, infos, boundary) < args.max_boundary_cost:
            safe.add(boundary)
    return sorted(safe)


def segment_cost(words, infos, start, end, args):
    segment_words = words[start:end]
    word_count = end - start
    duration = segment_words[-1]["end"] - segment_words[0]["start"]
    cost = 0.0

    cost += abs(duration - args.target_duration) * 1.2
    if duration > args.max_duration:
        cost += 360.0 + (duration - args.max_duration) * 90.0
    if word_count > args.target_words:
        cost += (word_count - args.target_words) * 3.0
    if word_count > args.max_words:
        cost += 360.0 + (word_count - args.max_words) * 70.0
    if word_count < args.min_words:
        cost += 120.0

    if not is_clause_like(words, infos, start, end) and word_count >= 6:
        cost += 100.0

    first = norm_word(segment_words[0]["word"])
    last = norm_word(segment_words[-1]["word"])
    tokens = [norm_word(word["word"]) for word in segment_words]
    if first in BAD_START_WORDS and starts_lowercase(segment_words[0]["word"]):
        cost += 70.0
    if last in BAD_END_WORDS and not has_final_punctuation(segment_words[-1]["word"]):
        cost += 80.0
    if ends_with_any(tokens, TEMPORAL_CLAUSE_STARTS) and not has_final_punctuation(segment_words[-1]["word"]):
        cost += 350.0

    if end < len(words):
        cost += boundary_cost(words, infos, end)
    return cost


def split_unit_words(words, nlp, args):
    duration = words[-1]["end"] - words[0]["start"]
    if len(words) <= args.split_word_threshold and duration <= args.split_duration_threshold:
        return [(0, len(words), "preserved")]

    infos = parse_unit_words(nlp, words)
    candidates = candidate_boundaries(words, infos, args)
    if len(candidates) <= 2:
        return [(0, len(words), "compound_unsplit:no_safe_boundary")]

    n = len(words)
    dp = {0: 0.0}
    back = {}
    for end in candidates[1:]:
        best = None
        best_start = None
        for start in candidates:
            if start >= end or start not in dp:
                continue
            if end != n and end - start < args.min_words:
                continue
            if end - start > args.max_words + 20:
                continue
            duration = words[end - 1]["end"] - words[start]["start"]
            if end != n and duration > args.max_duration + 8:
                continue
            score = dp[start] + segment_cost(words, infos, start, end, args)
            if best is None or score < best:
                best = score
                best_start = start
        if best_start is not None:
            dp[end] = best
            back[end] = best_start

    if n not in back:
        return [(0, n, "compound_unsplit:dp_failed")]

    pieces = []
    cursor = n
    while cursor > 0:
        start = back[cursor]
        reason = "compound_clause_rule"
        if cursor < n:
            reason += ":" + boundary_reason(words, cursor)
        else:
            reason += ":unit_end"
        pieces.append((start, cursor, reason))
        cursor = start
    pieces.reverse()

    if len(pieces) == 1:
        return [(0, n, "compound_unsplit:no_better_split")]
    return pieces


def make_output_unit(sentence_id, words, reason, pre_pad, post_pad):
    start = words[0]["start"]
    end = words[-1]["end"]
    cut_start = max(0.0, start - pre_pad)
    cut_end = end + post_pad
    scores = [word.get("score") for word in words if word.get("score") is not None]
    output = {
        "id": sentence_id,
        "start": round(start, 3),
        "end": round(end, 3),
        "cut_start": round(cut_start, 3),
        "cut_end": round(cut_end, 3),
        "duration": round(end - start, 3),
        "cut_duration": round(cut_end - cut_start, 3),
        "text": text_from_words(words),
        "word_count": len(words),
        "avg_score": round(sum(scores) / len(scores), 3) if scores else None,
        "boundary_reason": reason,
        "words": words,
    }
    if "index" in words[0]:
        output["start_word_index"] = words[0]["index"]
        output["end_word_index"] = words[-1]["index"] + 1
    return output


def input_units(data):
    if "blocks" in data:
        return data["blocks"], "blocks"
    if "sentences" in data:
        return data["sentences"], "sentences"
    raise ValueError("Input JSON must contain either 'blocks' or 'sentences'.")


def build_output(data, args):
    units, input_key = input_units(data)
    nlp = stanza.Pipeline(
        "en",
        model_dir=args.model_dir,
        processors="tokenize,pos,lemma,depparse",
        use_gpu=False,
        verbose=False,
        download_method=None,
    )

    output_units = []
    split_count = 0
    for unit in units:
        words = unit["words"]
        pieces = split_unit_words(words, nlp, args)
        if len(pieces) > 1:
            split_count += 1
        source_reason = unit.get("boundary_reason") or unit.get("reason") or input_key
        for start, end, reason in pieces:
            if reason == "preserved":
                final_reason = source_reason
            else:
                final_reason = reason + "+source_" + source_reason
            output_units.append(
                make_output_unit(
                    len(output_units) + 1,
                    words[start:end],
                    final_reason,
                    args.pre_pad,
                    args.post_pad,
                )
            )

    assigned = sum(unit["word_count"] for unit in output_units)
    input_word_count = sum(unit["word_count"] for unit in units)
    durations = [unit["duration"] for unit in output_units]
    word_counts = [unit["word_count"] for unit in output_units]
    return {
        "metadata": {
            "source": args.input,
            "strategy": "rule_based_compound_sentence_clause_splitter",
            "uses_llm": False,
            "uses_stanza": True,
            "input_collection": input_key,
            "input_unit_count": len(units),
            "sentence_count": len(output_units),
            "split_unit_count": split_count,
            "word_count": input_word_count,
            "assigned_word_count": assigned,
            "all_words_assigned": assigned == input_word_count,
            "max_duration": max(durations) if durations else 0,
            "max_words": max(word_counts) if word_counts else 0,
            "limits": {
                "split_word_threshold": args.split_word_threshold,
                "split_duration_threshold": args.split_duration_threshold,
                "target_duration": args.target_duration,
                "max_duration": args.max_duration,
                "target_words": args.target_words,
                "max_words": args.max_words,
                "max_boundary_cost": args.max_boundary_cost,
            },
            "padding": {"pre_seconds": args.pre_pad, "post_seconds": args.post_pad},
        },
        "sentences": output_units,
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="coarse_blocks_pure_grammar.json")
    parser.add_argument("--output", default="sentence_units_compound_clause_rules.json")
    parser.add_argument("--model-dir", default="stanza_resources")
    parser.add_argument("--split-word-threshold", type=int, default=30)
    parser.add_argument("--split-duration-threshold", type=float, default=14.0)
    parser.add_argument("--min-words", type=int, default=4)
    parser.add_argument("--target-words", type=int, default=18)
    parser.add_argument("--max-words", type=int, default=34)
    parser.add_argument("--target-duration", type=float, default=6.5)
    parser.add_argument("--max-duration", type=float, default=11.0)
    parser.add_argument("--max-boundary-cost", type=float, default=450.0)
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
    print(f"input units: {metadata['input_unit_count']}")
    print(f"output units: {metadata['sentence_count']}")
    print(f"split units: {metadata['split_unit_count']}")
    print(f"words assigned: {metadata['assigned_word_count']}/{metadata['word_count']}")
    print(f"all words assigned: {metadata['all_words_assigned']}")
    print(f"max duration: {metadata['max_duration']:.3f}")
    print(f"max words: {metadata['max_words']}")


if __name__ == "__main__":
    main()
