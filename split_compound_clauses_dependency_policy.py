import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import stanza

import split_compound_clauses as base


HARD_TIGHT_DEPRELS = {"aux", "case", "cop", "det", "fixed", "flat", "mark"}
LOCAL_CORE_DEPRELS = {"nsubj", "csubj", "obj", "iobj", "xcomp", "ccomp"}
CLAUSE_CANDIDATE_DEPRELS = {"advcl", "acl", "ccomp", "conj", "parataxis"}
COMPLETENESS_ANCHOR_DEPRELS = {"root", "conj", "parataxis", "advcl", "acl", "ccomp", "xcomp"}
INDEPENDENT_ANCHOR_DEPRELS = {"root", "conj", "parataxis"}
DEPENDENT_ANCHOR_DEPRELS = {"advcl", "acl", "ccomp", "xcomp"}
DANGLING_START_DEPRELS = {"case", "mark", "cc", "fixed", "flat"}
DANGLING_CONDITIONAL_START_DEPRELS = {"aux", "cop", "det"}
DANGLING_END_DEPRELS = {"aux", "case", "cc", "cop", "det", "fixed", "flat", "mark"}
CLAUSE_PENALTY = {
    "advcl": 180.0,
    "acl": 220.0,
    "ccomp": 260.0,
    "conj": 90.0,
    "parataxis": 20.0,
}
IGNORED_DEPRELS = {"punct", "discourse"}


def iter_edges(infos):
    for child_index, child_infos in enumerate(infos):
        for info in child_infos:
            head = info.get("head")
            if head is None or head == child_index:
                continue
            deprel = info["deprel"] or ""
            base_deprel = base.deprel_base(deprel)
            yield {
                "child": child_index,
                "head": head,
                "deprel": deprel,
                "base": base_deprel,
                "upos": info["upos"],
                "text": info["text"],
            }


def build_children(infos):
    children = defaultdict(list)
    for edge in iter_edges(infos):
        children[edge["head"]].append(edge)
    return children


def subtree_indexes(root, children):
    seen = set()
    stack = [root]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for edge in children.get(current, []):
            stack.append(edge["child"])
    return seen


def add_candidate(candidates, boundary, reason, words, args):
    if boundary <= args.min_words - 1 or boundary >= len(words) - args.min_words + 1:
        return
    candidates[boundary].add(reason)


def dependency_candidate_boundaries(words, infos, args):
    candidates = defaultdict(set)
    children = build_children(infos)

    for index, word_infos in enumerate(infos):
        if not any(base.deprel_base(info["deprel"]) == "root" for info in word_infos):
            continue
        subtree = subtree_indexes(index, children)
        if not subtree:
            continue
        sentence_start = min(subtree)
        if sentence_start > 0:
            add_candidate(candidates, sentence_start, "independent_root_start", words, args)

    for edge in iter_edges(infos):
        child = edge["child"]
        head = edge["head"]
        base_deprel = edge["base"]

        if base_deprel == "cc":
            add_candidate(candidates, child, "cc_before_connector", words, args)
            continue

        if base_deprel == "mark":
            # Boundary before a subordinate marker: "... / because ...", "... / if ..."
            add_candidate(candidates, child, "mark_subordinate_start", words, args)
            continue

        if base_deprel not in CLAUSE_CANDIDATE_DEPRELS:
            continue

        subtree = subtree_indexes(child, children)
        if not subtree:
            continue
        subtree_start = min(subtree)
        subtree_end = max(subtree) + 1

        if child > head:
            cc_children = [
                item["child"]
                for item in children.get(child, [])
                if item["base"] == "cc" and item["child"] < child
            ]
            boundary = min(cc_children) if cc_children else subtree_start
            add_candidate(candidates, boundary, f"{base_deprel}_subtree_start", words, args)
        else:
            add_candidate(candidates, subtree_end, f"{base_deprel}_subtree_end", words, args)

    if args.include_punctuation_candidates:
        for index, word in enumerate(words[:-1]):
            if has_boundary_punctuation(words, infos, index, args):
                add_candidate(candidates, index + 1, "punctuation", words, args)

    return candidates


