#!/usr/bin/env python3
"""Read-only Bluesky attention measurement; only aggregate output leaves memory.

Lexicon: https://github.com/bluesky-social/atproto/blob/main/packages/bsky/lexicons/app/bsky/feed/searchPosts.json
Verified 2026-11-05: required q; sort (latest/top), since (inclusive), until
(exclusive), mentions, author, lang, domain, url, tag, limit (1..100), cursor.
Dates filter sortAt, not necessarily createdAt; pagination can truncate results.
"""

import argparse
from collections import defaultdict
from datetime import date, timedelta
import html
import json
import math
import os
from pathlib import Path
import re
import statistics
import time
from urllib.parse import unquote, urlsplit

import httpx

HOSTS = ("biorxiv.org", "medrxiv.org", "arxiv.org", "doi.org",
         "pubmed.ncbi.nlm.nih.gov", "nature.com")
SESSION = "com.atproto.server.createSession"
SEARCH = "app.bsky.feed.searchPosts"
MAX_CALLS = 1000
PAUSE = 0.3
QUERY_FORMS = ("*", "domain:{host}", "{host}")


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


class Attention:
    def __init__(self, items):
        self.index = item_index(items)
        self.items = defaultdict(empty_stats)
        self.unknown = defaultdict(empty_stats)
        self.seen = set()
        self.unknown_posts = 0

    def add(self, post):
        uri = post["uri"]
        if uri in self.seen:
            return
        self.seen.add(uri)
        keys = {key for link in extract_links(post) if (key := normalize(link))}
        matched = set().union(*(self.index.get(key, set()) for key in keys))
        unknown = {key for key in keys if key not in self.index and not key.startswith("pmid:")}
        self.unknown_posts += bool(unknown)
        for stats in ([self.items[key] for key in matched] + [self.unknown[key] for key in unknown]):
            stats["posts"] += 1
            stats["authors"].add(post["author"]["did"])
            stats["engagement"] += post.get("likeCount", 0) + post.get("repostCount", 0)


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


def preflight(api, start, end):
    selected, results = None, []
    for form in QUERY_FORMS:
        params = search_params(HOSTS[0], start, end, form)
        result = {"q": params["q"], "domain": params.get("domain", "—"), "status": "unavailable",
                  "posts": 0, "linked": 0, "error": "", "selected": False}
        results.append(result)
        try:
            response = api.search_response(params)  # One call per form, without retries.
            result["status"] = response.status_code
            data = api.payload(response, SEARCH)
            if not isinstance(data.get("posts"), list):
                raise ProbeError(f"{SEARCH}: HTTP 200, missing posts array")
            result["posts"] = len(data["posts"])
            result["linked"] = sum(links_to_host(post, HOSTS[0]) for post in data["posts"])
            if selected is None and result["linked"]:
                selected, result["selected"] = form, True
        except BudgetStop:
            result["error"] = "Search call budget exhausted"
        except (ProbeError, KeyError, TypeError, ValueError, AttributeError) as exc:
            result["error"] = str(exc) if isinstance(exc, ProbeError) else f"{SEARCH}: HTTP 200, malformed post response"
    return selected, results


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


