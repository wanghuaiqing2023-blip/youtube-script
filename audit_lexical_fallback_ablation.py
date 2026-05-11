import argparse
import json
from collections import Counter
from pathlib import Path

import stanza

import split_compound_clauses as splitter


def unit_duration(words):
    return words[-1]["end"] - words[0]["start"]


def should_audit_unit(unit, args):
    words = unit["words"]
    return len(words) > args.split_word_threshold or unit_duration(words) > args.split_duration_threshold


def raw_candidate_boundaries(words, infos, args):
    if args.all_boundaries:
        return list(range(args.min_words, max(args.min_words, len(words) - args.min_words + 1)))

    candidates = set()
    tokens = [splitter.norm_word(word["word"]) for word in words]
    for index, word in enumerate(words[:-1]):
        pos = index + 1
        if pos < args.min_words or len(words) - pos < args.min_words:
            continue
        value = word["word"]
        right = splitter.norm_word(words[pos]["word"])
        left = splitter.norm_word(words[pos - 1]["word"])
        if splitter.has_final_punctuation(value) or splitter.has_soft_punctuation(value):
            candidates.add(pos)
        if right in splitter.COORDINATORS | splitter.SUBORDINATORS:
            candidates.add(pos)
        if splitter.starts_with_any(
            tokens,
            pos,
            splitter.TEMPORAL_CLAUSE_STARTS | splitter.PURPOSE_CLAUSE_STARTS,
        ):
            candidates.add(pos)
        if (
            right in splitter.CLAUSE_START_WORDS
            and left
            not in splitter.PREPOSITIONS
            | splitter.ARTICLES
            | splitter.DETERMINERS
            | splitter.POSSESSIVE_DETERMINERS
            | splitter.AUXILIARIES
            | splitter.MODALS
            and splitter.plausible_clause_start(words, infos, pos)
        ):
            candidates.add(pos)
        for info in infos[pos]:
            if splitter.deprel_base(info["deprel"]) in {"advcl", "ccomp", "conj", "parataxis"}:
                candidates.add(pos)
    return sorted(candidates)


def lexical_fallback_reasons(words, infos, boundary):
    left_word = words[boundary - 1]["word"]
    right_word = words[boundary]["word"]
    left = splitter.norm_word(left_word)
    right = splitter.norm_word(right_word)
    tokens = [splitter.norm_word(word["word"]) for word in words]
    left_tokens = tokens[:boundary]
    reasons = []

    if left in splitter.COORDINATORS | splitter.SUBORDINATORS | splitter.RELATIVE_WORDS:
        reasons.append(f"hard:left_connector:{left}")
    if splitter.ends_with_any(left_tokens, splitter.TEMPORAL_CLAUSE_STARTS):
        reasons.append("hard:left_hanging_temporal_starter")
    if left in splitter.STRONG_BAD_END_WORDS:
        reasons.append(f"hard:left_strong_bad_end:{left}")
    if (
        right in splitter.SUBORDINATORS | splitter.RELATIVE_WORDS
        and splitter.starts_lowercase(right_word)
        and not splitter.has_final_punctuation(left_word)
    ):
        reasons.append(f"hard:right_dependent_clause_start:{right}")
    if (
        right in splitter.ARTICLES | splitter.POSSESSIVE_DETERMINERS
        and not splitter.starts_with_any(tokens, boundary, splitter.TEMPORAL_CLAUSE_STARTS)
    ):
        reasons.append(f"hard:right_determiner_start:{right}")
    if right in splitter.AUXILIARIES | splitter.MODALS | splitter.NEGATORS | splitter.CONTRACTED_AUX:
        reasons.append(f"hard:right_aux_modal_negator_start:{right}")
    if left in splitter.SUBJECT_PRONOUNS and splitter.starts_lowercase(right_word):
        previous = splitter.norm_word(words[boundary - 2]["word"]) if boundary >= 2 else ""
        if not (left == "it" and right in splitter.CLAUSE_START_WORDS) and previous not in splitter.PREPOSITIONS:
            reasons.append(f"hard:subject_pronoun_split:{left}_{right}")
    if boundary >= 2:
        previous = splitter.norm_word(words[boundary - 2]["word"])
        if previous in splitter.PREPOSITIONS and left in splitter.ARTICLES | splitter.POSSESSIVE_DETERMINERS:
            reasons.append(f"hard:prep_determiner_phrase_split:{previous}_{left}")

    if left in splitter.BAD_END_WORDS and left not in splitter.STRONG_BAD_END_WORDS:
        reasons.append(f"soft:left_bad_end:{left}")
    if (
        right in splitter.BAD_START_WORDS
        and splitter.starts_lowercase(right_word)
        and not splitter.starts_with_any(tokens, boundary, splitter.TEMPORAL_CLAUSE_STARTS)
    ):
        reasons.append(f"soft:right_bad_start:{right}")
    if right in splitter.OBJECT_PRONOUNS and not splitter.word_has_subject_role(infos, boundary):
        reasons.append(f"soft:right_object_pronoun_start:{right}")
    if splitter.starts_lowercase(right_word) and not splitter.has_final_punctuation(left_word):
        reasons.append("soft:right_lowercase_without_final_punctuation")

    return reasons