def crossing_edges(words, infos, boundary):
    edges = []
    for edge in iter_edges(infos):
        child = edge["child"]
        head = edge["head"]
        child_left = child < boundary
        head_left = head < boundary
        if child_left == head_left:
            continue
        distance = abs(child - head)
        edges.append(
            {
                **edge,
                "distance": distance,
                "child_word": words[child]["word"],
                "head_word": words[head]["word"] if 0 <= head < len(words) else None,
                "child_side": "left" if child_left else "right",
                "head_side": "left" if head_left else "right",
            }
        )
    return edges


def non_punct_infos_at(infos, index):
    return [
        info
        for info in infos[index]
        if info["upos"] != "PUNCT" and base.deprel_base(info["deprel"]) not in IGNORED_DEPRELS
    ]


def has_punctuation_role(infos, index):
    return any(
        info["upos"] == "PUNCT" or base.deprel_base(info["deprel"]) == "punct"
        for info in infos[index]
    )


def has_boundary_punctuation(words, infos, index, args):
    if args.no_lexicon:
        return has_punctuation_role(infos, index)
    return base.has_final_punctuation(words[index]["word"]) or base.has_soft_punctuation(words[index]["word"])


def has_soft_boundary_punctuation(words, infos, index, args):
    if args.no_lexicon:
        return has_punctuation_role(infos, index)
    return base.has_soft_punctuation(words[index]["word"])


def first_syntactic_index(infos, start, end):
    for index in range(start, end):
        if non_punct_infos_at(infos, index):
            return index
    return None


def last_syntactic_index(infos, start, end):
    for index in range(end - 1, start - 1, -1):
        if non_punct_infos_at(infos, index):
            return index
    return None


def span_has_subject(infos, start, end):
    for index in range(start, end):
        for info in non_punct_infos_at(infos, index):
            if base.deprel_base(info["deprel"]) in base.SUBJECT_DEPRELS:
                return True
    return False


def has_cop_child(index, children):
    return any(edge["base"] == "cop" for edge in children.get(index, []))


def clause_anchors_in_span(words, infos, start, end):
    children = build_children(infos)
    anchors = []
    for index in range(start, end):
        for info in non_punct_infos_at(infos, index):
            base_deprel = base.deprel_base(info["deprel"])
            upos = info["upos"]
            is_verbal_anchor = upos in {"VERB", "AUX"} and base_deprel in COMPLETENESS_ANCHOR_DEPRELS
            is_copular_anchor = (
                upos in {"ADJ", "ADV", "NOUN", "NUM", "PRON", "PROPN"}
                and base_deprel in COMPLETENESS_ANCHOR_DEPRELS
                and has_cop_child(index, children)
            )
            if is_verbal_anchor or is_copular_anchor:
                anchors.append(
                    {
                        "index": index,
                        "word": words[index]["word"],
                        "text": info["text"],
                        "upos": upos,
                        "deprel": info["deprel"],
                        "base": base_deprel,
                        "head": info.get("head"),
                    }
                )
    return anchors


def head_chain_exits_without_local_independent_anchor(infos, index, start, end):
    seen = set()
    current = index
    while current is not None:
        if current in seen:
            return False
        seen.add(current)
        current_infos = non_punct_infos_at(infos, current)
        if not current_infos:
            return False
        head = current_infos[0].get("head")
        if head is None:
            return False
        if head < start or head >= end:
            return True
        head_roles = {base.deprel_base(info["deprel"]) for info in non_punct_infos_at(infos, head)}
        if head_roles & INDEPENDENT_ANCHOR_DEPRELS:
            return False
        current = head
    return False


def external_edge_roles(infos, index, roles, start, end):
    external_roles = []
    for info in non_punct_infos_at(infos, index):
        role = base.deprel_base(info["deprel"])
        if role not in roles:
            continue
        head = info.get("head")
        if head is None or head < start or head >= end:
            external_roles.append(role)
    return sorted(set(external_roles))


