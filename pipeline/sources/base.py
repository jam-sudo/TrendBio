"""Source contract and shared HTTP policy; callers own the HTTP client."""

import logging
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
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


def request(client: httpx.Client, url: str, *, method: str = 'GET',
            attempts: int = 3, backoff: float = 1.0, **kwargs) -> httpx.Response:
    """Retry transient HTTP and transport failures without logging secrets."""
    if attempts < 1 or backoff < 0:
        raise ValueError('attempts must be positive and backoff nonnegative')
    for attempt in range(attempts):
        delay = backoff * 2 ** attempt
        try:
            response = client.request(method, url, follow_redirects=True, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 429 and exc.response.status_code < 500:
                raise
            if attempt == attempts - 1:
                raise
            retry_after = exc.response.headers.get('Retry-After')
            if retry_after:
                try:
                    seconds = float(retry_after)
                except ValueError:
                    try:
                        seconds = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError, OverflowError):
                        seconds = 0
                delay = max(delay, seconds)
        except httpx.TransportError:
            if attempt == attempts - 1:
                raise
        time.sleep(delay)
    raise AssertionError('unreachable')


def matches_keywords(text: str, keywords: list[str]) -> bool:
    text = text.casefold()
    return any(word.casefold() in text for word in keywords)


def collected(source: Source, items: list[Item]) -> list[Item]:
    logger.info('%s: collected %d items', source, len(items))
    return items
