from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class Category(BaseModel):
    slug: str
    label: str
    covers: str


class Taxonomy(BaseModel):
    domain: str
    categories: list[Category]

    def slugs(self) -> list[str]:
        return [category.slug for category in self.categories]


class Scoring(BaseModel):
    weights: dict[str, float]
    yesterday_penalty: float = 0.05
    rise_k: int = 3
    rise_cap: float = 10.0
    history_days_for_own_baseline: int = 14
    cluster_distance_threshold: float = 0.10
    cluster_linkage: Literal['average', 'complete'] = 'complete'
    min_cluster_size: int = 3
    continuity_threshold: float = 0.80
    window_days: int = 7
    top_n: int = 5
    synthesis_max_items: int = Field(default=40, ge=1)
    monthly_ceiling_usd: float = 50.0
    star_gain_threshold: int = 100


def load_taxonomy(domain: str, root: Path = Path("config")) -> Taxonomy:
    path = root / "taxonomy" / f"{domain}.yaml"
    return Taxonomy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_scoring(root: Path = Path("config")) -> Scoring:
    path = root / "scoring.yaml"
    return Scoring.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
