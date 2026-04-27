import argparse
import json
import re
from pathlib import Path

import stanza


TRIM_RE = re.compile(r"^[^\w']+|[^\w']+$")

BAD_START_UPOS = {"ADP", "PART"}
DEPENDENT_START_UPOS = {"SCONJ", "CCONJ"}
BAD_END_WORDS = {
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
    "when",
    "while",
    "where",
    "that",
    "which",
    "who",
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
    "than",
    "like",
    "is",
    "are",
    "was",
    "were",
    "do",
    "does",
    "did",
    "have",
    "has",
    "can",
    "could",
    "would",
    "should",
    "will",
    "just",
    "think",
}


def norm_word(value):
    return TRIM_RE.sub("", value).lower()


def is_lowercase_start(value):
    stripped = value.lstrip('"\'([{')
    return bool(stripped[:1].islower())


def sentence_has_predicate(sentence):
    return any(word.upos in {"VERB", "AUX"} and word.deprel in {"root", "cop", "xcomp", "ccomp", "conj"} for word in sentence.words)


def audit_unit(nlp, unit):
    text = unit["text"]
    doc = nlp(text)
    issues = []
    parsed_sentences = []

    for sentence in doc.sentences:
        words = sentence.words
        parsed_sentences.append(
            {
                "text": sentence.text,
                "tokens": [
                    {
                        "text": word.text,
                        "upos": word.upos,
                        "head": word.head,
                        "deprel": word.deprel,
                    }
                    for word in words
                ],
            }
        )
        if len(words) >= 4 and not sentence_has_predicate(sentence):
            issues.append("sentence_without_predicate")

    if unit["words"]:
        first_text = unit["words"][0]["word"]
        last_text = unit["words"][-1]["word"]
        first_norm = norm_word(first_text)
        last_norm = norm_word(last_text)

        first_parsed = doc.sentences[0].words[0] if doc.sentences and doc.sentences[0].words else None
        if first_parsed:
            if is_lowercase_start(first_text) and first_parsed.upos in BAD_START_UPOS:
                issues.append(f"starts_with_{first_parsed.upos.lower()}")
            if (
                is_lowercase_start(first_text)
                and first_parsed.upos in DEPENDENT_START_UPOS
                and unit["word_count"] > 8
            ):
                issues.append(f"starts_with_dependent_{first_parsed.upos.lower()}")

        if last_norm in BAD_END_WORDS and not last_text.rstrip().endswith((".", "?", "!")):
            issues.append("bad_ending_word")

    if unit["duration"] > 18:
        issues.append("longer_than_18s")
    if unit["word_count"] > 55:
        issues.append("more_than_55_words")

    return {
        "id": unit["id"],
        "start": unit["start"],
        "end": unit["end"],
        "duration": unit["duration"],
        "word_count": unit["word_count"],
        "issues": sorted(set(issues)),
        "text": text,
        "parsed_sentences": parsed_sentences,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="sentence_units_complete.json")
    parser.add_argument("--output", default="stanza_audit_report.json")
    parser.add_argument("--model-dir", default="stanza_resources")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    units = data["sentences"][: args.limit or None]

    nlp = stanza.Pipeline(
        "en",
        model_dir=args.model_dir,
        processors="tokenize,pos,lemma,depparse",
        use_gpu=False,
        verbose=False,
        download_method=None,
    )

    audited = [audit_unit(nlp, unit) for unit in units]
    suspicious = [item for item in audited if item["issues"]]
    report = {
        "input": args.input,
        "audited_count": len(audited),
        "suspicious_count": len(suspicious),
        "suspicious": suspicious,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"audited: {len(audited)}")
    print(f"suspicious: {len(suspicious)}")
    for item in suspicious[:20]:
        print()
        print(
            f"ID {item['id']} duration={item['duration']} words={item['word_count']} issues={','.join(item['issues'])}"
        )
        print(item["text"][:500])


if __name__ == "__main__":
    main()
