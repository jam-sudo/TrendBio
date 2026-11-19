# TrendBio science expansion plan

English · [한국어](science-expansion-plan.ko.md)

Reviewed November 19, 2026. CompBio, All Biology (beta) and Physics are public. Mathematics and Statistics, Earth and Environment, and Chemistry are private pilots. Both website languages show the same research, scoring and evidence. Readers can switch languages on any date or topic. We will set the total monthly model budget after measuring pilot costs across several dates.

## What the pilots established

| Field | Findings | Publication decision |
|---|---|---|
| Mathematics and Statistics | For November 19, 382 papers produced 24 initial topics, one under a single-question screen, and six after allowing a candidate to split. The last approach recovered all three designated zero-sum subsequence papers and three of four time-varying forecasting papers. The selected structure-preserving finite-element and neural PDE papers still failed to form their intended groups. | Keep the pilot private. In a separate week, only one of the top five and one of the bottom four passed both grouping and summary review. Errors included describing numerical evidence as a proof and attributing the same guarantee to different papers. [November 19 review](expansion-measurements/2026-11-19/math-review.ko.md) · [Held-out review](expansion-measurements/2026-11-19/heldout-review.ko.md) |
| Earth and Environment | All 142 articles listed in four weeks of tables of contents from five Copernicus journals were collected. The November 4 run grouped three comparable ocean-observation papers. Its statement about lack of common raw data exceeded the evidence. On November 19, three surface-ozone papers reached one seven-day candidate and the editorial check split them two plus one. With a 28-day window the papers reached three separate candidates. | Keep the pilot private. Check summary support and recovery of known observational groups. Add publishers and environmental and conservation journals to measure coverage beyond the five titles. [Ozone evidence by window](expansion-measurements/2026-11-19/earth-ozone-windows.json) · [Pilot review](expansion-measurements/2026-11-19/earth-run.json) |
| Chemistry | The pilot found 179 dated papers with abstracts and a current CC BY license for the version of record in five journals. On November 4 it collected 48 papers. Neither of the two candidates supported a shared research question across three papers. | Keep the pilot private. Measure analytical chemistry coverage and the share of preprints with verifiable reuse terms. [Sources, licenses and versions](expansion-measurements/2026-11-19/chemistry-rights-versions.json) |
| Humanities and Arts | Of 57 records, 43 chapters linked to a book in the sample. Requiring a title and abstract and counting a book once left 12 works. The only 28-day group combined Iberian rock art, an Italian landscape survey and dating of construction in Nicaragua. Each weekly run produced zero groups. | Defer daily and monthly publication. Sample independent scholarly books, regional-language publishers and work outside archaeology. [Evidence and 28-day comparison](expansion-measurements/2026-11-19/windows-humanities-arts.json) |

November 19 was the calibration date. Three unrelated mathematics groups originally ranked 20, 23 and 24 were excluded. Two exclusions had inaccurate evidence quotations. On November 4, rechecking four candidates with quotation errors produced valid decisions for all 73 candidates and preserved the nine selected topics. The held-out results above govern the publication decision. [Independent editorial review](expansion-measurements/2026-11-19/heldout-review.ko.md)

### Measured model costs

The November 4 runs started from an empty store and processed seven days. The November 5 runs restored the previous day's papers, embeddings, editorial decisions and usage ledger. Each amount is the difference in recorded usage across that run. These dates were replayed in order on November 19. Historical metadata versions and actual daily uptime require separate evidence.

| Private edition | Nov 4 papers / ranked topics | Initial cost | Nov 5 new papers / ranked topics | Incremental cost |
|---|---:|---:|---:|---:|
| Mathematics and Statistics | 559 / 9 | $0.3437 | 65 / 7 | $0.1990 |
| Earth and Environment | 33 / 1 | $0.0349 | 7 / 0 | $0.0020 |
| Chemistry | 48 / 0 | $0.0117 | 8 / 0 | $0.0027 |

The nine additional experiments cost $0.7751. The November 19 mathematics calibration, including its initial run, summary recovery and single-question review, cost $1.0275. With the partition checks, the same-day experimental totals reached $1.2022 for mathematics and $0.1727 for Earth. Published editions recorded $5.19 for 14 CompBio dates, $0.67 for two Physics dates and $0.46 for one All Biology date. Measure dates with many and few new summaries before projecting recurring costs. The $55 setting is a per-field model-switch threshold. The aggregate monthly budget is still open. [Pilot runs and ledgers](expansion-measurements/2026-11-19/pilot-comparison.json) · [Existing editions](expansion-measurements/2026-11-19/existing-costs.json)

