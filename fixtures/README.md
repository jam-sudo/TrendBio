# Contract fixtures

This is synthetic data for offline pipeline tests and site development, not real
research or collected source responses. All evidence links use `example.org`;
names, identifiers, descriptions, signals, and model provenance are illustrative.
No network requests or LLM calls generate this dataset.

- `data/computational/days/`: October 30–November 1, 2026, five ranked topics each.
  October 30 is backfilled and records `claude-haiku-5-5`; the other days record
  `claude-opus-5-5`.
- `data/computational/topics/`: five topics, with all four evidence types.
  `protein-design-binders-a1b2` has 70 consecutive history entries from August 24
  to November 1, including unranked days and a return to the rankings. Its ranks
  on the three day pages are 1, 1, and 2. Empty windows have zero counts.
- `data/computational/items/YYYY/MM/`: 40 items across all five sources. Each
  topic has a linked preprint/published pair counted once as published. Paths use
  `first_seen`, with both `:` and `/` in the ID replaced by `_`.
- `notes/`: one editor note and one deliberate orphan, `nonexistent-topic-zzzz`.

Centroids are synthetic five-dimensional unit vectors, not scientific embeddings.
Rise values illustrate ranking changes; they are not outputs of the future scoring
stage. Component weights and yesterday penalties use `config/scoring.yaml`.
Embedding shards and GitHub star histories are left to the store task (B3).

From the repository root, with the Python dependencies installed:

```sh
python -m tests.fixtures_build
python -m pytest -q
```

Regeneration overwrites this dataset's JSON and note files deterministically.
JSON uses UTF-8, two-space indentation, sorted keys, and a trailing newline.
The tests validate every item/topic/day, cross-references, filenames, histories,
rank snapshots, serialization, and regeneration. Site development should use
`TRENDBIO_DATA_ROOT=../fixtures/data` and `TRENDBIO_NOTES_ROOT=../fixtures/notes`.