def segment_completeness_cost(words, infos, start, end, args):
    word_count = end - start
    anchors = clause_anchors_in_span(words, infos, start, end)
    independent_anchors = [anchor for anchor in anchors if anchor["base"] in INDEPENDENT_ANCHOR_DEPRELS]
    dependent_anchors = [anchor for anchor in anchors if anchor["base"] in DEPENDENT_ANCHOR_DEPRELS]
    first_index = first_syntactic_index(infos, start, end)
    last_index = last_syntactic_index(infos, start, end)
    first_roles = set()
    last_roles = set()
    cost = 0.0
    reasons = []

    if first_index is not None:
        first_roles = {base.deprel_base(info["deprel"]) for info in non_punct_infos_at(infos, first_index)}
    if last_index is not None:
        last_roles = {base.deprel_base(info["deprel"]) for info in non_punct_infos_at(infos, last_index)}

    if not anchors and word_count >= 6:
        cost += args.completeness_no_predicate_cost
        reasons.append("no_predicate_anchor")
    elif not anchors and word_count >= args.min_words and has_soft_boundary_punctuation(words, infos, end - 1, args):
        cost += args.completeness_no_predicate_cost
        reasons.append("intro_fragment_no_predicate")

    if anchors and dependent_anchors and not independent_anchors:
        cost += args.completeness_subordinate_only_cost
        reasons.append("subordinate_only")

    strong_start_roles = (
        external_edge_roles(infos, first_index, DANGLING_START_DEPRELS, start, end)
        if first_index is not None
        else []
    )
    if strong_start_roles:
        cost += args.completeness_dangling_edge_cost
        reasons.append("dangling_start:" + "+".join(strong_start_roles))

    conditional_start_roles = (
        external_edge_roles(infos, first_index, DANGLING_CONDITIONAL_START_DEPRELS, start, end)
        if first_index is not None
        else []
    )
    if conditional_start_roles and not independent_anchors:
        cost += args.completeness_dangling_edge_cost
        reasons.append("dangling_start_conditional:" + "+".join(conditional_start_roles))

    end_roles = (
        external_edge_roles(infos, last_index, DANGLING_END_DEPRELS, start, end)
        if last_index is not None
        else []
    )
    if end_roles:
        cost += args.completeness_dangling_edge_cost
        reasons.append("dangling_end:" + "+".join(end_roles))

    if last_index is not None and has_soft_boundary_punctuation(words, infos, end - 1, args) and anchors:
        last_anchor = max(anchors, key=lambda anchor: anchor["index"])
        if (
            last_anchor["base"] in DEPENDENT_ANCHOR_DEPRELS
            and head_chain_exits_without_local_independent_anchor(infos, last_anchor["index"], start, end)
        ):
            cost += args.completeness_intro_ending_cost
            reasons.append(f"intro_ending:{last_anchor['base']}")

    evidence = {
        "first_word": words[first_index]["word"] if first_index is not None else "",
        "first_roles": sorted(first_roles),
        "first_external_roles": strong_start_roles + conditional_start_roles,
        "last_word": words[last_index]["word"] if last_index is not None else "",
        "last_roles": sorted(last_roles),
        "last_external_roles": end_roles,
        "anchors": anchors,
        "independent_anchor_count": len(independent_anchors),
        "dependent_anchor_count": len(dependent_anchors),
    }
    return {"cost": cost, "reasons": reasons, "evidence": evidence}