def window_text(words, boundary, radius=8):
    start = max(0, boundary - radius)
    end = min(len(words), boundary + radius)
    before = splitter.text_from_words(words[start:boundary])
    after = splitter.text_from_words(words[boundary:end])
    return before, after


def crossing_edges(words, infos, boundary):
    edges = []
    for child_index, child_infos in enumerate(infos):
        for info in child_infos:
            head = info.get("head")
            if head is None or head == child_index:
                continue
            child_left = child_index < boundary
            head_left = head < boundary
            if child_left == head_left:
                continue

            base = splitter.deprel_base(info["deprel"])
            if base in splitter.IGNORED_CROSSING_DEPRELS:
                category = "ignored"
                penalty = 0.0
            elif base in splitter.TIGHT_DEPRELS:
                category = "tight"
                penalty = 1000.0
            elif base in splitter.CORE_CROSSING_DEPRELS:
                distance = abs(child_index - head)
                category = "core_near" if distance <= 10 else "core_far"
                penalty = 360.0 if distance <= 10 else 160.0
            else:
                category = "light"
                penalty = 90.0

            edges.append(
                {
                    "child_index": child_index,
                    "child_word": words[child_index]["word"],
                    "child_upos": info["upos"],
                    "deprel": info["deprel"],
                    "base_deprel": base,
                    "head_index": head,
                    "head_word": words[head]["word"] if 0 <= head < len(words) else None,
                    "child_side": "left" if child_left else "right",
                    "head_side": "left" if head_left else "right",
                    "category": category,
                    "parser_only_penalty": penalty,
                }
            )
    return edges


def word_infos(infos, index):
    return [
        {
            "text": info["text"],
            "upos": info["upos"],
            "deprel": info["deprel"],
            "head": info["head"],
        }
        for info in infos[index]
    ]


def parser_miss_reasons(reasons, edges, parser_only_cost, max_boundary_cost):
    summaries = []
    if not edges:
        summaries.append("no_crossing_dependency_found")
    else:
        categories = sorted({edge["category"] for edge in edges})
        summaries.append("crossing_dependencies_found:" + ",".join(categories))
        if all(edge["category"] == "ignored" for edge in edges):
            summaries.append("all_crossings_ignored_by_parser_only_policy")
        elif parser_only_cost < max_boundary_cost:
            summaries.append("crossing_penalty_below_block_threshold")

    for reason in reasons:
        if reason.startswith("hard:right_determiner_start"):
            summaries.append("right_determiner_is_start_completeness_issue_not_crossing_issue")
        elif reason.startswith("hard:right_aux_modal_negator_start"):
            summaries.append("right_aux_modal_start_is_start_completeness_issue_not_crossing_issue")
        elif reason.startswith("hard:right_dependent_clause_start"):
            summaries.append("dependent_clause_start_can_parse_internally_without_blocking_crossing")
        elif reason.startswith("hard:left_connector"):
            summaries.append("left_hanging_connector_often_has_ignored_or_low_cost_cc_relation")
        elif reason.startswith("hard:left_strong_bad_end"):
            summaries.append("left_hanging_function_word_not_reliably_blocked_by_crossing")
        elif reason.startswith("hard:subject_pronoun_split"):
            summaries.append("subject_predicate_split_needs_lexical_escalation_when_nsubj_cost_is_below_threshold")
        elif reason.startswith("hard:prep_determiner_phrase_split"):
            summaries.append("preposition_determiner_fragment_may_not_create_boundary_crossing")
        elif reason.startswith("hard:left_hanging_temporal_starter"):
            summaries.append("temporal_starter_fragment_is_span_completeness_issue")
    return sorted(set(summaries))


