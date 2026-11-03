"""Regenerate the synthetic contract fixtures: python -m tests.fixtures_build."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from itertools import combinations
from pathlib import Path

import yaml

from pipeline.jsonio import day_path, dump, item_path, topic_path
from pipeline.models import Day, Item, RankedTopic, RunInfo, Scores, Signals, Topic, TopicDay


def log1p(value: int) -> float:
    # Decimal's correctly rounded logarithm avoids platform libm differences in fixture bytes.
    return float(Decimal(1 + value).ln())


def build(root: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    taxonomy = yaml.safe_load((repo / "config/taxonomy/computational.yaml").read_text(encoding="utf-8"))
    categories = [entry["slug"] for entry in taxonomy["categories"]]
    scoring = yaml.safe_load((repo / "config/scoring.yaml").read_text(encoding="utf-8"))
    specs = [
        ("protein-design-binders-a1b2", "Protein binder design", 6, "Binder design gains shared evaluation tools"),
        ("single-cell-perturbations-c3d4", "Single-cell perturbation models", 5, "Perturbation models converge on held-out cell states"),
        ("pangenome-graph-mapping-e5f6", "Pangenome graph mapping", 0, "Graph mapping workflows expand reproducible comparisons"),
        ("spatial-transcriptomics-atlas-a7b8", "Spatial transcriptomics atlases", 1, "Spatial atlas methods connect expression and tissue context"),
        ("reproducible-workflow-tools-c9d0", "Reproducible workflow tools", 9, "Workflow releases bring portable analysis environments"),
        ("proteome-search-0006", "Proteome search", 2, "Proteome search methods improve reference coverage"),
        ("metabolic-flux-0007", "Metabolic flux models", 3, "Flux models connect metabolite measurements to pathways"),
        ("chromatin-accessibility-0008", "Chromatin accessibility", 4, "Chromatin models resolve regulatory context"),
        ("pathway-networks-0009", "Pathway networks", 7, "Pathway networks connect perturbation evidence"),
        ("sequence-models-0010", "Biological sequence models", 8, "Sequence models broaden held-out evaluation"),
        ("variant-annotation-0011", "Variant annotation", 0, "Variant annotation tools share reference benchmarks"),
        ("industry-platforms-0012", "Industry platforms", 10, "Research platforms release reproducible reference workflows"),
        ("rna-splicing-0013", "RNA splicing models", 1, "Splicing models connect sequence and expression"),
        ("protein-interactions-0014", "Protein interactions", 2, "Interaction maps extend shared evaluation resources"),
        ("metabolite-identification-0015", "Metabolite identification", 3, "Metabolite identification gains open reference spectra"),
        ("methylation-models-0016", "Methylation models", 4, "Methylation methods compare regulatory predictions"),
        ("cell-state-mapping-0017", "Cell state mapping", 5, "Cell state maps connect independent reference atlases"),
        ("enzyme-design-0018", "Enzyme design", 6, "Enzyme design benchmarks compare functional predictions"),
        ("network-dynamics-0019", "Network dynamics", 7, "Network models compare dynamic pathway responses"),
        ("workflow-validation-0020", "Workflow validation", 9, "Workflow validation tools simplify reproducibility checks"),
        ('long-read-assembly-0021', 'Long read assembly', 0, 'Long read assembly extend reproducible comparisons'),
        ('rna-structure-0022', 'RNA structure prediction', 1, 'RNA structure prediction extend reproducible comparisons'),
        ('peptide-search-0023', 'Peptide search', 2, 'Peptide search extend reproducible comparisons'),
        ('lipidomics-atlases-0024', 'Lipidomics atlases', 3, 'Lipidomics atlases extend reproducible comparisons'),
        ('enhancer-prediction-0025', 'Enhancer prediction', 4, 'Enhancer prediction extend reproducible comparisons'),
        ('cell-lineage-0026', 'Cell lineage tracing', 5, 'Cell lineage tracing extend reproducible comparisons'),
        ('antibody-design-0027', 'Antibody design', 6, 'Antibody design extend reproducible comparisons'),
        ('signaling-networks-0028', 'Signaling networks', 7, 'Signaling networks extend reproducible comparisons'),
        ('multimodal-models-0029', 'Multimodal biology models', 8, 'Multimodal biology models extend reproducible comparisons'),
        ('workflow-provenance-0030', 'Workflow provenance', 9, 'Workflow provenance extend reproducible comparisons'),
        ('research-automation-0031', 'Research automation platforms', 10, 'Research automation platforms extend reproducible comparisons'),
        ('genome-imputation-0032', 'Genome imputation', 0, 'Genome imputation extend reproducible comparisons'),
        ('isoform-quantification-0033', 'Isoform quantification', 1, 'Isoform quantification extend reproducible comparisons'),
        ('protein-localization-0034', 'Protein localization', 2, 'Protein localization extend reproducible comparisons'),
        ('metabolic-pathways-0035', 'Metabolic pathway inference', 3, 'Metabolic pathway inference extend reproducible comparisons'),
        ('regulatory-elements-0036', 'Regulatory element maps', 4, 'Regulatory element maps extend reproducible comparisons'),
        ('cell-type-annotation-0037', 'Cell type annotation', 5, 'Cell type annotation extend reproducible comparisons'),
        ('protein-folding-0038', 'Protein folding models', 6, 'Protein folding models extend reproducible comparisons'),
        ('disease-networks-0039', 'Disease network models', 7, 'Disease network models extend reproducible comparisons'),
        ('benchmark-tools-0040', 'Benchmark tools', 9, 'Benchmark tools extend reproducible comparisons'),
    ]
    days = [date(2026, 10, 30) + timedelta(days=i) for i in range(3)]
    topics = []
    for topic_index, (slug, label, category_index, headline) in enumerate(specs):
        category = categories[category_index]
        secondary = [categories[8]]
        items = []
        evidence = [
            ("biorxiv", "preprint", "Evaluation protocol"),
            ("arxiv", "preprint", "Held-out benchmark"),
            ("biorxiv", "preprint", "Cross-dataset comparison"),
            ("biorxiv", "preprint", "Reproducible analysis"),
            ("pubmed", "published", "Reproducible analysis"),
            ("github", "code", "Evaluation toolkit"),
            ("rss", "industry", "Reference workflow announcement"),
            ("arxiv", "preprint", "Independent replication"),
        ]
        for index, (source, kind, title) in enumerate(evidence):
            seen = date(2026, 8, 24) if topic_index == 0 and index < 3 else date(2026, 10, 26) + timedelta(days=index // 2)
            native = f"fixture-{topic_index + 1:02d}-{index + 1:02d}"
            if source == "biorxiv":
                native = f"10.1101/{seen:%Y.%m.%d}.{topic_index + 1:02d}{index + 1:04d}"
            elif source == "github":
                native = f"trendbio-fixtures/{slug}"
            doi = native if source == "biorxiv" else f"10.0000/{native}" if kind == "published" else None
            metadata = {"fixture": True}
            if kind == "published":
                metadata["journal"] = "Synthetic Methods Journal"
            elif kind == "code":
                metadata.update(license="MIT", star_gain_7d=120, stars=420)
            elif kind == "industry":
                metadata["source_name"] = "Example Research Tools"
            items.append(Item(
                id=f"{source}:{native}", source=source, type=kind,
                title=f"{label}: {title.lower()}", url=f"https://example.org/{slug}/{index + 1}",
                doi=doi, published_at=seen, first_seen=seen,
                authors=["Example Researcher", "Sample Collaborator"] if kind in ("preprint", "published") else [],
                org="Example Research Tools" if kind in ("code", "industry") else None,
                abstract=f"Synthetic fixture for {label.lower()}. It describes {title.lower()} using a shared evaluation protocol.",
                summary=f"{title} for {label.lower()} with shared evaluation inputs.",
                primary_category=category, secondary_categories=secondary,
                published_doi=None, preprint_id=None, metadata=metadata,
            ))
        items[3].published_doi = items[4].doi
        items[4].preprint_id = items[3].id
        for item in items:
            dump(item, item_path(root / "data", "computational", item))

        history = []
        start = date(2026, 8, 24) if topic_index == 0 else days[0]
        for offset in range((days[-1] - start).days + 1):
            today = start + timedelta(days=offset)
            current = [item for item in items if today - timedelta(days=6) <= item.first_seen <= today]
            linked = {item.preprint_id for item in current if item.preprint_id}
            counted = [item for item in current if item.id not in linked]
            rank = None
            if today in days and (topic_index < 5 or today == days[-1]):
                rank = topic_index + 1
                if today == days[-1] and topic_index < 2:
                    rank = 2 - topic_index
            elif topic_index == 0 and today == start:
                rank = 1
            counts = {kind: sum(item.type == kind for item in counted) for kind in ("published", "preprint", "code", "industry")}
            signals = Signals(**counts, rise_ratio=5.0 - rank * 0.7 if rank else 1.0 if counted else 0.0,
                              star_gain_7d=sum(item.metadata.get("star_gain_7d", 0) for item in counted))
            if today == days[-1] and rank:
                signals.rise_ratio = 5.0 - rank * 0.15 if rank <= 5 else 3.8 - (rank - 6) * 0.1
            components = dict(rise=signals.rise_ratio, diversity=sum(value > 0 for value in counts.values()) / 4,
                              code_velocity=min(log1p(signals.star_gain_7d) / log1p(10_000), 1),
                              volume=min(log1p(len(counted)) / log1p(50), 1))
            subtotal = sum(scoring["weights"][name] * value for name, value in components.items())
            penalty = scoring["yesterday_penalty"] * subtotal if history and history[-1].rank is not None else 0.0
            scores = Scores(**components, penalty=penalty, total=subtotal - penalty)
            history.append(TopicDay(date=today, rank=rank, item_ids=[item.id for item in current],
                                    count_7d=len(counted), signals=signals, scores=scores))
        synthesis = (
            f"Activity around {label.lower()} now spans research records, a code release, and a workflow announcement. "
            "The published analysis and its linked preprint describe the same work, so they contribute one published signal. "
            "An independent replication preprint adds a separate evaluation perspective, while the toolkit supplies shared inputs for comparison. "
            "The announcement describes a reference workflow using that evaluation protocol. Together these records motivate attention to "
            "reproducibility across implementations. They do not establish superiority on every dataset or demonstrate clinical performance; "
            "those conclusions would require evidence beyond the synthetic records included here."
        )
        if topic_index < 5:
            centroid = [float(i == topic_index) for i in range(5)]
        elif topic_index < 15:
            pair = list(combinations(range(5), 2))[topic_index - 5]
            centroid = [float(1 / Decimal(2).sqrt()) if i in pair else 0.0 for i in range(5)]
        elif topic_index < 20:
            centroid = [-float(i == topic_index - 15) for i in range(5)]
        else:
            pair = list(combinations(range(5), 2))[(topic_index - 20) % 10]
            centroid = [(-1 if topic_index < 30 or i == pair[1] else 1) * float(1 / Decimal(2).sqrt())
                        if i in pair else 0.0 for i in range(5)]
        topics.append(Topic(
            slug=slug, label=label, category=category, secondary_categories=secondary,
            centroid=centroid, history=history,
            headline=headline, summary=f"Research, a toolkit, and a workflow announcement connect {label.lower()} to reproducible evaluation.",
            synthesis=synthesis, synthesis_model="claude-opus-5-5" if topic_index < 5 else "claude-sonnet-5-5" if topic_index < 20 else "claude-haiku-5-5", synthesized_on=days[-1],
            item_one_liners={items[4].id: "Published evaluation with a linked preprint and shared analysis inputs."},
            related=[spec[0] for spec in specs if spec[0] != slug][:3],
        ))
    never_ranked = topics[4].model_copy(update={
        "slug": "never-ranked-fixture-0000", "label": "Never-ranked workflow fixture",
        "headline": "Never-ranked workflow fixture",
        "history": [entry.model_copy(update={"rank": None}) for entry in topics[4].history],
        "related": [],
    })
    topics[0].related[-1] = never_ranked.slug
    dump(never_ranked, topic_path(root / "data", "computational", never_ranked.slug))
    for topic in topics:
        dump(topic, topic_path(root / "data", "computational", topic.slug))
    for today in [days[0] - timedelta(days=1), *days]:
        ranked = []
        for topic in topics if today in days else []:
            entry = next(entry for entry in topic.history if entry.date == today)
            if entry.rank is None:
                continue
            ranked.append(RankedTopic(slug=topic.slug, rank=entry.rank, headline=topic.headline,
                                      summary=topic.summary, category=topic.category,
                                      signals=entry.signals, scores=entry.scores))
        started = datetime.combine(today, time(6), tzinfo=timezone.utc)
        run = RunInfo(started=started, finished=started + timedelta(minutes=2), status="ok" if ranked else "degraded",
                      backfilled=today <= days[0],
                      synthesis_model="claude-haiku-5-5" if today <= days[0] else "claude-opus-5-5",
                      source_status={source: "ok" for source in ("biorxiv", "arxiv", "pubmed", "github", "rss")})
        dump(Day(domain="computational", date=today, ranked=sorted(ranked, key=lambda row: row.rank), run=run),
             day_path(root / "data", "computational", today))
    notes = root / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "protein-design-binders-a1b2.md").write_text(
        "These **synthetic fixtures** illustrate linked evidence and continuous topic history.\n", encoding="utf-8")
    (notes / "nonexistent-topic-zzzz.md").write_text(
        "This deliberate orphan note verifies that a missing topic produces a warning, not a failed build.\n", encoding="utf-8")


if __name__ == "__main__":
    build(Path(__file__).resolve().parents[1] / "fixtures")
