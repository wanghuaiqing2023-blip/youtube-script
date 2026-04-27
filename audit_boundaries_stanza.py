import argparse
import json
import re
from pathlib import Path

import stanza


PUNCT_RE = re.compile(r"^\W+$")
IGNORED_DEPRELS = {"punct", "cc", "discourse", "parataxis"}


def stanza_word_count(nlp, text):
    doc = nlp(text)
    return sum(len(sentence.words) for sentence in doc.sentences)


def boundary_crossings(nlp, left_text, right_text):
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
            if word_side != head_side and not PUNCT_RE.match(word.text):
                crossings.append(
                    {
                        "word": word.text,
                        "upos": word.upos,
                        "deprel": word.deprel,
                        "side": word_side,
                        "head": sentence.words[word.head - 1].text,
                        "head_side": head_side,
                    }
                )
        offset += len(sentence.words)

    return crossings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="sentence_units_complete.json")
    parser.add_argument("--output", default="stanza_boundary_audit.json")
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

    suspicious = []
    for left, right in zip(units, units[1:]):
        crossings = boundary_crossings(nlp, left["text"], right["text"])
        if crossings:
            suspicious.append(
                {
                    "left_id": left["id"],
                    "right_id": right["id"],
                    "left_duration": left["duration"],
                    "right_duration": right["duration"],
                    "left_words": left["word_count"],
                    "right_words": right["word_count"],
                    "crossings": crossings,
                    "left_text": left["text"],
                    "right_text": right["text"],
                }
            )

    report = {
        "input": args.input,
        "boundary_count": max(0, len(units) - 1),
        "suspicious_boundary_count": len(suspicious),
        "suspicious": suspicious,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"boundaries: {report['boundary_count']}")
    print(f"suspicious_boundaries: {len(suspicious)}")
    for item in suspicious[:20]:
        print()
        print(f"{item['left_id']} -> {item['right_id']}")
        print("crossings:", item["crossings"][:5])
        print("LEFT:", item["left_text"][:300])
        print("RIGHT:", item["right_text"][:300])


if __name__ == "__main__":
    main()
