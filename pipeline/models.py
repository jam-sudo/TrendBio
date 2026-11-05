from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ItemType = Literal["published", "preprint", "code", "industry"]
Source = Literal["biorxiv", "arxiv", "pubmed", "github", "rss"]


class Item(BaseModel):
    id: str
    source: Source
    type: ItemType
    title: str
    url: str
    doi: str | None
    published_at: date
    first_seen: date
    authors: list[str]
    org: str | None
    abstract: str
    summary: str | None
    primary_category: str | None
    secondary_categories: list[str] = []
    relevant: bool = True
    published_doi: str | None
    preprint_id: str | None
    metadata: dict[str, Any] = {}


class Signals(BaseModel):
    published: int
    preprint: int
    code: int
    industry: int
    rise_ratio: float
    star_gain_7d: int


class Scores(BaseModel):
    rise: float
    diversity: float
    code_velocity: float
    volume: float
    penalty: float
    total: float


class TopicDay(BaseModel):
    date: date
    rank: int | None
    item_ids: list[str]
    attached_item_ids: list[str] = []
    count_7d: int
    signals: Signals
    scores: Scores


class Topic(BaseModel):
    slug: str
    label: str
    category: str
    secondary_categories: list[str]
    centroid: list[float]
    history: list[TopicDay]
    headline: str | None
    summary: str | None
    synthesis: str | None
    synthesis_model: str | None
    synthesized_on: date | None
    item_one_liners: dict[str, str] = {}
    related: list[str] = []


class RankedTopic(BaseModel):
    slug: str
    rank: int
    headline: str
    summary: str
    category: str
    signals: Signals
    scores: Scores


class RunInfo(BaseModel):
    started: datetime
    finished: datetime
    status: Literal["ok", "degraded"]
    backfilled: bool
    synthesis_model: str
    source_status: dict[str, Literal["ok", "failed", "skipped"]]
    notes: list[str] = []


class Day(BaseModel):
    domain: str
    date: date
    ranked: list[RankedTopic]
    run: RunInfo


class MapData(BaseModel):
    class Point(BaseModel):
        slug: str
        label: str
        headline: str
        category: str
        x: float = Field(ge=0, le=1)
        y: float = Field(ge=0, le=1)
        size: int = Field(ge=0)
        first_ranked: date
        last_ranked: date
        months: list[str]
        neighbors: list[str]

    generated_on: date
    method: Literal["umap"]
    points: list[Point]
