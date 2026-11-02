# Source response fixtures

Recorded from public APIs/feeds on 2026-11-02. Each fixture has at most four
records; unused records and fields were removed deliberately. Pagination totals
in bioRxiv, arXiv and PubMed search were adjusted to the retained records.

- `biorxiv.json`: `https://api.biorxiv.org/details/biorxiv/2025-01-06/2025-01-06/0`, four selected records covering category/keyword inclusion and exclusion.
- `arxiv.xml`: `https://export.arxiv.org/api/query?search_query=cat:cs.LG+AND+all:single-cell&max_results=3` (LapDDPM) plus `https://export.arxiv.org/api/query?id_list=1706.03762` (Attention Is All You Need); two records combined under one feed envelope.
- `pubmed_search.json`: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=scanpy[Title]&retmode=json&retmax=2`.
- `pubmed.xml`: efetch for the two returned PMIDs, `38668977,32632608`; reference lists, affiliations and author identifiers removed.
- `github.json`, `github_releases.json`: `https://api.github.com/repos/scverse/scanpy` and its `/releases?per_page=3` endpoint; account details removed except the organization login.
- `rss.xml`: first two entries from `https://www.insitro.com/feed/` plus the first non-biological entry from `https://blogs.nvidia.com/feed/`; full HTML bodies removed, descriptions retained.

All unit HTTP is mocked by respx. Edge cases and star timestamps are constructed
in tests, not claimed as recorded data: GitHub's live stargazers endpoint returned
401. GitHub now documents restrictions on access to stargazer lists, so live
star-history backfill requires an authorized token and may fail for public repos.
