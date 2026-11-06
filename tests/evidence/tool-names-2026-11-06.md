# Tool-name review — 2026-11-06

## Extraction audit

Read every stored computational paper item under `data/computational/items`, retaining the last sorted shard for duplicate IDs, and applied the proposed title-prefix regex and initial stoplist. No data files were changed. Counts below are paper occurrences, not leaderboard appearances; original spelling is preserved. This produced 6,227 candidate paper titles and 5,852 distinct spellings.

The 80 most frequent candidates and all 100 sampled titles below were read by hand. Sample: Python `random.Random(20261106).sample(sorted(matches, key=lambda item: item["id"]), 100)`, without replacement. A positive is a named method, model, software package, dataset, benchmark, database or instrument introduced by the title; it does not imply available software or independent validation.

**Estimated precision: 99/100 (99%) before additions.** The sole sample false positive was Autoimmunity (#56). Added **Corrigendum**, **Retraction** (obvious non-names in the frequent list), and **Autoimmunity** to the exported case-insensitive stoplist. The same sample retains 99/99 apparent names afterward; this is a tuning sample, not an independent 100% precision claim. Regex extraction can still mistake an ordinary noun for a name and miss titles without this format.

## 80 most frequent candidates (before additions)

| Name | Papers | Manual review |
| --- | ---: | --- |
| MOSAIC | 6 | Named method/resource |
| PRISM | 6 | Named method/resource |
| BRIDGE | 6 | Named method/resource |
| ECLIPSE | 4 | Named method/resource |
| SPARK | 4 | Named method/resource |
| PRIME | 4 | Named method/resource |
| Corrigendum | 4 | Reject: publication notice |
| TRACE | 4 | Named method/resource |
| AEGIS | 3 | Named method/resource |
| EMBER | 3 | Named method/resource |
| Panorama | 3 | Named method/resource |
| ProMeta | 3 | Named method/resource |
| GRAFT | 3 | Named method/resource |
| Retraction | 3 | Reject: publication notice |
| TANGO | 3 | Named method/resource |
| singIST | 3 | Named method/resource |
| SMART | 3 | Named method/resource |
| ORBIT | 3 | Named method/resource |
| MIRAGE | 3 | Named method/resource |
| RAPID | 3 | Named method/resource |
| EPIC | 3 | Named method/resource |
| PETRA | 2 | Named method/resource |
| SPECTRA | 2 | Named method/resource |
| PEtab-GUI | 2 | Named method/resource |
| MDIntrinsicDimension | 2 | Named method/resource |
| BaGGLS | 2 | Named method/resource |
| SeqManager | 2 | Named method/resource |
| DeepPNI | 2 | Named method/resource |
| Singletrack | 2 | Named method/resource |
| Metappuccino | 2 | Named method/resource |
| KCFtools | 2 | Named method/resource |
| CycleVI | 2 | Named method/resource |
| BudFinder | 2 | Named method/resource |
| phylobar | 2 | Named method/resource |
| Pro4S | 2 | Named method/resource |
| SiSaNA | 2 | Named method/resource |
| RiboZAP | 2 | Named method/resource |
| Seqwin | 2 | Named method/resource |
| SpNeigh | 2 | Named method/resource |
| USP-ddG | 2 | Named method/resource |
| CASPULE | 2 | Named method/resource |
| GeneSNAKE | 2 | Named method/resource |
| SignifiKANTE | 2 | Named method/resource |
| PMGen | 2 | Named method/resource |
| PaNDA | 2 | Named method/resource |
| SigRescueR | 2 | Named method/resource |
| AstroLogics | 2 | Named method/resource |
| PCLIPtools | 2 | Named method/resource |
| XChrom | 2 | Named method/resource |
| MAGIC | 2 | Named method/resource |
| SHEST | 2 | Named method/resource |
| IRCAS | 2 | Named method/resource |
| scDock | 2 | Named method/resource |
| PertAdapt | 2 | Named method/resource |
| Selector | 2 | Named method/resource |
| MiRformer | 2 | Named method/resource |
| STcompare | 2 | Named method/resource |
| Cis-TERN | 2 | Named method/resource |
| RoBep | 2 | Named method/resource |
| LoL-align | 2 | Named method/resource |
| Eduomics | 2 | Named method/resource |
| Amaranth | 2 | Named method/resource |
| TAGINE | 2 | Named method/resource |
| Tangerine | 2 | Named method/resource |
| MIMEco | 2 | Named method/resource |
| plinkQC | 2 | Named method/resource |
| NanoporeDB | 2 | Named method/resource |
| TIRTL-seq | 2 | Named method/resource |
| STAR-GO | 2 | Named method/resource |
| DeeDeeExperiment | 2 | Named method/resource |
| needLR | 2 | Named method/resource |
| SynCraft | 2 | Named method/resource |
| MERGE-RNA | 2 | Named method/resource |
| SpatialBench | 2 | Named method/resource |
| HELM-BERT | 2 | Named method/resource |
| GALA | 2 | Named method/resource |
| SNooPy | 2 | Named method/resource |
| COMPASS | 2 | Named method/resource |
| GatorSC | 2 | Named method/resource |
| geneSCOPE | 2 | Named method/resource |

## Random 100 candidates (before additions)

| # | Candidate | Stored paper title | Manual review |
| ---: | --- | --- | --- |
| 1 | WASTER | WASTER: Practical de novo Phylogenomics from Low-coverage Short Reads. | Named method/resource |
| 2 | MDAgent | MDAgent: A Multi-Agent Framework for End-to-End Molecular Dynamics Research | Named method/resource |
| 3 | NeuroWorld | NeuroWorld: A Latent Brain World Model for Stimulus-Conditioned Human Brain Dynamics | Named method/resource |
| 4 | PyrMol | PyrMol: A Knowledge-Structured Pyramid Graph Framework forGeneralizable Molecular Property Prediction | Named method/resource |
| 5 | CBIcall | CBIcall: a configuration-driven framework for variant calling in large sequencing cohorts | Named method/resource |
| 6 | SurgSLOT | SurgSLOT: Segment Anything in Surgical Videos via Semantic Long-term Tracking | Named method/resource |
| 7 | ALPINE | ALPINE: a scalable pipeline for comprehensive classification of gene-editing outcomes from long-read amplicon sequencing. | Named method/resource |
| 8 | CellPilot | CellPilot: an agentic framework that pilots small language models through autonomous single-cell annotation | Named method/resource |
| 9 | qPyCR | qPyCR: A qPCR Data Analyzer for Template Quantification and the Detection of Performance Outliers | Named method/resource |
| 10 | Elab2ARC | Elab2ARC: A Browser-Based Workspace for Converting Free-Text Protocols into rich FAIR digital objects | Named method/resource |
| 11 | SynBioFooDB | SynBioFooDB: a comprehensive resource for synthetic biology-driven food biomanufacturing. | Named method/resource |
| 12 | SpikGPT | SpikGPT: A High-Accuracy and Interpretable Spiking Attention Framework for Single-Cell Annotation | Named method/resource |
| 13 | DiagnoDating | DiagnoDating: diagnostics for dated phylogenies in microbial population genetics. | Named method/resource |
| 14 | BrainFuse | BrainFuse: a unified infrastructure integrating realistic biological modeling and core AI methodology | Named method/resource |
| 15 | TopoLIA | TopoLIA: Topology-Inspired Latent Interaction Attention for Drug Discovery | Named method/resource |
| 16 | EasyPseudogene | EasyPseudogene: an easy-to-use and multithreaded pipeline for pseudogene detection | Named method/resource |
| 17 | Susagi | Susagi: A Microbiome World Model | Named method/resource |
| 18 | mIDEA | mIDEA: An Interpretable Structure-Sequence Model for Methylation-Dependent Protein-DNA Binding Sensitivity | Named method/resource |
| 19 | XAI-ecDNA | XAI-ecDNA: A Proof-of-Concept Framework for Explainable Multi-Modal Extrachromosomal DNA Detection Using Synthetic FISH and Genomics | Named method/resource |
| 20 | SAbDab2 | SAbDab2: The structural antibody database in the age of machine learning | Named method/resource |
| 21 | SurfFold | SurfFold: a unified model for protein inverse folding by integrating surface and structural information. | Named method/resource |
| 22 | SpNeigh | SpNeigh: spatial neighborhood and differential expression analysis for high-resolution spatial transcriptomics | Named method/resource |
| 23 | Carbonara | Carbonara: a SAXS-guided seeding framework for exploring protein solution-state dynamics | Named method/resource |
| 24 | MDNA | MDNA : a software module for DNA structure generation and analysis. | Named method/resource |
| 25 | DiagnoLLM | DiagnoLLM: A Hybrid Bayesian Neural Language Framework for Interpretable Disease Diagnosis | Named method/resource |
| 26 | CLEAR | CLEAR: Concise List Enrichment Analysis Reducing Redundancy | Named method/resource |
| 27 | Accelign | Accelign: a GPU-based library for accelerating pairwise sequence alignment. | Named method/resource |
| 28 | DMGRN | DMGRN: Enhancing Diffusion Models for Gene Regulatory Network Inference. | Named method/resource |
| 29 | SmartTrap | SmartTrap: automated precision experiments with optical tweezers. | Named method/resource |
| 30 | cryoSENSE | cryoSENSE: Compressive Sensing Enables High-throughput Microscopy with Sparse and Generative Priors on the Protein Cryo-EM Image Manifold | Named method/resource |
| 31 | Enerzyme | Enerzyme: A Framework for Efficient Training of Reactive Neural Network Potentials for Enzyme Catalysis with Application to Methyltransferases | Named method/resource |
| 32 | QuiCAT | QuiCAT: a scalable and flexible framework for mapping synthetic sequences. | Named method/resource |
| 33 | NimbusImage | NimbusImage: a cloud-computing platform for image analysis. | Named method/resource |
| 34 | DREAMER-S | DREAMER-S: Deep leaRning-Enabled Attention-based Multiple-instance approaches with Explainable Representations for Spatial biology. | Named method/resource |
| 35 | PDI-Spot | PDI-Spot: A Robust Representation Learning Framework for Identifying Energetic Hotspots in Protein-DNA Complexes. | Named method/resource |
| 36 | DSCC | DSCC: disease subtyping using spectral clustering and community detection from consensus networks. | Named method/resource |
| 37 | Helicase | Helicase: Vectorized parsing and bitpacking of genomic sequences | Named method/resource |
| 38 | scHyperLink | scHyperLink: Revealing Cell-Type-Specific Gene Regulation With Hypergraph Neural Networks. | Named method/resource |
| 39 | kache-hash | kache-hash: A dynamic, concurrent, and cache-efficient hash table for streaming k-mer operations | Named method/resource |
| 40 | PepALD | PepALD: Macrocyclic Peptide Generation via Autoregressive Latent Diffusion | Named method/resource |
| 41 | Prot-LAMBDA | Prot-LAMBDA: Explicit Distance Learning Enhances Structural Reasoning in Protein Language Models | Named method/resource |
| 42 | scGPA | scGPA: an LLM-assisted workflow for directional virtual gene perturbation analysis from single-cell transcriptomes. | Named method/resource |
| 43 | biHash | biHash: bisulfite-aware recursive nucleotide hashing | Named method/resource |
| 44 | scDiagnostics | scDiagnostics: systematic assessment of cell type annotation in single-cell transcriptomics data. | Named method/resource |
| 45 | TensorPLS | TensorPLS: an R package for exploring molecular and temporal patterns in longitudinal omics data using PLS-DA | Named method/resource |
| 46 | CrossLabFit | CrossLabFit: A novel framework for integrating qualitative and quantitative data across multiple labs for model calibration. | Named method/resource |
| 47 | DRIADA | DRIADA: an open-source Python toolkit for linking single-neuron selectivity and population activity to behavior | Named method/resource |
| 48 | CAMP | CAMP: Coreset Accelerated Metacell Partitioning enables scalable analysis of single-cell data | Named method/resource |
| 49 | TiSAM | TiSAM: fusing spatial and histopathology foundation models for whole-slide image segmentation | Named method/resource |
| 50 | EpiBench | EpiBench: Can LLMs Understand Epitopes for Antibody Drug Discovery? | Named method/resource |
| 51 | wavess 1.2 | wavess 1.2: presenting an HLA-aware within-host virus sequence simulation framework. | Named method/resource |
| 52 | Static2Dynamic | Static2Dynamic: Reconstructing videos of unobservable cellular, developmental, and disease processes | Named method/resource |
| 53 | GenCore | GenCore: Genomic distance estimation using Locally Consistent Parsing | Named method/resource |
| 54 | WIMOAD | WIMOAD: Weighted Integration of Multi-Omics data with meta learning for Alzheimer's Disease diagnosis. | Named method/resource |
| 55 | HipHap | HipHap: Haplotype Assignment and Confidence Scoring for Diploid Reference Genomes | Named method/resource |
| 56 | Autoimmunity | Autoimmunity: Molecular Mechanisms, Biomarkers, and Therapeutic Opportunities. | Reject: disease overview |
| 57 | LRSomatic | LRSomatic: a highly scalable and robust pipeline for somatic variant calling in long-read sequencing data | Named method/resource |
| 58 | RAPID-Net | RAPID-Net: Accurate Pocket Identification for Binding-Site-Agnostic Docking. | Named method/resource |
| 59 | Col-Ovo | Col-Ovo: Smartphone-based artificial intelligence for rapid counting of Aedes mosquito eggs under field conditions | Named method/resource |
| 60 | CarveMe-GutMicrobes | CarveMe-GutMicrobes: Automated Metabolic Model Reconstruction for Gut Microbial Species and Communities | Named method/resource |
| 61 | HyperCom | HyperCom: a hypergraph-based method to infer cell-resolved cell-cell communication. | Named method/resource |
| 62 | NORI | NORI: Fast probabilistic inference for ambiguous observation-entity mappings | Named method/resource |
| 63 | BiGAT-Fusion | BiGAT-Fusion: Node-Wise Gated Bidirectional Graph Attention for Drug Repurposing | Named method/resource |
| 64 | Omni-iEEG | Omni-iEEG: A Large-Scale, Comprehensive iEEG Dataset and Benchmark for Epilepsy Research | Named method/resource |
| 65 | ADMET-XSpec | ADMET-XSpec: A Tool for Systematic Cross-Species Data Integration in ADMET Prediction. | Named method/resource |
| 66 | hStouffer | hStouffer: the enhanced meta-analysis method for the comprehensive analysis of large-scale RNA-seq data. | Named method/resource |
| 67 | IHIT-BED | IHIT-BED: an interpretable transformer approach using unbiased hematology analyzer impedance data for early identification of bacteremia in emergency department. | Named method/resource |
| 68 | MOZAIC | MOZAIC: compound growth via in silico reactions and global optimization using Conformational Space Annealing. | Named method/resource |
| 69 | BioResearcher | BioResearcher: Scenario-Guided Multi-Agent for Translational Medicine | Named method/resource |
| 70 | SVCROWS | SVCROWS: a user-defined tool for interpreting significant structural variants in heterogeneous datasets. | Named method/resource |
| 71 | ybyra | ybyra: Y-chromosome haplogroup calling using a tree-based scoring method | Named method/resource |
| 72 | CLEAR-HPV | CLEAR-HPV: Interpretable Concept Discovery for HPV-Associated Morphology in Whole-Slide Histology | Named method/resource |
| 73 | BENDER | BENDER: A Cross-taxon IDP Simulation Database Reveals Conserved Sequence-Ensemble Laws Across the Tree of Life | Named method/resource |
| 74 | IECP | IECP: iterative equilibration of cell-type expression profiles improves accuracy of reference-free deconvolution. | Named method/resource |
| 75 | NeuroWeave-3D | NeuroWeave-3D: Uncertainty-Aware Evidence Completion for Brain Tumor Segmentation with Missing MRI Modalities | Named method/resource |
| 76 | StabilityArc | StabilityArc: Decoding Protein Sequence Embeddings into Generalizable Stability Landscapes | Named method/resource |
| 77 | TripKa | TripKa: Accurate and Scalable Acid-Base Dissociation Property Prediction via Triplet Interaction Networks and Physical Knowledge. | Named method/resource |
| 78 | UcTCRp | UcTCRp: a TCRβ-based framework for quantitative MAIT- and iNKT-associated repertoire-state profiling | Named method/resource |
| 79 | TriGraphQA | TriGraphQA: a triple graph learning framework for model quality assessment of protein complexes | Named method/resource |
| 80 | CryoFSL | CryoFSL: an annotation-efficient, few-shot learning framework for robust protein particle picking in cryo-electron microscopy micrographs. | Named method/resource |
| 81 | AntibodyDesignBFN | AntibodyDesignBFN: High-Fidelity Fixed-Backbone Antibody Design via Discrete Bayesian Flow Networks | Named method/resource |
| 82 | CRAIC | CRAIC: interactive interrogation of multiple sequence alignment uncertainty | Named method/resource |
| 83 | ViraHinter | ViraHinter: a dual-modal artificial intelligence framework for predicting virus-host interactions | Named method/resource |
| 84 | STSBench | STSBench: A Large-Scale Dataset for Modeling Neuronal Activity in the Dorsal Stream of Primate Visual Cortex | Named method/resource |
| 85 | spaCraft | spaCraft: calibrated power analysis and sample-size planning for multi-sample spatial transcriptomics | Named method/resource |
| 86 | ProfhEX | ProfhEX: Empowering Early Drug Discovery with Machine Learning-Based Target Profiling and Liability Prediction. | Named method/resource |
| 87 | AXOLOTL | AXOLOTL: an accurate method for detecting aberrant gene expression in rare diseases using coexpression constraints. | Named method/resource |
| 88 | GenPairX | GenPairX: A Hardware-Algorithm Co-Designed Accelerator for Paired-End Read Mapping | Named method/resource |
| 89 | Arborist | Arborist: Prioritizing Bulk DNA Inferred Tumor Phylogenies via Low-pass Single-cell DNA Sequencing Data | Named method/resource |
| 90 | AMix-2 | AMix-2: Establishing Protein as a Native Modality in Large Language Models | Named method/resource |
| 91 | SCUDDO | SCUDDO: an unsupervised clustering algorithm for single-cell Hi-C maps using diagonal diffusion operators. | Named method/resource |
| 92 | LINKER | LINKER: Learning Interactions between Functional Groups and Residues with Chemical Knowledge-Enhanced Reasoning and Explainability. | Named method/resource |
| 93 | UnivAIRRse | UnivAIRRse: A Unified Framework for Organizing and Comparing Adaptive Immune Receptor Repertoire Simulators | Named method/resource |
| 94 | SIMOFF | SIMOFF: Discovering the metabolic objective of the cell | Named method/resource |
| 95 | UNAAGI | UNAAGI: Atom-Level Diffusion for Generating Non-Canonical Amino Acid Substitutions | Named method/resource |
| 96 | NeuroPpred-PSCG | NeuroPpred-PSCG: A Multimodal Framework Using ProtT5 and Structural Features for Neuropeptide Prediction Based on Gated Cross-Attention Mechanism and Multiscale Gated Convolution. | Named method/resource |
| 97 | Siibra | Siibra: a software tool suite for realizing a Multilevel Human Brain Atlas from complex data resources. | Named method/resource |
| 98 | DistPCA | DistPCA: Tera-Scale Genomic PCA via Out-of-Core Distributed Parallelism | Named method/resource |
| 99 | TCR2HLA | TCR2HLA: Calibrated inference of HLA genotypes from TCR repertoires enables identification of immunologically relevant metaclonotypes. | Named method/resource |
| 100 | KlinkPPI | KlinkPPI: Single Point of Access to Protein-Protein Interactions Across Databases | Named method/resource |

## Delivery and checks

- Names are **paper links**, using `target="_blank" rel="noopener"`; card headline links use a stretched pseudo-element and paper links sit above it. Names preserve title casing (including acronym names), with no uppercase styling.
- Pages: home, day, week and month rankings. Period names use the most recent history entry inside that period, including unranked entries, without pooling earlier paper IDs. Ranks 21–40 have no name line; unnamed rows have no empty element and retain their previous height.
- Shared global item cache reads each requested paper at most once per build, including repeated IDs; no per-row filesystem traversal.
- Real data baseline: `/usr/bin/time -p env TRENDBIO_DATA_ROOT=../data npm run build` from `site/`: **3.52 s wall**, Astro **2.79 s**, 1,074 pages.
- Final real-data build after the mobile-wrap fix, with the same command: **6.71 s wall**, Astro **6.10 s**, 1,074 pages; under the requested 10 seconds. An earlier post-feature measurement was 3.58 s wall / 3.15 s Astro; timings vary with other local test work.
- `cd site && npm test && npm run build`: **16 files, 132 tests passed** (18.95 s); build succeeded. Coverage includes extraction/version/stoplist/length boundaries, published-first alphabetical selection, case-insensitive deduplication, at most three names, exact day and most-recent in-period history, rank 20/21, no empty line, source-level nested-anchor validation, independent card/paper clicks, keyboard order/focus and both-theme axe checks. Fixtures live only under `site/tests/fixtures/tool-names` and are copied by `site/tests/build.ts`.
- Real-data `/` at both widths and themes: **zero WCAG A/AA axe violations**, no horizontal page overflow, no vertical compact-row overflow. A wrapping issue found during image inspection was corrected and covered by long-name compact fixtures.
- Viewed all four full-page screenshots, plus readable featured/compact crops. Names remain quiet and readable in dark/light themes; mobile names wrap within their rows, and unnamed rows keep their original 40 px height. Screenshots are local, git-ignored artifacts:
  - `site/.playwright-shots/tool-names-real-1280-dark.png`
  - `site/.playwright-shots/tool-names-real-1280-light.png`
  - `site/.playwright-shots/tool-names-real-390-dark.png`
  - `site/.playwright-shots/tool-names-real-390-light.png`
  - Corresponding `-featured.png` and `-compact.png` crops in the same directory.

No LLM calls, ranking changes, data writes, dependencies or deployment.

## Cut-synthesis repair

- `synthesis_repair_targets` now recognizes any headline or summary ending in `…`, in either a day row or topic, without the former 91/161-character caps. Completed item-fallback rows with their `synthesis-fallback:` note remain excluded.
- Regression tests cover 112-character headlines, new limits and longer values in both rows/topics, long item-fallback headlines/summaries, and a successfully repaired row/topic producing no further jobs.
- Full required Python command: `uv run --no-project --python 3.12 --with pydantic --with pytest --with numpy --with pyyaml --with respx --with httpx --with feedparser --with anthropic --with scikit-learn --with typer --with umap-learn python -m pytest -q`: **536 passed**, 101 UMAP random-seed/n_jobs warnings, **101.42 s**.
- Real-data command (same uv dependencies): `python -m pipeline repair-synthesis --from 2026-11-01 --to 2026-11-06 --data-root data --dry-run` returned **`repair_synthesis_targets rows=1 topics=2 estimated_jobs=2`**.
- Only the dry run was executed: the existing cut headline in `data/` remains untouched for the coordinator to repair separately if authorized. No live LLM calls, workflow dispatch or push.
