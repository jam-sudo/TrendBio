"""Source contract and shared HTTP policy; callers own the HTTP client."""

import logging
from datetime import date
from pathlib import Path
import time
from typing import Protocol

import httpx
import yaml

from pipeline.models import Item, Source

logger = logging.getLogger(__name__)


class SourceAdapter(Protocol):
    name: Source

    def fetch(self, start: date, end: date, client: httpx.Client) -> list[Item]: ...


def load_config() -> dict:
    path = Path(__file__).resolve().parents[2] / 'config/sources/computational.yaml'
    return yaml.safe_load(path.read_text(encoding='utf-8'))


def request(client: httpx.Client, url: str, *, method: str = 'GET', **kwargs) -> httpx.Response:
    """Three total attempts, including transport failures, without logging secrets."""
    for attempt in range(3):
        try:
            response = client.request(method, url, follow_redirects=True, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 429 and exc.response.status_code < 500:
                raise
            if attempt == 2:
                raise
        except httpx.TransportError:
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)
    raise AssertionError('unreachable')


def matches_keywords(text: str, keywords: list[str]) -> bool:
    text = text.casefold()
    return any(word.casefold() in text for word in keywords)


def collected(source: Source, items: list[Item]) -> list[Item]:
    logger.info('%s: collected %d items', source, len(items))
    return items