def spearman(xs, ys):
    def ranks(values):
        order = sorted(range(len(values)), key=values.__getitem__)
        result = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i + 1
            while j < len(order) and values[order[i]] == values[order[j]]:
                j += 1
            for position in order[i:j]:
                result[position] = (i + j + 1) / 2
            i = j
        return result

    if len(xs) != len(ys) or len(xs) < 2:
        return None
    x, y = ranks(xs), ranks(ys)
    mx, my = statistics.mean(x), statistics.mean(y)
    denominator = math.sqrt(sum((v - mx) ** 2 for v in x) * sum((v - my) ** 2 for v in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / denominator if denominator else None


def load_store(root, days):
    day_paths = sorted((root / "days").glob("*.json"))
    latest = max(date.fromisoformat(path.stem) for path in day_paths)
    start = latest - timedelta(days=days - 1)
    items = {}
    for path in (root / "items").rglob("*.json"):
        item = json.loads(path.read_text())
        items[item["id"]] = item
    rows = []
    for path in (root / "topics").glob("*.json"):
        topic = json.loads(path.read_text())
        for entry in topic["history"]:
            rank = entry.get("rank")
            if start.isoformat() <= entry["date"] <= latest.isoformat() and rank is not None and 1 <= rank <= 40:
                rows.append({"rank": rank, "item_ids": set(entry["item_ids"]) | set(entry.get("attached_item_ids", []))})
    return items, rows, start.isoformat(), (latest + timedelta(days=1)).isoformat()


def share(count, total):
    return f"{count}/{total} ({count / total:.1%})" if total else "0/0 (n/a)"


def render_report(items, rows, attention, states, start, end, calls, session_calls=1, error=None, preflight_results=()):
    partial = bool(error) or any(state["partial"] for state in states.values())
    lines = ["# Bluesky attention probe", f"Window: {start} inclusive to {end} exclusive (UTC).",
             f"Search calls: {calls}/{MAX_CALLS}; session calls: {session_calls}.",
             f"Partial results: {'YES — counts may undercount.' if partial else 'no detected truncation.'}"]
    if error:
        lines.append(f"Failure: {error}")
    if preflight_results:
        lines += ["", f"## Query preflight ({HOSTS[0]})", "One call per form; included in the search call budget. Host-linked posts require a facet or external embed link.",
                  "", "| Query | Domain parameter | HTTP | Posts | Host-linked posts | Result |",
                  "|---|---|---:|---:|---:|---|"]
        for result in preflight_results:
            diagnostic = html.escape(" ".join(result["error"].split())).replace("|", "&#124;")
            lines.append(f"| {result['q']} | {result['domain']} | {result['status']} | {result['posts']} | {result['linked']} | {diagnostic or ('selected' if result['selected'] else 'not selected')} |")
    lines += ["", "| Host | Search calls | Unique posts swept | Stop | Undercount flag |",
              "|---|---:|---:|---|---|"]
    for host, state in states.items():
        lines.append(f"| {host} | {state['calls']} | {state['posts']} | {state['status']} | {'yes' if state['partial'] else 'no detected truncation'} |")
    lines += ["", "Search uses sortAt, which may differ from post creation time. Cursor end is not proof of complete coverage; the search index and pagination may omit posts. Counts deduplicate post URIs across hosts; author DIDs stay in memory. Likes plus reposts are current totals on the matched posts, not events restricted to the window.",
              "", "## Relevant window papers", "Stored relevant paper records with published_at in the window (linked preprint/publication records remain separate). Zero-attention records are included in distributions; p90 uses nearest rank.",
              "", "| Source | Papers | At least 1 post | At least 3 authors | Authors median / p90 / max |", "|---|---:|---|---|---|"]
    papers = {key: item for key, item in items.items() if item.get("relevant") and item.get("type") in {"preprint", "published"} and start <= item["published_at"] < end}
    for source in ("all", "biorxiv", "arxiv", "pubmed"):
        subset = [attention.items[key] for key, item in papers.items() if source == "all" or item["source"] == source]
        authors = sorted(len(stats["authors"]) for stats in subset)
        distribution = f"{statistics.median(authors):g} / {authors[math.ceil(.9 * len(authors)) - 1]} / {max(authors)}" if authors else "n/a"
        lines.append(f"| {source} | {len(subset)} | {share(sum(s['posts'] > 0 for s in subset), len(subset))} | {share(sum(a >= 3 for a in authors), len(subset))} | {distribution} |")
    observations = []
    best_ranks = {}
    for row in rows:
        stats = [attention.items[key] for key in row["item_ids"]]
        authors = set().union(*(s["authors"] for s in stats))
        observations.append((row["rank"], any(s["posts"] for s in stats), len(authors)))
        for key in row["item_ids"]:
            best_ranks[key] = min(best_ranks.get(key, 41), row["rank"])
    lines += ["", "## Top 40 rows", "Each topic/date is one observation; all rows use attention over the whole window (descriptive, not a predictive backtest). Linked means at least one item with a matched post; authors are unioned across item_ids and attached_item_ids.",
              "", "| Ranks | Rows | At least 1 linked item | At least 3 authors |", "|---|---:|---|---|"]
    for low, high in ((1, 5), (6, 20), (21, 40)):
        group = [row for row in observations if low <= row[0] <= high]
        lines.append(f"| {low}-{high} | {len(group)} | {share(sum(row[1] for row in group), len(group))} | {share(sum(row[2] >= 3 for row in group), len(group))} |")
    correlation = spearman([row[0] for row in observations], [row[2] for row in observations])
    lines += ["", f"Spearman(rank, distinct authors): {f'{correlation:.4f}' if correlation is not None else 'undefined (too few rows or constant values)'}; n={len(observations)}. Ties use average ranks; negative means more attention at better ranks.",
              "", "## Top 15 most shared relevant papers", "| Paper | Distinct authors | Likes + reposts | Best rank |", "|---|---:|---:|---|"]
    shared = [key for key, item in items.items() if item.get("relevant") and item.get("type") in {"preprint", "published"} and attention.items[key]["posts"]]
    for key in sorted(shared, key=lambda key: (-len(attention.items[key]["authors"]), key))[:15]:
        stats = attention.items[key]
        title = html.escape(" ".join(items[key]["title"].split())).replace("|", "&#124;")
        lines.append(f"| {title} | {len(stats['authors'])} | {stats['engagement']} | {best_ranks.get(key, 'not ranked')} |")
    lines += ["", "## Attention outside the store", f"{attention.unknown_posts} unique posts link to at least one normalized DOI/arXiv ID absent from the store ({len(attention.unknown)} distinct IDs). Top 10 IDs by distinct authors:"]
    for key in sorted(attention.unknown, key=lambda key: (-len(attention.unknown[key]["authors"]), key))[:10]:
        lines.append(f"- {key}")
    top20 = [row for row in observations if row[0] <= 20]
    lines += ["", f"Verdict: {share(sum(row[2] >= 3 for row in top20), len(top20))} of ranks 1-20 rows have at least 3 distinct authors; {'partial coverage, a lower bound' if partial else 'observed coverage only'}, not evidence of ranking improvement."]
    return "\n".join(lines) + "\n"


def emit(report):
    print(report)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as summary:
            summary.write(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be a positive integer")
    handle, password = os.environ.get("BLUESKY_HANDLE"), os.environ.get("BLUESKY_APP_PASSWORD")
    if not handle or not password:
        emit(f"Probe failed before {SESSION}: set BLUESKY_HANDLE and BLUESKY_APP_PASSWORD; no HTTP call made.")
        return 1
    try:
        items, rows, start, end = load_store(Path(__file__).resolve().parents[2] / "data/computational", args.days)
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        emit("Probe failed: unable to read the stored items, topic histories or latest day/window; no HTTP call made.")
        return 1
    attention = Attention(items)
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        api = Bluesky(client)
        try:
            api.login(handle, password)
        except (ProbeError, ValueError, TypeError, AttributeError) as exc:
            error = str(exc) if isinstance(exc, ProbeError) else f"{SESSION}: HTTP 200, malformed session response"
            emit(f"Probe failed: {error}; search calls: 0; no attention measurement available.")
            return 1
        form, preflight_results = preflight(api, start, end)
        if form is None:
            states, error = {}, "No search query form returned HTTP 200 with a verified link to the first host; sweep not started."
        else:
            states, error = sweep(api, attention, start, end, form)
    emit(render_report(items, rows, attention, states, start, end, api.calls, api.session_calls, error, preflight_results))
    return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(main())
