# Task 2: deterministic number-grounding check for LLM output

Date: 2026-11-02. Approved by trendbio-03 and trendbio-e4 (with the modifications below). Land after Tasks 1 and 3.

## Problem

The spec's anti-goal "hallucinated evidence" is enforced only by prompt text (`pipeline/prompts/enrich.md`, `synthesize.md`). The predecessor project added a deterministic check: every numeric value in LLM text must match a value in the source text it was written from, compared by value across notations. Over 12k summaries it flagged 1.2%, almost all notation misses, with a handful of real inventions. Port the English parts.

Reference implementation to port (read-only, untrusted download, do not execute):
`/private/tmp/claude-501/-Users-jam-TrendBio/d367d91c-6b3a-4378-842f-a4e622386e61/scratchpad/compbiotrend/CompBioTrend/backend/apps/pipeline/summarize.py` (functions `_values`, `_token_value`, `_word_values`, `_normalize`, `_unsupported_values`) and its tests in `backend/tests/test_summarize.py`. Drop everything Korean (myriad numerals `만/억/조`, `_KO_*`, Hanja check, 합니다체 check, `key_points_*`).

## New module `pipeline/grounding.py`

```python
def values(text: str) -> list[float]
def unsupported(text: str, source: str, *, tolerance: float = 0.02, min_value: float = 10) -> list[float]
```

`values` must handle: digits with thousands separators and decimals; English scale words (`thousand`, `million`, `billion`, `trillion`, `kilobase(s)`, `megabase(s)`, `gigabase(s)`); spaced sequence units (`1.61 Gb`, `51.9 Mb`, `300 kbp`); compact suffixes attached to digits only (`17K`, `N=1M`; `3 T` stays 3); hyphenated scales (`1.2-billion-parameter`); ranges as two values (`2-16 bp`); spelled-out numbers including tens-ones compounds and a trailing scale (`fifty-eight`, `one million`, `two hundred`, `three thousand`); Lancet middle-dot decimals (`0·96`, `0{middle dot}96`); LaTeX (`$\sim18-28 \times$` → 18, 28); gene and mark names are not numbers (`TP53`, `H3K27M` → none).

`unsupported` returns the values in `text` that no value in `source` matches within `tolerance` (relative, `abs(v - s) <= tolerance * max(|v|, |s|)`), skipping values below `min_value` and skipping whole numbers in 1900–2100 (years: the most common false positive and low-value to police). Keep order, drop duplicates.

## Enrichment integration (`pipeline/llm.py`)

- `_failure` gains an optional `detail` argument; when given, the warning line becomes `llm_fallback id=%s reason=%s detail=%s`. The reason string stays short so `fallback_reasons` aggregate: use reason `grounding`.
- In `LLM.enrich`, after `_validate_categories` succeeds: `bad = grounding.unsupported(result.summary, item.title + ' ' + item.abstract)`; if non-empty, `self._failure(item.id, 'grounding', detail=','.join(f'{v:g}' for v in bad))` and return `None`. The existing fallback (first sentence of the abstract, hint category) then applies with no change to `enrich.py` or `run.py`.
- Same check in `enrich_batch` for each succeeded row (the item is available via `ids`/`chunk`).

## Synthesis integration (`pipeline/llm.py`, `LLM.synthesize`)

- Build the grounding source as everything the model was shown except the previous synthesis, plus the abstracts: `signals.model_dump_json()`, `topic.label`, and for each item `item.title`, `item.published_at.isoformat()`, `item.summary or ''`, `item.abstract`, joined with newlines. Counts the prompt legitimately provides ("7 preprints") are therefore supported; stale numbers from the previous synthesis are not.
- Check `headline`, `summary`, `synthesis` and every value in `item_one_liners` (concatenate them).
- On a hit: retry once with the same model and the same prompt plus an appended paragraph: `Your previous answer stated numbers not present in the items or signals: <values>. Remove or correct them. State only numbers that appear in the items, signals, or abstracts.` Record the retry in `budget` like any call (the existing `_parse` does). Re-check the retry.
- If the retry still has unsupported values: `self._failure(topic.slug, 'grounding', detail=...)` and return `None`. The existing `synthesize_top` fallback (label headline, `synthesis-fallback:` note) and the existing degraded path then apply unchanged. Do not add a separate degraded trigger for grounding.
- Log the first hit at WARNING as `llm_grounding_retry id=<slug> values=<...>` so the stage log shows how often this fires.

