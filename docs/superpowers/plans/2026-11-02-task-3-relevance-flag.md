# Task 3: relevance flag in enrichment

Date: 2026-11-02. Approved by trendbio-03 and trendbio-e4. Land after Task 1 and before the October re-backfill (the re-run re-enriches every item, so the flag will be populated for free).

## Problem

TrendBio collects arXiv `q-bio.*` unfiltered and PubMed broadly. Of 548 October arXiv items, 104 are `cs.LG` primary and 16 `cs.CV`; titles like "Automatic Construction of Strong Simple Baselines" and "Do Language Models Know What Compelling Scientific Evidence Looks Like?" passed the keyword filter. PubMed contributes 3,407 of 5,862 October items, many general-biomedicine. These items join clusters and count toward every signal. The predecessor project hit the same problem and solved it by asking two questions in the labelling call: is it about biology, and is the main contribution computational.

## Change

Add one boolean to the existing Haiku enrichment call. Same call, no extra cost.

### `pipeline/llm.py`

- `Enrichment` gains `relevant: bool`. (`_output_model` inherits it; the batch schema is derived from it, so `enrich_batch` picks it up automatically.)

### `pipeline/prompts/enrich.md`

Add a `relevant` field to the instructions, worded as:

> relevant: true only when the item is about living systems or biomedicine AND its main contribution is computational: a method, algorithm, statistical or machine-learning model, software tool, database or resource, benchmark, simulation, or a study whose primary activity is large-scale computational analysis of biological data. false for general machine-learning, computer-vision, NLP, robotics or benchmark work with no biological question, even if cross-listed in a biology category; and false for wet-lab, clinical, epidemiological or field studies whose computation is routine statistics or standard bioinformatics used as supporting analysis. For code and industry items, true when they concern computational biology or bioinformatics.

Keep the rest of the prompt as it is; still require exactly one primary category even when `relevant` is false.

### `pipeline/models.py`

- `Item` gains `relevant: bool = True`. Existing item files without the field load as relevant (the fixture data and any pre-existing items).

### `pipeline/enrich.py`

- In `enrich_items`, after a successful result set `item.relevant = result.relevant`. The fallback `Enrichment(...)` built on LLM failure sets `relevant=True` (an unanswered question must not drop a paper).
- Return the number of items marked irrelevant so `run.py` can log it: change the return to `tuple[list[Item], list[str], int]` and update the two call sites (`run.py` daily enrich stage; check `tests/test_enrich.py` callers).

### `pipeline/run.py`

- Daily enrich stage: `counts['irrelevant'] = <count from enrich_items>`.
- Backfill `enrich_batch` loop: set `item.relevant = result.relevant` for successes and `relevant=True` in the fallback `Enrichment(...)`; add `counts['irrelevant']` to the `enrich_batch` stage.
- Embed stage: only embed items with `item.relevant` (`window = [item for item in window if item.relevant]` before computing `missing`). Irrelevant items keep their file but never get an embedding or a cluster.
- Cluster stage already works on `window`, so irrelevant items are excluded from clustering, from `corpus_titles`, and therefore from `signals_for`, `volume` and `rise`. Verify nothing else reads `store.items_between` for signals (grep; `_related` and `resynthesize` work from topics, fine).
- Leave the backfill `enrich_batch` embedding as is (it embeds every chunk item; wasteful but harmless, and changing it would complicate the chunk loop). Add a one-line comment saying so.

### Site

No change: irrelevant items never appear in a topic's `item_ids`. Do not edit `site/`.

## Files the worker may edit

- `pipeline/llm.py`, `pipeline/prompts/enrich.md`, `pipeline/models.py`, `pipeline/enrich.py`, `pipeline/run.py`
- `tests/test_enrich.py`, `tests/test_run.py`, `tests/test_models.py`
- Any test that constructs `Enrichment(...)` without `relevant` must add `relevant=True` (grep `Enrichment(` under `tests/`).

Do not edit `data/`, `config/`, `site/`, `pipeline/cluster.py`, `pipeline/score.py`.

## Tests (write first)

`tests/test_enrich.py`:

- `test_irrelevant_item_keeps_categories_and_is_flagged`: fake output `{summary, primary='ml-ai', secondary=[], relevant=False}` → stored item has `relevant is False`, `primary_category == 'ml-ai'`, `summary` set; `enrich_items` returns irrelevant count 1.
- `test_fallback_marks_item_relevant`: refusal path → `item.relevant is True`.
- `test_enrich_prompt_defines_relevance`: `enrich.md` contains `relevant:` and the phrase `main contribution is computational`.

`tests/test_models.py`:

- `test_item_without_relevant_field_loads_as_relevant`: `Item.model_validate_json` on a JSON without `relevant` → `True`.

`tests/test_run.py` (extend `FakeLLM` with a settable `irrelevant_ids: set[str]`, returning `relevant=False` for those ids in both `enrich` and `enrich_batch`):

- `test_irrelevant_items_are_excluded_from_clustering_and_signals`: run a day where one new item is irrelevant → it is in no topic's `item_ids`, has no embedding (`store.get_embeddings([id])` raises `KeyError`), its file exists with `relevant: false`, and the sum of `count_7d` over topics does not include it.
- `test_enrich_stage_logs_irrelevant_count`: caplog `stage=enrich event=end` line contains `irrelevant=1`.
- `test_backfill_enrich_batch_sets_relevance_and_logs_count`: via `run_backfill`, an item in `irrelevant_ids` ends with `relevant: false` and the `enrich_batch` stage line contains `irrelevant=1`.

## Commands

```
uv run --no-project --python 3.12 --with pydantic --with pytest --with numpy --with pyyaml --with respx --with httpx --with feedparser --with anthropic --with scikit-learn --with typer python -m pytest -q
```

All existing tests plus the new ones must pass. No network in tests.

## Commit

One commit on `main`: `feat: relevance flag in enrichment; irrelevant items excluded from clustering and signals`. **Do not push.**

## Evidence to report

- pytest summary line.
- The final `relevant` paragraph of `enrich.md`.
- `git show --stat HEAD`; `git status --porcelain data` empty.