### Independent checks on collection

- **Mathematics and Earth.** For November 4 the store contained all 21 sampled papers from the independent arXiv monthly listing and all 33 articles from the Earth publishers’ contents pages. One and three papers respectively supported ranked topics. Fourteen precisely dated numerical-analysis and statistics journal articles had no matching title in the same 28 days of new arXiv submissions. Journal publication lags limit what this comparison can establish. All eight number-theory journal records had only year or month precision. [External journal check](expansion-measurements/2026-11-19/math-external-journals.json)
- **Chemistry.** The 179 licensed papers comprised 19 organic, 27 inorganic, 26 physical, 28 analytical and 79 general-journal papers. The production embedding model yielded 3, 2, 3 and 3 weekly candidates, or 19 across 28 days. Europe PMC returned 726 DOIs for the same five ISSNs in the November 4 window. It dated 719 to November 1. Of the 48 eligible Crossref articles, 33 overlapped. Index dates, abstract availability and licenses affect those denominators. [Licensed sample](expansion-measurements/2026-11-19/windows-chemistry-licensed.json) · [November comparison](expansion-measurements/2026-11-19/pilot-comparison.json)
- **ChemRxiv.** Its 1,502 DOIs represented 1,381 works and included 1,201 first versions. Of those DOI records, 1,479 provided abstracts, zero provided a license URL in Crossref, and four sampled publisher pages returned HTTP 403 to automated retrieval. Thirty-four version relations led to 31 journal DOIs. Use ChemRxiv to check bibliographic links and versions while rights remain unresolved. [Version inventory](expansion-measurements/2026-11-19/chemistry-rights-versions.json) · [Publisher migration FAQ](https://connect.acspubs.org/chemrxiv-migration-FAQ)
- **Computing.** Searching CHI 2026 by proceedings and extended-abstract ISBN returned zero child papers. Matching ACM records by proceedings DOI and title recovered 1,702 full papers and 1,005 extended abstracts, all dated April 13. OSDI listed 137 presentations. Matching title and first-author surname located an arXiv version for two of six sampled papers from each venue. SODA 2025 indexed 192 book chapters under its ISBN, with month-level dates and no abstracts. Its first five titles matched the publisher's program. Track conference dates separately from publication dates. [Conference samples](expansion-measurements/2026-11-19/computing-conferences.json) · [SODA contents](https://epubs.siam.org/doi/10.1137/1.9781611978322.fm)
- **Economics, psychology and agriculture.** RePEc connects working paper and journal versions of the same work. The second Europe PMC query for *Psychological Science* recovered all three expected records, while PubMed returned seven papers with abstracts for its own publication-date query. Of four Brazilian agriculture records checked against the publisher, three provided a year and one request failed. Record retrieval failures separately from incomplete dates or missing coverage. [Economics version example](https://ideas.repec.org/p/nbr/nberwo/4509.html) · [Psychology comparison](expansion-measurements/2026-11-19/psychology-reference.json) · [Regional agriculture](expansion-measurements/2026-11-19/regional-agriculture.json)

The four non-overlapping weeks from October 22 through November 18 covered 47 combinations of sources and publication types. The counts below describe the chosen sample. A source can be represented in multiple combinations.

| Field | Source/type combinations | Precisely dated | With abstract | Next independent sample |
|---|---:|---:|---:|---|
| Chemistry | 7 | 977 | 918 | Publisher contents across four branches |
| Earth and Environment | 7 | 269 | 260 | Other publishers, environmental and conservation journals |
| Computing and Information | 4 | 19 | 13 | Theory, systems and HCI conferences, information-science journals |
| Engineering | 4 | 10 | 10 | Early-access and conference records, since 403 of 411 new registrations lacked a complete date |
| Agriculture, Fisheries, Veterinary and Food | 6 | 69 | 28 | Crops, forests, fisheries, food and regional languages. All 69 dated records came from veterinary journals |
| Medicine and Health | 3 | 468 | 158 | Study design, participants, uncertainty and correction records. Six of ten independent PubMed records had an abstract |
| Social Sciences | 9 | 41 | 35 | Working-paper versions and psychological studies across indexes |
| Humanities and Arts | 7 | 57 | 26 | Journals outside archaeology, regional-language books and parent–chapter links |

With identical embeddings and a three-paper minimum, the broader chemistry sample produced 28, 33, 32 and 30 weekly candidates. Medicine and Health produced 10, 6, 1 and 8. Computing and Engineering produced zero each week, Agriculture one in the last week, and Social Sciences one in each of the first two weeks. Mathematics produced 55, 72, 55 and 56 weekly groups from 1,971 papers, or 284 groups over 28 days. The longer Earth window added 38 previously ungrouped papers and lost six previously grouped ones. These counts precede editorial review. [Mathematics windows](expansion-measurements/2026-11-19/windows-math.json) · [Earth windows](expansion-measurements/2026-11-19/windows-earth-environment.json) · [Other fields](expansion-measurements/2026-11-19/windows-other-fields.json)

## Reader editions and rollout order

| Stage | Scope | Evidence required for the next decision |
|---|---|---|
| 0 · Public | CompBio, All Biology beta and Physics | Track the two biology audiences and their shared papers for 14 live dates. Physics currently covers quantum, optics, mesoscopic/nanoscale physics and cosmology. Sample stellar and galactic observations first, then gravity, particle and nuclear physics, fluids and plasmas, and statistical physics. |
| 1 · Private mathematics pilot | Number theory, numerical analysis and statistical methodology (`math.NT`, `math.NA`, `stat.ME`) | Verify theorem assumptions and conclusions, numerical error conditions and conditions for inferential claims. Measure source recall and grouping before expanding the edition. |
| 2 · Natural sciences | Private Earth and Chemistry pilots | Compare the four chemistry branches and general chemistry. Sample solid Earth, atmosphere, oceans, climate and environmental work. Link observational data to papers and assess evidence quality by branch. |
| 2 · Computing and Information | Begin with theory, systems and human–computer interaction | Check field-specific proceedings, preprint versions and publication spikes around conferences. Sample information and library science separately. |
| 3 · Applied fields | Engineering and materials, agriculture/forestry/fisheries/veterinary/food, medicine and public health | State each pilot’s actual scope. Include field studies and regional-language agriculture. Verify study populations, designs, uncertainty and corrections in clinical and public-health summaries. [FAO AGRIS](https://www.fao.org/agris/) |
| 4 · Social Sciences | Begin with economics/business and psychology/cognition, then education, sociology, law, politics, human geography and media | Track working-paper revisions, countries and languages. Distinguish experimental, observational and replication studies. Check causal claims against study design. [IDEAS/RePEc](https://ideas.repec.org/) |
| 5 · Humanities and Arts | History, archaeology and heritage, languages and literature, philosophy and religion, and arts research | Test 28-day windows with books, chapters, journals and regional-language sources. Check identifiers, parent–chapter duplication and evidence for summaries. Expand the sample if monthly coverage is sparse. [DOAB](https://doabooks.org/) |

Stages 3–5 are provisional. Reader demand, access to conferences, books and regional-language material, and the cost of verification can change their order. Before adding a source, verify access and reuse terms, abstract coverage, pagination and date precision. [arXiv taxonomy](https://arxiv.org/category_taxonomy) · [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api) · [OpenAlex](https://help.openalex.org/api/)

### Source limits that affect the order

| Weekly arXiv submissions, UTC | Oct 22–28 | Oct 29–Nov 4 | Nov 5–11 | Nov 12–18 |
|---|---:|---:|---:|---:|
| All mathematics and statistics | 2,340 | 2,873 | 2,375 | 2,302 |
| Three pilot subjects | 459 | 559 | 479 | 474 |
| All computer science | 4,079 | 4,947 | 4,144 | 3,925 |

The current collector reads the oldest 2,000 records first for a seven-day request. Both broad searches exceeded that limit in every measured week. Split the requests by date and reconcile unique identifiers against source totals before broadening coverage. [Collector](../pipeline/sources/arxiv.py) · [arXiv API](https://info.arxiv.org/help/api/user-manual.html)

For the same 28 days, Crossref’s publication-date filter returned 416 articles from JACS (400 with abstracts), 10 from *Analytical Sciences* (zero with abstracts), zero from *Chemical Science*, 35 from *Earth System Science Data* (all with abstracts) and 27 from *Earth and Planetary Science Letters* (zero with abstracts). All 129 newly registered *Chemical Science* records had only the publication year. Registration can surface candidates whose publication date must then be checked with the publisher. [Crossref filters](https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/) · [Chemical Science records](https://api.crossref.org/journals/2041-6539/works?filter=type:journal-article,from-created-date:2026-10-22,until-created-date:2026-11-18&rows=200&select=DOI,published,created)

## Criteria for regular publication

1. **Collection.** Compare source totals, stored records, duplicates and missing abstracts across four independent weeks, by subfield, language and publication type. Distinguish empty weeks, API failures and truncated results. Follow independent samples from tables of contents, programs and book catalogs through collection, grouping and publication.
2. **Editing.** Sample ten high-ranked, ten low-ranked and ten excluded cases from different weeks and subfields. Review grouping and summaries for ranked cases and the exclusion reasons for the rest. The initial review target is nine passes per set of ten. Rerun a fresh sample after corrections that change conclusions.
3. **Ranking and cadence.** Compare all eligible groups with the top ten, single-journal concentration and category caps. Today a topic needs at least three published papers or preprints within seven days. Test books, chapters and standalone datasets as distinct publication types. Recluster the same collection over seven and 28 days and review recovered and falsely merged topics. The existing weekly and monthly pages aggregate daily rankings. [Daily pipeline](../pipeline/run.py) · [Period aggregation](../site/src/lib/periods.ts)
4. **Operations.** For the first 14 live daily editions track success, duration and cost, then estimate 30-day spending across the service. Review representativeness using non-overlapping weeks because consecutive daily inputs overlap. Decide the total monthly budget from measured usage before enabling a recurring new field.
5. **Publication.** Make the scope, sources and actual edition date visible. Verify independent data paths, dated permalinks, source links, retention of the preceding edition on failure and archive regressions. Decide whether to publish, improve sources or change the cadence.

## Coverage across research classifications

All 42 second-level OECD categories have an editorial home. Each “other” category feeds a subfield review queue. A persistent body of work can acquire its own named subfield. [OECD Frascati Manual, Table 2.2](https://www.oecd.org/content/dam/oecd/en/publications/reports/2015/10/frascati-manual-2015_g1g57dcb/9789264239012-en.pdf)

| OECD division | Detailed fields and their destination |
|---|---|
| Natural sciences | 1.1 mathematics/statistics, 1.2 computing/information, 1.3 physics/astronomy, 1.4 chemistry, 1.5 Earth/environment, 1.6 biology, 1.7 other natural sciences |
| Engineering and technology | 2.1 civil, 2.2 electrical/electronic/information, 2.3 mechanical, 2.4 chemical, 2.5 materials, 2.6 medical engineering, 2.7 environmental engineering, 2.8 environmental biotechnology, 2.9 industrial biotechnology, 2.10 nanotechnology, 2.11 other engineering |
| Medicine and health | 3.1 basic medicine, 3.2 clinical medicine, 3.3 health sciences, 3.4 medical biotechnology, 3.5 other medical sciences |
| Agriculture and veterinary sciences | 4.1 agriculture/forestry/fisheries, 4.2 animal and dairy sciences, 4.3 veterinary sciences, 4.4 agricultural biotechnology, 4.5 other agricultural sciences |
| Social sciences | 5.1 psychology/cognition, 5.2 economics/business, 5.3 education, 5.4 sociology, 5.5 law, 5.6 politics, 5.7 social/economic geography, 5.8 media/communications, 5.9 other social sciences |
| Humanities and arts | 6.1 history/archaeology, 6.2 languages/literature, 6.3 philosophy/ethics/religion, 6.4 arts research, 6.5 other humanities |

We also mapped all 23 ANZSRC 2020 Fields of Research divisions to reader editions. [Australian Bureau of Statistics classification](https://www.abs.gov.au/statistics/classifications/australian-and-new-zealand-standard-research-classification-anzsrc/2020) · [Fields of Research, Table 1](https://www.abs.gov.au/statistics/classifications/australian-and-new-zealand-standard-research-classification-anzsrc/2020/anzsrc2020_for.xlsx)

| Destination | FoR division numbers | Boundary checks |
|---|---|---|
| Biology, Physics, Mathematics | 31, 51, 49 | Observational astronomy belongs in Physics. New statistical methods belong in Mathematics. A new biological finding using those methods belongs in Biology. |
| Chemistry, Earth/Environment, Computing | 34, 37, 41, 46 | Sample Earth observations and environmental/conservation studies separately. Include information retrieval and library science. |
| Engineering, Agriculture, Medicine | 40, 33, 30, 32, 42 | Cover built environment and urban design in Engineering, urban inequality in Social Sciences, food production in Agriculture/Food, and population nutrition in Health. |
| Social Sciences | 35, 38, 39, 44, 48, 52 | Include tourism and services, legal and policy research, and classroom-based education studies. |
| Humanities and Arts | 36, 43, 47, 50 | Cover cultural heritage, performance and writing. Route social effects of media to Social Sciences. |
| Across editions | 45, Indigenous studies | Tag explicitly and route by the research question. Language revitalization can appear in language/culture and community health in Health. Verify samples against public lists from the relevant communities and institutions. |

Use the primary question to route interdisciplinary work and cross-link other editions. For example, an energy material’s phase transition, an energy-storage device’s performance and an energy policy belong primarily in Physics, Engineering and Social Sciences respectively. Link versions of the same work and count it once within an edition.

## Checks on the public editions

**All Biology and CompBio.** Each edition independently filters, clusters and ranks a seven-day collection. All Biology currently samples 17 bioRxiv subjects and 11 PubMed journals. The top ten on November 19 drew on 81 unique papers for All Biology and 93 for CompBio. Each set had 81 distinct DOIs, with 17 shared out of a union of 145. Twelve CompBio papers had no DOI and the editions ran at different times. Keep both editions and track this overlap over 14 live dates before reconsidering the home page. [All Biology data](../data/biology/days/2026-11-19.json) · [CompBio data](../data/computational/days/2026-11-19.json)

All Biology collected 756 bioRxiv and 91 PubMed records on its first date. Of the records, 815 passed relevance, yielding 116 clusters and 40 ranked topics. The code activity signal was zero. Evidence diversity contributed 0.25 for one publication type and 0.50 for both a preprint and a journal publication. Multiple journals of one publication type gave the same diversity value. [Biology sources](../config/sources/biology.yaml) · [Scoring](../pipeline/score.py)

| Primary Biology category | Relevant records | Clusters | Ranked |
|---|---:|---:|---:|
| Cell and molecular | 166 | 28 | 8 |
| Neuroscience | 182 | 29 | 8 |
| Quantitative biology | 156 | 21 | 8 |
| Genetics and genomics | 93 | 12 | 7 |
| Development | 27 | 7 | 4 |
| Evolution and paleobiology | 38 | 7 | 2 |
| Ecology | 25 | 3 | 1 |
| Plants | 59 | 8 | 1 |
| Organismal and behavioral | 41 | 1 | 1 |
| Microbial ecology | 18 | 0 | 0 |
| Immunobiology | 10 | 0 | 0 |
| Other | 0 | 0 | 0 |

Three microbial ecology and four immunobiology papers contributed to clusters assigned other primary labels. Thirty of the 59 plant papers entered plant clusters. Among the 81 unique papers behind the All Biology top ten, 72 came from bioRxiv and seven from *Plant Physiology*. Check the absence of dedicated microbiology and immunology bioRxiv categories, the two microbial ecology journals and one immunology journal, and the score distribution for the eight plant clusters. Reweighting growth at 75% and volume at 25%, holding clusters and caps fixed, retained nine of the first day’s top ten. The simultaneous-cluster median serves as the first-day baseline. Continue the beta. [All Biology audit](../data/biology/audits/first-14.json)

**Physics.** Of 106 clusters, 68 were quantum, 16 cosmology, 11 optics and 11 mesoscopic/nanoscale physics. A cap of eight per category yielded 32 visible topics. All had 0.25 evidence diversity and zero code activity on that date. Across the same four weeks, the weekly ranges outside the covered subjects were 243–287 for stellar/galactic work, 182–259 for gravity, 273–352 for particle/nuclear work, 145–153 for fluids/plasmas and 104–153 for statistical physics. Cross-listings can overlap. Start the next Physics sample with observational and theoretical work in stellar and galactic astronomy. The live audit has recorded two Physics dates and one All Biology date as of this review. [Physics source comparison](expansion-measurements/2026-11-19/physics-archives.json) · [Physics audit](../data/physics/audits/first-14.json)