def dependency_boundary_verdict(words, infos, boundary, args):
    reasons = []
    cost = 0.0

    for edge in crossing_edges(words, infos, boundary):
        base_deprel = edge["base"]
        distance = edge["distance"]

        if base_deprel in IGNORED_DEPRELS:
            continue

        if base_deprel in HARD_TIGHT_DEPRELS:
            reasons.append(
                f"forbid:tight:{base_deprel}:{edge['child_word']}->{edge['head_word']}"
            )
            continue

        if base_deprel in LOCAL_CORE_DEPRELS:
            if distance <= args.local_core_distance:
                reasons.append(
                    f"forbid:local_core:{base_deprel}:{edge['child_word']}->{edge['head_word']}:d{distance}"
                )
            else:
                cost += args.far_core_cost
                reasons.append(
                    f"penalize:far_core:{base_deprel}:{edge['child_word']}->{edge['head_word']}:d{distance}"
                )
            continue

        if base_deprel == "cc":
            # A cc crossing is not enough by itself; the stranded-cc check below
            # decides whether the connector was left on the wrong side.
            continue

        if base_deprel == "acl" and distance <= args.local_acl_distance:
            reasons.append(
                f"forbid:local_acl:{edge['deprel']}:{edge['child_word']}->{edge['head_word']}:d{distance}"
            )
            continue

        if base_deprel in CLAUSE_PENALTY:
            penalty = CLAUSE_PENALTY[base_deprel]
            cost += penalty
            reasons.append(
                f"penalize:clause:{base_deprel}:{edge['child_word']}->{edge['head_word']}:{penalty:g}"
            )
            continue

        cost += args.other_dep_cost
        reasons.append(
            f"penalize:other:{base_deprel}:{edge['child_word']}->{edge['head_word']}:{args.other_dep_cost:g}"
        )

    if boundary > 0:
        left_infos = infos[boundary - 1]
        for info in left_infos:
            if base.deprel_base(info["deprel"]) == "cc":
                reasons.append(f"forbid:stranded_cc:{words[boundary - 1]['word']}")

    hard_reasons = [reason for reason in reasons if reason.startswith("forbid:")]
    if hard_reasons:
        return {
            "action": "forbid",
            "cost": float("inf"),
            "reasons": reasons,
        }
    if cost:
        return {
            "action": "penalize",
            "cost": cost,
            "reasons": reasons,
        }
    return {
        "action": "allow",
        "cost": 0.0,
        "reasons": reasons,
    }


def candidate_reason_cost(reasons):
    cost = 0.0
    for reason in reasons:
        if reason == "mark_subordinate_start":
            cost += 120.0
        elif reason == "cc_before_connector":
            cost += 20.0
        elif reason.endswith("_subtree_end"):
            cost += 30.0
        elif reason == "independent_root_start":
            cost -= 100.0
        elif reason == "punctuation":
            cost -= 50.0
    return cost


def grammar_segment_cost(words, infos, candidates, start, end, args):
    segment_words = words[start:end]
    word_count = end - start
    duration = segment_words[-1]["end"] - segment_words[0]["start"]
    cost = 0.0

    cost += abs(duration - args.target_duration) * 1.0
    if duration > args.max_duration:
        cost += 320.0 + (duration - args.max_duration) * 90.0
    if word_count > args.target_words:
        cost += (word_count - args.target_words) * 2.5
    if word_count > args.max_words:
        cost += 320.0 + (word_count - args.max_words) * 70.0
    if word_count < args.min_words:
        cost += 120.0

    completeness = segment_completeness_cost(words, infos, start, end, args)
    cost += completeness["cost"]

    if end < len(words):
        verdict = dependency_boundary_verdict(words, infos, end, args)
        if verdict["action"] == "forbid":
            return float("inf")
        cost += verdict["cost"]
        cost += candidate_reason_cost(candidates.get(end, set()))

    return cost


def record_completeness_stats(stats, completeness):
    if not completeness or completeness["cost"] <= 0:
        return
    stats["completeness_penalty_count"] += 1
    for reason in completeness["reasons"]:
        stats[f"completeness_reason:{reason}"] += 1