def audit(data, args):
    units, input_key = splitter.input_units(data)
    nlp = stanza.Pipeline(
        "en",
        model_dir=args.model_dir,
        processors="tokenize,pos,lemma,depparse",
        use_gpu=False,
        verbose=False,
        download_method=None,
    )

    label_counts = Counter()
    totals = Counter()
    samples = []

    for unit in units:
        if not should_audit_unit(unit, args):
            continue
        totals["audited_units"] += 1
        words = unit["words"]
        infos = splitter.parse_unit_words(nlp, words)
        candidates = raw_candidate_boundaries(words, infos, args)
        totals["raw_candidate_boundaries"] += len(candidates)

        for boundary in candidates:
            parser_only_cost = splitter.dependency_crossing_cost(infos, boundary)
            parser_only_safe = parser_only_cost < args.max_boundary_cost
            if not parser_only_safe:
                continue

            totals["parser_only_safe_boundaries"] += 1
            current_hard_forbidden = splitter.forbidden_boundary(words, boundary)
            current_cost = splitter.boundary_cost(words, infos, boundary)
            current_safe = current_cost < args.max_boundary_cost
            reasons = lexical_fallback_reasons(words, infos, boundary)

            if current_hard_forbidden:
                bucket = "hard_fallback_blocked"
            elif not current_safe:
                bucket = "soft_fallback_blocked"
            elif reasons:
                bucket = "risky_still_allowed"
            else:
                bucket = "clean_parser_only_safe"

            totals[bucket] += 1
            for reason in reasons:
                label_counts[reason] += 1

            if bucket != "clean_parser_only_safe" and len(samples) < args.limit_samples:
                before, after = window_text(words, boundary)
                edges = crossing_edges(words, infos, boundary)
                samples.append(
                    {
                        "bucket": bucket,
                        "unit_id": unit.get("id"),
                        "boundary": boundary,
                        "unit_word_count": len(words),
                        "unit_duration": round(unit_duration(words), 3),
                        "left_word": words[boundary - 1]["word"],
                        "right_word": words[boundary]["word"],
                        "parser_only_cost": round(parser_only_cost, 3),
                        "current_cost": "inf" if current_cost == float("inf") else round(current_cost, 3),
                        "reasons": reasons,
                        "parser_miss_reasons": parser_miss_reasons(
                            reasons,
                            edges,
                            parser_only_cost,
                            args.max_boundary_cost,
                        ),
                        "crossing_edges": edges,
                        "left_word_infos": word_infos(infos, boundary - 1),
                        "right_word_infos": word_infos(infos, boundary),
                        "left_context": before,
                        "right_context": after,
                        "unit_text": splitter.text_from_words(words),
                    }
                )

    return {
        "metadata": {
            "source": args.input,
            "input_collection": input_key,
            "mode": "all_boundaries" if args.all_boundaries else "splitter_candidate_boundaries",
            "max_boundary_cost": args.max_boundary_cost,
            "split_word_threshold": args.split_word_threshold,
            "split_duration_threshold": args.split_duration_threshold,
        },
        "totals": dict(totals),
        "label_counts": dict(label_counts.most_common()),
        "samples": samples,
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="coarse_blocks_pure_grammar.json")
    parser.add_argument("--output", default="lexical_fallback_ablation_audit.json")
    parser.add_argument("--model-dir", default="stanza_resources")
    parser.add_argument("--split-word-threshold", type=int, default=30)
    parser.add_argument("--split-duration-threshold", type=float, default=14.0)
    parser.add_argument("--min-words", type=int, default=4)
    parser.add_argument("--max-boundary-cost", type=float, default=450.0)
    parser.add_argument("--limit-samples", type=int, default=120)
    parser.add_argument("--all-boundaries", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    report = audit(data, args)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    totals = report["totals"]
    print(f"Wrote {args.output}")
    print(f"audited units: {totals.get('audited_units', 0)}")
    print(f"raw candidate boundaries: {totals.get('raw_candidate_boundaries', 0)}")
    print(f"parser-only safe boundaries: {totals.get('parser_only_safe_boundaries', 0)}")
    print(f"hard fallback blocked: {totals.get('hard_fallback_blocked', 0)}")
    print(f"soft fallback blocked: {totals.get('soft_fallback_blocked', 0)}")
    print(f"risky still allowed: {totals.get('risky_still_allowed', 0)}")
    print(f"clean parser-only safe: {totals.get('clean_parser_only_safe', 0)}")


if __name__ == "__main__":
    main()
