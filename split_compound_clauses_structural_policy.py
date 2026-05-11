import argparse
import json
from pathlib import Path

import split_compound_clauses_dependency_policy as dep


CORE_CLAUSE_DEPRELS = {"ccomp", "csubj"}
CORE_ARGUMENT_DEPRELS = {"nsubj", "obj", "iobj", "xcomp"}
NOMINAL_UPOS = {"NOUN", "PROPN", "PRON"}


def first_content_info(infos, index):
    items = dep.non_punct_infos_at(infos, index)
    return items[0] if items else None


def upos_at(infos, index):
    info = first_content_info(infos, index)
    return info["upos"] if info else ""


def side_span_for_boundary(boundary, side, word_count):
    if side == "left":
        return 0, boundary
    return boundary, word_count


def edge_child_side_is_internally_closed(words, infos, edge, boundary):
    start, end = side_span_for_boundary(boundary, edge["child_side"], len(words))
    return not dep.head_chain_exits_without_local_independent_anchor(
        infos,
        edge["child"],
        start,
        end,
    )


def structural_dependency_boundary_verdict(words, infos, boundary, args):
    reasons = []
    cost = 0.0

    for edge in dep.crossing_edges(words, infos, boundary):
        base_deprel = edge["base"]

        if base_deprel in dep.IGNORED_DEPRELS:
            continue

        if base_deprel in dep.HARD_TIGHT_DEPRELS:
            reasons.append(
                f"forbid:tight:{base_deprel}:{edge['child_word']}->{edge['head_word']}"
            )
            continue

        if base_deprel == "acl" and upos_at(infos, edge["head"]) in NOMINAL_UPOS:
            reasons.append(
                f"forbid:nominal_acl:{edge['deprel']}:{edge['child_word']}->{edge['head_word']}"
            )
            continue

        if base_deprel in CORE_ARGUMENT_DEPRELS:
            reasons.append(
                f"forbid:core_argument:{base_deprel}:{edge['child_word']}->{edge['head_word']}"
            )
            continue

        if base_deprel in CORE_CLAUSE_DEPRELS:
            if edge_child_side_is_internally_closed(words, infos, edge, boundary):
                cost += args.structural_core_clause_cost
                reasons.append(
                    f"penalize:closed_core_clause:{base_deprel}:{edge['child_word']}->{edge['head_word']}:{args.structural_core_clause_cost:g}"
                )
            else:
                reasons.append(
                    f"forbid:open_core_clause:{base_deprel}:{edge['child_word']}->{edge['head_word']}"
                )
            continue

        if base_deprel == "cc":
            continue

        if base_deprel in dep.CLAUSE_PENALTY:
            penalty = dep.CLAUSE_PENALTY[base_deprel]
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
        for info in infos[boundary - 1]:
            if dep.base.deprel_base(info["deprel"]) == "cc":
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


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="coarse_blocks_pure_grammar.json")
    parser.add_argument("--output", default="sentence_units_structural_policy_test.json")
    parser.add_argument("--model-dir", default="stanza_resources")
    parser.add_argument("--split-word-threshold", type=int, default=30)
    parser.add_argument("--split-duration-threshold", type=float, default=14.0)
    parser.add_argument("--min-words", type=int, default=4)
    parser.add_argument("--target-words", type=int, default=18)
    parser.add_argument("--max-words", type=int, default=34)
    parser.add_argument("--target-duration", type=float, default=6.5)
    parser.add_argument("--max-duration", type=float, default=11.0)
    parser.add_argument("--other-dep-cost", type=float, default=80.0)
    parser.add_argument("--structural-core-clause-cost", type=float, default=360.0)
    parser.add_argument("--completeness-no-predicate-cost", type=float, default=900.0)
    parser.add_argument("--completeness-subordinate-only-cost", type=float, default=1200.0)
    parser.add_argument("--completeness-dangling-edge-cost", type=float, default=1200.0)
    parser.add_argument("--completeness-intro-ending-cost", type=float, default=1800.0)
    parser.add_argument("--include-punctuation-candidates", action="store_true")
    parser.add_argument("--include-completeness-debug", action="store_true")
    parser.add_argument(
        "--allow-surface-punctuation",
        action="store_false",
        dest="no_lexicon",
        help="Allow surface punctuation character checks. By default this structural test uses no-lexicon mode.",
    )
    parser.add_argument("--pre-pad", type=float, default=0.25)
    parser.add_argument("--post-pad", type=float, default=0.35)
    parser.set_defaults(no_lexicon=True)
    args = parser.parse_args()

    # Compatibility attributes for dep.build_output metadata. They are not used
    # by this structural boundary policy.
    args.local_core_distance = None
    args.local_acl_distance = None
    args.far_core_cost = None
    return args


def main():
    args = parse_args()
    dep.dependency_boundary_verdict = structural_dependency_boundary_verdict
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = dep.build_output(data, args)
    metadata = output["metadata"]
    metadata["strategy"] = "structural_dependency_policy_clause_splitter_test"
    metadata["structural_policy"] = {
        "uses_fixed_distance_thresholds": False,
        "core_argument_deprels": sorted(CORE_ARGUMENT_DEPRELS),
        "core_clause_deprels": sorted(CORE_CLAUSE_DEPRELS),
        "nominal_upos_for_acl": sorted(NOMINAL_UPOS),
        "core_argument_crossing": "forbid",
        "nominal_acl_crossing": "forbid",
        "core_clause_crossing": "penalize_if_child_side_head_chain_closes_inside_span_else_forbid",
        "structural_core_clause_cost": args.structural_core_clause_cost,
    }
    metadata["dependency_policy"]["local_core_distance"] = None
    metadata["dependency_policy"]["local_acl_distance"] = None
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