def split_unit_words(words, nlp, args, stats):
    duration = words[-1]["end"] - words[0]["start"]
    if len(words) <= args.split_word_threshold and duration <= args.split_duration_threshold:
        return [(0, len(words), "preserved", None)]

    infos = base.parse_unit_words(nlp, words)
    candidates = dependency_candidate_boundaries(words, infos, args)
    stats["raw_dependency_candidates"] += len(candidates)

    safe_candidates = {0: {"unit_start"}, len(words): {"unit_end"}}
    for boundary, reasons in candidates.items():
        verdict = dependency_boundary_verdict(words, infos, boundary, args)
        if verdict["action"] == "forbid":
            stats["dependency_forbidden_candidates"] += 1
            for reason in verdict["reasons"]:
                if reason.startswith("forbid:"):
                    stats[f"forbid_reason:{reason.split(':', 3)[0]}:{reason.split(':', 3)[1]}:{reason.split(':', 3)[2]}"] += 1
            continue
        safe_candidates[boundary] = reasons
        stats["safe_dependency_candidates"] += 1
        for reason in reasons:
            stats[f"candidate_reason:{reason}"] += 1

    if len(safe_candidates) <= 2:
        completeness = segment_completeness_cost(words, infos, 0, len(words), args)
        return [(0, len(words), "dependency_policy_unsplit:no_safe_candidate", completeness)]

    ordered = sorted(safe_candidates)
    n = len(words)
    dp = {0: 0.0}
    back = {}
    for end in ordered[1:]:
        best = None
        best_start = None
        for start in ordered:
            if start >= end or start not in dp:
                continue
            if end != n and end - start < args.min_words:
                continue
            duration = words[end - 1]["end"] - words[start]["start"]
            if end != n and duration > args.max_duration + 8:
                continue
            score = dp[start] + grammar_segment_cost(words, infos, safe_candidates, start, end, args)
            if score == float("inf"):
                continue
            if best is None or score < best:
                best = score
                best_start = start
        if best_start is not None:
            dp[end] = best
            back[end] = best_start

    if n not in back:
        completeness = segment_completeness_cost(words, infos, 0, n, args)
        return [(0, n, "dependency_policy_unsplit:dp_failed", completeness)]

    pieces = []
    cursor = n
    while cursor > 0:
        start = back[cursor]
        if cursor == n:
            reason = "dependency_policy_clause:unit_end"
        else:
            reason = "dependency_policy_clause:" + "+".join(sorted(safe_candidates.get(cursor, [])))
        completeness = segment_completeness_cost(words, infos, start, cursor, args)
        pieces.append((start, cursor, reason, completeness))
        cursor = start
    pieces.reverse()

    if len(pieces) == 1:
        completeness = segment_completeness_cost(words, infos, 0, n, args)
        return [(0, n, "dependency_policy_unsplit:no_better_split", completeness)]
    return pieces


