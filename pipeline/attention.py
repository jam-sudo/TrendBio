"""Optional Bluesky attention; social identities and posts stay in memory."""

from collections import defaultdict
from datetime import date, timedelta
import os
import re
import time
from urllib.parse import unquote, urlsplit

import httpx

HOSTS = ("biorxiv.org", "medrxiv.org", "arxiv.org", "doi.org",
         "pubmed.ncbi.nlm.nih.gov", "nature.com")
SESSION = "com.atproto.server.createSession"
SEARCH = "app.bsky.feed.searchPosts"
MAX_CALLS = 1000
PAUSE = 0.3


class ProbeError(Exception):
    """Only non-secret diagnostics and API error/message fields belong here."""


class BudgetStop(Exception):
    pass


def normalize(value):
    """Return a DOI, arxiv:ID or pmid:ID; never return arbitrary link text."""
    if not isinstance(value, str):
        return None
    value = unquote(value.strip()).casefold()
    # Ignore query/fragment tracking before matching identifiers.
    value = value.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    match = re.search(r"(?:arxiv\.org/(?:abs|pdf|html)/|arxiv:)([a-z.-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$", value)
    if match:
        return "arxiv:" + match[1]
    match = re.search(r"(?:pubmed\.ncbi\.nlm\.nih\.gov/|pmid:|pubmed:)(\d+)$", value)
    if match:
        return "pmid:" + match[1]
    match = re.search(r"(?:www\.)?nature\.com/articles/([a-z0-9.-]+)(?:\.pdf)?$", value)
    if match:
        value = "10.1038/" + match[1].removesuffix(".pdf")
    match = re.search(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", value)
    if match:
        return re.sub(r"(?:v\d+|\.full(?:\.pdf)?|\.abstract)+$", "", match[0])
    return None


def extract_links(post):
    record = post.get("record", {})
    links = {
        feature["uri"]
        for facet in record.get("facets", [])
        for feature in facet.get("features", [])
        if feature.get("$type") == "app.bsky.richtext.facet#link"
        and isinstance(feature.get("uri"), str)
    }
    # Inspect only this post's external media, never the text/links of quoted posts.
    for embed in (record.get("embed", {}), post.get("embed", {})):
        if embed.get("$type", "").startswith("app.bsky.embed.recordWithMedia"):
            embed = embed.get("media", {})
        if embed.get("$type", "").startswith("app.bsky.embed.external"):
            uri = embed.get("external", {}).get("uri")
            if isinstance(uri, str):
                links.add(uri)
    return links


def links_to_host(post, host):
    for link in extract_links(post):
        parsed = urlsplit(link)
        hostname = (parsed.hostname or "").rstrip(".")
        if parsed.scheme in {"http", "https"} and (hostname == host or hostname.endswith("." + host)):
            return True
    return False


def search_params(host, start, end, form):
    params = {"q": form.format(host=host), "sort": "latest", "since": start,
              "until": end, "limit": 100}
    if form != "domain:{host}":
        params["domain"] = host
    return params


def item_index(items):
    index = defaultdict(set)
    for item_id, item in items.items():
        values = [item.get(key) for key in ("id", "doi", "url", "published_doi", "preprint_id")]
        pmid = item.get("metadata", {}).get("pmid")
        if pmid:
            values.append(f"pmid:{pmid}")
        for value in values:
            key = normalize(value)
            if key:
                index[key].add(item_id)
    return index


def empty_stats():
    return {"posts": 0, "authors": set(), "engagement": 0}


def prefix_group(key):
    if key.startswith("10.1038/d41586-") or key.startswith("pmid:"):
        return None
    if key.startswith(("10.1101/", "10.64898/")):
        return "bioRxiv or medRxiv DOIs"
    if key.startswith("arxiv:"):
        return "arXiv ids"
    return "other DOIs"


class Attention:
    def __init__(self, items):
        self.index = item_index(items)
        self.items = defaultdict(empty_stats)
        self.unknown = defaultdict(empty_stats)
        self.seen = set()
        self.unknown_posts = 0
        self.author_ids = defaultdict(set)
        self.posts = []

    def add(self, post):
        uri = post["uri"]
        if uri in self.seen:
            return
        self.seen.add(uri)
        keys = {key for link in extract_links(post) if (key := normalize(link))}
        author = post["author"]["did"]
        self.author_ids[author].update(keys)
        matched = set().union(*(self.index.get(key, set()) for key in keys))
        unknown = {key for key in keys if key not in self.index and prefix_group(key)}
        engagement = sum(post.get(field, 0) for field in ("likeCount", "repostCount", "quoteCount"))
        self.posts.append((author, matched, unknown, engagement))
        self.unknown_posts += bool(unknown)
        for stats in ([self.items[key] for key in matched] + [self.unknown[key] for key in unknown]):
            stats["posts"] += 1
            stats["authors"].add(author)
            stats["engagement"] += engagement

    def non_automated(self, threshold):
        automated = {author for author, keys in self.author_ids.items() if len(keys) >= threshold}
        items, unknown = defaultdict(empty_stats), defaultdict(empty_stats)
        automated_posts = 0
        for author, matched, outside, engagement in self.posts:
            if author in automated:
                automated_posts += 1
                continue
            for stats in ([items[key] for key in matched] + [unknown[key] for key in outside]):
                stats["posts"] += 1
                stats["authors"].add(author)
                stats["engagement"] += engagement
        return items, unknown, len(automated), automated_posts


class Bluesky:
    def __init__(self, client, sleep=time.sleep, max_calls=MAX_CALLS):
        self.client = client
        self.sleep = sleep
        self.max_calls = min(max_calls, MAX_CALLS)
        self.calls = 0
        self.session_calls = 0
        self.host = "https://bsky.social"
        self.headers = {}

    def request(self, method, call, **kwargs):
        try:
            return self.client.request(method, f"{self.host}/xrpc/{call}", **kwargs)
        except httpx.RequestError:
            raise ProbeError(f"{call}: network failure (HTTP status unavailable)") from None

    @staticmethod
    def payload(response, call):
        if response.status_code != 200:
            detail = ""
            try:
                data = response.json()
                if isinstance(data, dict):
                    detail = "; ".join(f"{key}: {data[key]}" for key in ("error", "message")
                                       if isinstance(data.get(key), str))[:200]
            except ValueError:
                pass
            raise ProbeError(f"{call}: HTTP {response.status_code}" + (f", {detail}" if detail else ""))
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except ValueError:
            raise ProbeError(f"{call}: HTTP 200, invalid JSON response") from None

    def login(self, handle, password):
        self.session_calls += 1
        response = self.request("POST", SESSION, json={"identifier": handle, "password": password})
        data = self.payload(response, SESSION)
        token = data.get("accessJwt")
        if not isinstance(token, str) or not token:
            raise ProbeError(f"{SESSION}: HTTP 200, missing access token")
        for service in data.get("didDoc", {}).get("service", []):
            if service.get("id", "").endswith("#atproto_pds"):
                host = service.get("serviceEndpoint", "")
                parsed = urlsplit(host)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise ProbeError(f"{SESSION}: HTTP 200, invalid session host")
                self.host = host.rstrip("/")
                break
        self.headers = {"Authorization": f"Bearer {token}"}

    def search_response(self, params):
        if self.calls >= self.max_calls:
            raise BudgetStop
        self.sleep(PAUSE)
        self.calls += 1  # Failed calls and retries consume the same budget.
        return self.request("GET", SEARCH, params=params, headers=self.headers)

    def search(self, params):
        for attempt in range(5):
            response = self.search_response(params)
            if response.status_code == 429 and attempt < 4:
                try:
                    retry_after = float(response.headers.get("Retry-After", "0"))
                except ValueError:
                    retry_after = 0
                delay = max(2 ** (attempt + 1), retry_after)
                if delay > 60:
                    raise ProbeError(f"{SEARCH}: HTTP 429, retry delay exceeds 60 seconds")
                self.sleep(delay)
                continue
            data = self.payload(response, SEARCH)
            if not isinstance(data.get("posts"), list):
                raise ProbeError(f"{SEARCH}: HTTP 200, missing posts array")
            return data


def sweep(api, attention, start, end, form):
    states = {host: {"posts": 0, "calls": 0, "status": "pending", "partial": False,
                     "cursor": None, "cursors": set(), "seen": set(), "hits": 0} for host in HOSTS}
    error = None
    # Round-robin pages prevent the first busy host from consuming the whole budget.
    while any(state["status"] == "pending" for state in states.values()):
        for host, state in states.items():
            if state["status"] != "pending":
                continue
            params = search_params(host, start, end, form)
            if state["cursor"]:
                params["cursor"] = state["cursor"]
            before = api.calls
            try:
                page = api.search(params)
                posts = page["posts"]
                for post in posts:
                    if links_to_host(post, host):
                        attention.add(post)
                    state["seen"].add(post["uri"])
                state["posts"] = len(state["seen"])
                state["hits"] = max(state["hits"], page.get("hitsTotal") or 0)
                cursor = page.get("cursor")
                if cursor and cursor not in state["cursors"] and posts:
                    state["cursors"].add(cursor)
                    state["cursor"] = cursor
                else:
                    state["partial"] = bool(cursor) or state["hits"] > state["posts"] or len(posts) == 100
                    state["status"] = "cursor limit" if state["partial"] else "cursor end"
            except BudgetStop:
                state["status"], state["partial"] = "budget limit", True
            except (ProbeError, KeyError, TypeError, ValueError, AttributeError) as exc:
                # Only ProbeError may expose the API's error/message fields.
                error = str(exc) if isinstance(exc, ProbeError) else f"{SEARCH}: HTTP 200, malformed post response"
                state["status"], state["partial"] = "request failed", True
            finally:
                state["calls"] += api.calls - before
            if error or api.calls >= api.max_calls:
                for remaining in states.values():
                    if remaining["status"] == "pending":
                        remaining["status"] = "request failed" if error else "budget limit"
                        remaining["partial"] = True
                return states, error
    return states, error


def sweep_days(api, attention, start, end):
    """Search [start, end) in UTC day slices; publish only aggregate host coverage."""
    hosts = {host: {"partial": False, "truncated_days": []} for host in HOSTS}
    current = start
    try:
        while current < end:
            following = current + timedelta(days=1)
            states, error = sweep(api, attention, current.isoformat(), following.isoformat(), "*")
            for host, state in states.items():
                hosts[host]["partial"] |= state["partial"]
                if state["status"] == "cursor limit":
                    hosts[host]["truncated_days"].append(current.isoformat())
            current = following
            if error or (api.calls >= api.max_calls and current < end):
                for host in hosts.values():
                    host["partial"] = True
                break
    except Exception:
        # Preserve usable aggregates even when an unexpected response ends the sweep.
        for host in hosts.values():
            host["partial"] = True
    return hosts


def collect_attention(day, store, cfg, client):
    handle, password = os.getenv("BLUESKY_HANDLE"), os.getenv("BLUESKY_APP_PASSWORD")
    if not handle or not password:
        return None
    items = {item.id: item.model_dump() for item in store.items_between(date.min, day)}
    attention = Attention(items)
    api = Bluesky(client, max_calls=cfg.max_search_calls)
    api.login(handle, password)
    start = day - timedelta(days=cfg.window_days - 1)
    hosts = sweep_days(api, attention, start, day + timedelta(days=1))
    partial = any(host["partial"] for host in hosts.values())
    if partial and not attention.posts:
        return None
    filtered, _, automated, automated_posts = attention.non_automated(cfg.automated_min_ids)
    papers = [
        {"item_id": key, "engagement": stats["engagement"], "authors": len(stats["authors"])}
        for key, stats in filtered.items()
        if items[key].get("relevant") is True
        and items[key]["type"] in {"preprint", "published"}
        and stats["engagement"] >= cfg.min_engagement
    ]
    papers.sort(key=lambda paper: (-paper["engagement"], -paper["authors"], paper["item_id"]))
    return {
        "date": day.isoformat(), "window_start": start.isoformat(), "partial": partial,
        "search_calls": api.calls, "posts_swept": len(attention.posts),
        "automated_accounts": automated,
        "automated_post_share": automated_posts / len(attention.posts) if attention.posts else 0,
        "hosts": hosts, "papers": papers[:cfg.store_top_n],
    }
