from datetime import date, datetime, timedelta
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

ItemType = Literal["published", "preprint", "code", "industry"]
Source = Literal["biorxiv", "arxiv", "pubmed", "github", "rss", "crossref", "drops", "oai", "europepmc", "worldbank", "thoth", "openedition"]


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

    def can_quote_in_english(self) -> bool:
        language = self.metadata.get('abstract_language') or self.metadata.get('language')
        if language:
            code = str(language).strip().lower().replace('_', '-').split('-')[0]
            return code in {'en', 'eng', 'english'}
        if self.source in {'crossref', 'europepmc', 'oai', 'openedition', 'thoth'}:
            return False
        return not re.search(r'[가-힣ㄱ-ㅎㅏ-ㅣᄀ-ᇿ]', self.title + self.abstract)


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
    category: str | None = None
    research_question: str | None = Field(default=None, exclude_if=lambda question: question is None)
    result_passages: dict[str, str] = Field(default_factory=dict, exclude_if=lambda passages: not passages)
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
    synthesis: str | None = None
    category: str
    signals: Signals
    scores: Scores


class RunInfo(BaseModel):
    started: datetime
    finished: datetime
    status: Literal["ok", "degraded"]
    backfilled: bool
    window_days: int = Field(default=7, ge=1)
    model_cost_usd: float | None = Field(default=None, ge=0)
    synthesis_model: str
    source_status: dict[str, Literal["ok", "partial", "failed", "skipped"]]
    notes: list[str] = []


class Day(BaseModel):
    domain: str
    date: date
    ranked: list[RankedTopic]
    run: RunInfo

    @property
    def window_start(self) -> date:
        return self.date - timedelta(days=self.run.window_days - 1)


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