def build_output(data, args):
    units, input_key = base.input_units(data)
    nlp = stanza.Pipeline(
        "en",
        model_dir=args.model_dir,
        processors="tokenize,pos,lemma,depparse",
        use_gpu=False,
        verbose=False,
        download_method=None,
    )

    output_units = []
    stats = Counter()
    split_count = 0
    for unit in units:
        words = unit["words"]
        pieces = split_unit_words(words, nlp, args, stats)
        if len(pieces) > 1:
            split_count += 1
        source_reason = unit.get("boundary_reason") or unit.get("reason") or input_key
        for start, end, reason, completeness in pieces:
            final_reason = source_reason if reason == "preserved" else reason + "+source_" + source_reason
            record_completeness_stats(stats, completeness)
            output_unit = base.make_output_unit(
                len(output_units) + 1,
                words[start:end],
                final_reason,
                args.pre_pad,
                args.post_pad,
            )
            if completeness and args.include_completeness_debug:
                output_unit["completeness_cost"] = round(completeness["cost"], 3)
                output_unit["completeness_reasons"] = completeness["reasons"]
                output_unit["completeness_evidence"] = completeness["evidence"]
            output_units.append(output_unit)

    assigned = sum(unit["word_count"] for unit in output_units)
    input_word_count = sum(unit["word_count"] for unit in units)
    durations = [unit["duration"] for unit in output_units]
    word_counts = [unit["word_count"] for unit in output_units]
    return {
        "metadata": {
            "source": args.input,
            "strategy": "dependency_policy_clause_splitter_test",
            "uses_llm": False,
            "uses_stanza": True,
            "no_lexicon": args.no_lexicon,
            "input_collection": input_key,
            "input_unit_count": len(units),
            "sentence_count": len(output_units),
            "split_unit_count": split_count,
            "word_count": input_word_count,
            "assigned_word_count": assigned,
            "all_words_assigned": assigned == input_word_count,
            "max_duration": max(durations) if durations else 0,
            "max_words": max(word_counts) if word_counts else 0,
            "dependency_policy": {
                "hard_tight_deprels": sorted(HARD_TIGHT_DEPRELS),
                "local_core_deprels": sorted(LOCAL_CORE_DEPRELS),
                "local_core_distance": args.local_core_distance,
                "local_acl_distance": args.local_acl_distance,
                "clause_candidate_deprels": sorted(CLAUSE_CANDIDATE_DEPRELS),
                "clause_penalty": CLAUSE_PENALTY,
            },
            "completeness_policy": {
                "anchor_deprels": sorted(COMPLETENESS_ANCHOR_DEPRELS),
                "independent_anchor_deprels": sorted(INDEPENDENT_ANCHOR_DEPRELS),
                "dependent_anchor_deprels": sorted(DEPENDENT_ANCHOR_DEPRELS),
                "dangling_start_deprels": sorted(DANGLING_START_DEPRELS),
                "dangling_conditional_start_deprels": sorted(DANGLING_CONDITIONAL_START_DEPRELS),
                "dangling_end_deprels": sorted(DANGLING_END_DEPRELS),
                "no_predicate_cost": args.completeness_no_predicate_cost,
                "subordinate_only_cost": args.completeness_subordinate_only_cost,
                "dangling_edge_cost": args.completeness_dangling_edge_cost,
                "intro_ending_cost": args.completeness_intro_ending_cost,
                "punctuation_source": "stanza_punct_role" if args.no_lexicon else "surface_punctuation_chars",
            },
            "completeness_penalty_count": stats.get("completeness_penalty_count", 0),
            "stats": dict(stats),
            "limits": {
                "split_word_threshold": args.split_word_threshold,
                "split_duration_threshold": args.split_duration_threshold,
                "target_duration": args.target_duration,
                "max_duration": args.max_duration,
                "target_words": args.target_words,
                "max_words": args.max_words,
            },
            "padding": {"pre_seconds": args.pre_pad, "post_seconds": args.post_pad},
        },
        "sentences": output_units,
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="coarse_blocks_pure_grammar.json")
    parser.add_argument("--output", default="sentence_units_dependency_policy_test.json")
    parser.add_argument("--model-dir", default="stanza_resources")
    parser.add_argument("--split-word-threshold", type=int, default=30)
    parser.add_argument("--split-duration-threshold", type=float, default=14.0)
    parser.add_argument("--min-words", type=int, default=4)
    parser.add_argument("--target-words", type=int, default=18)
    parser.add_argument("--max-words", type=int, default=34)
    parser.add_argument("--target-duration", type=float, default=6.5)
    parser.add_argument("--max-duration", type=float, default=11.0)
    parser.add_argument("--local-core-distance", type=int, default=10)
    parser.add_argument("--local-acl-distance", type=int, default=5)
    parser.add_argument("--far-core-cost", type=float, default=420.0)
    parser.add_argument("--other-dep-cost", type=float, default=80.0)
    parser.add_argument("--completeness-no-predicate-cost", type=float, default=900.0)
    parser.add_argument("--completeness-subordinate-only-cost", type=float, default=1200.0)
    parser.add_argument("--completeness-dangling-edge-cost", type=float, default=1200.0)
    parser.add_argument("--completeness-intro-ending-cost", type=float, default=1800.0)
    parser.add_argument("--include-punctuation-candidates", action="store_true")
    parser.add_argument("--include-completeness-debug", action="store_true")
    parser.add_argument(
        "--no-lexicon",
        action="store_true",
        help="Avoid surface word/punctuation checks; use only Stanza UPOS/deprel/head roles for grammar decisions.",
    )
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
    print("dependency stats:")
    for key, value in sorted(metadata["stats"].items()):
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
