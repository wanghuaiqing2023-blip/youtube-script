# youtube-script

Local experiments for splitting WhisperX word-level transcripts into sentence-like audio units while preserving every word timestamp.

The current direction is local-only and grammar-first: use Stanza dependency parsing plus structural rules to split long compound sentences into clause-level units without rewriting the transcript and without relying on an LLM.

## Key Files

- `transcribe-whisperx_result.json`: source WhisperX transcript with word timestamps.
- `export_coarse_blocks.py`: first-stage exporter that creates complete grammar-safe coarse blocks.
- `coarse_blocks_pure_grammar.json`: first-stage coarse block output.
- `split_compound_clauses_dependency_policy.py`: second-stage dependency-policy clause splitter.
- `split_compound_clauses_structural_policy.py`: structural-policy test splitter that avoids fixed distance thresholds.
- `sentence_units_structural_policy_test.json`: latest structural-policy test output.
- `GRAMMAR_DEPENDENCY_CLAUSE_SPLITTING.md`: design notes and lessons learned for grammar-based clause splitting.
- `audit_lexical_fallback_ablation.py`: audit script for measuring how much lexical fallback had been doing.

## Current Workflow

The current workflow has two stages.

Stage 1 exports coarse grammar-safe blocks:

```powershell
.\.venv\Scripts\python.exe export_coarse_blocks.py `
  --input transcribe-whisperx_result.json `
  --model-dir stanza_resources `
  --output coarse_blocks_pure_grammar.json
```

Stage 2 splits long coarse blocks into clause-level units:

```powershell
.\.venv\Scripts\python.exe split_compound_clauses_structural_policy.py `
  --input coarse_blocks_pure_grammar.json `
  --output sentence_units_structural_policy_test.json `
  --model-dir stanza_resources
```

The structural policy:

- Uses Stanza for grammar parsing.
- Does not use an LLM.
- Preserves original WhisperX words and timestamps.
- Assigns every source word to exactly one output unit.
- Uses dependency roles such as `root`, `cc`, `mark`, `acl`, `nsubj`, `obj`, and `xcomp`.
- Uses structural closure checks instead of fixed word-distance thresholds.

## Notes

The key design idea is to avoid word-list rules like "because cannot start" or "of cannot end". Prefer grammar-role rules:

- Boundary safety: do not split tight dependency structures.
- Segment completeness: check whether a span closes internally through its head chain.
- Candidate generation: use dependency structure, clause subtrees, and independent roots.
- Global choice: use dynamic programming to prefer complete segments over shorter but broken ones.

See `GRAMMAR_DEPENDENCY_CLAUSE_SPLITTING.md` for the full strategy summary.
