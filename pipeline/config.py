from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class Category(BaseModel):
    slug: str
    label: str
    covers: str


class Taxonomy(BaseModel):
    domain: str
    categories: list[Category]

    def slugs(self) -> list[str]:
        return [category.slug for category in self.categories]


class Tier(BaseModel):
    to: int = Field(ge=1)
    model: str = Field(min_length=1)


class Scoring(BaseModel):
    weights: dict[str, float]
    yesterday_penalty: float = 0.05
    rise_k: int = 3
    rise_cap: float = 10.0
    history_days_for_own_baseline: int = 14
    cluster_distance_threshold: float = 0.10
    cluster_linkage: Literal['average', 'complete'] = 'complete'
    min_cluster_size: int = 3
    continuity_threshold: float = Field(default=0.95, ge=0, le=1)
    continuity_min_jaccard: float = Field(default=0.25, ge=0, le=1)
    continuity_max_gap_days: int = Field(default=10, ge=0)
    window_days: int = 7
    top_n: int = Field(default=40, ge=0)
    max_per_category: int = Field(default=8, ge=1)
    category_floor: int = Field(default=1, ge=0)
    featured_n: int = Field(default=5, ge=0)
    display_open_n: int = Field(default=20, ge=0)
    synthesis_tiers: list[Tier] = [
        Tier(to=5, model='claude-opus-5-5'),
        Tier(to=20, model='claude-sonnet-5-5'),
        Tier(to=40, model='claude-haiku-5-5'),
    ]
    backfill_synthesis_model: str = Field(default='claude-haiku-5-5', min_length=1)
    synthesis_max_items: int = Field(default=40, ge=1)
    synthesis_workers: int = Field(default=12, ge=1)
    monthly_ceiling_usd: float = 50.0
    degraded_fallback_min: int = 3
    degraded_fallback_rate: float = 0.2
    star_gain_threshold: int = 100

    @model_validator(mode='after')
    def validate_tiers(self):
        bounds = [tier.to for tier in self.synthesis_tiers]
        if not bounds or bounds != sorted(set(bounds)) or bounds[-1] < self.top_n:
            raise ValueError('synthesis tiers must increase and cover top_n')
        if self.display_open_n < self.featured_n:
            raise ValueError('display_open_n must include featured_n')
        return self


def load_taxonomy(domain: str, root: Path = Path("config")) -> Taxonomy:
    path = root / "taxonomy" / f"{domain}.yaml"
    return Taxonomy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_scoring(root: Path = Path("config")) -> Scoring:
    path = root / "scoring.yaml"
    return Scoring.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
