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