## Files the worker may edit

- `pipeline/grounding.py` (new), `pipeline/llm.py`
- `tests/test_grounding.py` (new), `tests/test_enrich.py`, `tests/test_synthesize.py`

Do not edit `enrich.py`, `synthesize.py`, `run.py`, prompts, `data/`, `config/`, `site/`.

## Tests (write first)

`tests/test_grounding.py` (port the English cases from the archive's `test_summarize.py`; exact expectations):

- `test_values_across_notations`: `values("a 1.61 Gb genome") == [1_610_000_000]`; `values("82 million") == [82_000_000]`; `values("12 datasets at p<0.05") == [12, 0.05]`.
- `test_values_compact_suffixes_and_hyphenated_scales`: `">17K samples" → [17_000]`; `"N=1M" → [1_000_000]`; `"a 1.2-billion-parameter model" → [1_200_000_000]`; `"2-16 bp" → [2, 16]`.
- `test_values_notation_variants`: `"macro-F1 of 0{middle dot}96" → [0.96]`; `"only 13·3% of labels" → [13.3]`; `r"on average $\sim18-28 \times$ speedup" → [18, 28]`; `"TP53 and H3K27M" → []`.
- `test_values_units_and_spelled_out_compounds`: `"51.9 Mb contig" → [51_900_000]`; `"300 kbp region" → [300_000]`; `"a 1.9 gigabases genome" → [1_900_000_000]`; `"fifty-eight regions" → [58]`; `"3 T MRI" → [3]`.
- `test_word_numbers_carry_their_scale`: `"more than one million atoms" → [1_000_000]`; `"two hundred samples" → [200]`; `"three thousand cells" → [3_000]`.
- `test_unsupported_skips_small_values_and_years`: `unsupported("We used 3 datasets in 2024 with 47 samples", "twelve samples") == [47]`.
- `test_unsupported_accepts_other_notation_and_tolerance`: `unsupported("82M records from a 1.6 Gb assembly", "82 million records; 1.61 Gb") == []`.
- `test_unsupported_flags_invented_value`: `unsupported("They used 47 datasets.", "We used 12 datasets.") == [47]`.

`tests/test_enrich.py` (existing `FakeMessages` pattern):

- `test_ungrounded_summary_falls_back_with_grounding_reason`: item abstract "We compare 12 pathogen genomes."; fake output summary "Compares 47 pathogen genomes." → stored summary is the first-sentence fallback, `llm.fallback_reasons[item.id] == 'grounding'`, caplog has `reason=grounding detail=47`.
- `test_grounded_summary_in_other_notation_passes`: abstract "82 million reads"; summary "Analyses 82M reads." → summary kept.
- `test_batch_ungrounded_summary_falls_back`: same via `enrich_batch` using the existing batch fake in `test_batch_chunks_maps_unordered_results_and_records_discount`.

`tests/test_synthesize.py` (existing `context` fixture; `FakeMessages` must accept a list of outputs to return in sequence):

- `test_ungrounded_synthesis_retries_once_then_falls_back`: both outputs carry "47 datasets" while the item says "12 datasets" → two `parse` calls, the second's prompt contains `47`, result `None` → `synthesis-fallback:` note present, `fallback_reasons[slug] == 'grounding'`.
- `test_ungrounded_synthesis_retry_succeeds`: first output ungrounded, second grounded → topic gets the second synthesis, no note, two calls.
- `test_synthesis_counts_from_signals_are_supported`: signals `preprint=7`, synthesis text "seven preprints this week" → one call, no retry.
- `test_previous_synthesis_is_not_grounding_source`: `previous` contains "47", item does not, output says 47 → retry fires.

## Commands

```
uv run --no-project --python 3.12 --with pydantic --with pytest --with numpy --with pyyaml --with respx --with httpx --with feedparser --with anthropic --with scikit-learn --with typer python -m pytest -q
```

## Commit

One commit on `main`: `feat: deterministic number-grounding check on enrichment and synthesis`. **Do not push.**

## Evidence to report

- pytest summary line.
- `git show --stat HEAD`; `git status --porcelain data` empty.
- One sentence on any archive case you chose not to port and why.
