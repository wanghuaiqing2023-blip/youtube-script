# youtube-script

Local experiments for splitting WhisperX word-level transcripts into sentence-like audio units while preserving every word timestamp.

## Key Files

- `transcribe-whisperx_result.json`: source WhisperX transcript with word timestamps.
- `split_sentences_grammar_coarse.py`: current grammar-first splitter.
- `sentence_units_pure_grammar_fine_30_quality_v9.json`: current candidate output.
- `coarse_blocks_pure_grammar.json`: coarse grammar blocks.
- `verify_coarse_nonoverlap.py`: coverage/non-overlap verifier for coarse blocks.

## Current Splitter

The current baseline is local-only:

- Uses Stanza for grammar parsing.
- Does not use an LLM.
- Preserves original WhisperX words and timestamps.
- Assigns every source word to exactly one output unit.

Example:

```powershell
python -m stanza.download en
python split_sentences_grammar_coarse.py `
  --input transcribe-whisperx_result.json `
  --output sentence_units_pure_grammar_fine_30_quality_v9.json `
  --fine-split-word-threshold 30 `
  --target-words 32 `
  --max-words 58 `
  --target-duration 10 `
  --max-duration 22
```

## Notes

The pure grammar/rule approach is useful as a conservative local baseline, but it is not expected to perfectly solve all long spoken-language blocks. The remaining hard cases are candidates for a cut-point-only LLM experiment.

## LLM Cut-Point Workflow (Index-Annotated Tokens)

To reduce ambiguity for the LLM, you can provide a transcript view where **every token has its absolute word index** (for example `word[123]`).

If you want a **ready-to-send prompt text** directly from `transcribe-whisperx_result.json`, run:

```bash
python build_llm_cutpoint_prompt.py \
  --input transcribe-whisperx_result.json \
  --output llm_cutpoint_prompt.txt \
  --index-style suffix
```

Generate payload:

```bash
python make_llm_cutpoint_payload.py \
  --input transcribe-whisperx_result.json \
  --output llm_cutpoint_payload.json \
  --index-style suffix
```

Then ask the LLM to return only:

- `cut_after_word_indices` (ascending integer indices),
- including the final word index.

Apply cutpoints:

```bash
python apply_llm_cutpoints.py \
  --input transcribe-whisperx_result.json \
  --cutpoints llm_cutpoints_one_shot.json \
  --output sentence_units_llm_one_shot.json
```
