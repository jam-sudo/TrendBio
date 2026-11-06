import importlib.util
import json
from pathlib import Path

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location("bluesky_probe", Path(__file__).parents[1] / "ops/bluesky-probe/probe.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


@pytest.fixture
def items():
    return {
        "biorxiv:10.1101/2026.11.01.123456": {
            "id": "biorxiv:10.1101/2026.11.01.123456", "doi": "10.1101/2026.11.01.123456",
            "published_doi": "10.1038/s41586-026-12345-6", "title": "A paper | with a title",
            "source": "biorxiv", "type": "preprint", "relevant": True,
            "published_at": "2026-11-01", "metadata": {"pmid": "12345"},
        },
        "arxiv:2611.00001": {
            "id": "arxiv:2611.00001", "title": "Another paper", "source": "arxiv",
            "type": "preprint", "relevant": True, "published_at": "2026-11-02",
        },
    }


def post(uri="at://did:plc:private/app.bsky.feed.post/private", author="did:plc:private", links=None):
    return {
        "uri": uri, "author": {"did": author, "handle": "private-person.bsky.social"},
        "record": {"text": "PRIVATE FIXTURE POST TEXT", "facets": [
            {"features": [{"$type": "app.bsky.richtext.facet#link", "uri": link}]} for link in (
                links if links is not None else ["https://www.nature.com/articles/s41586-026-12345-6"])
        ]}, "likeCount": 4, "repostCount": 2,
    }


@pytest.mark.parametrize(("value", "expected"), [
    ("https://www.biorxiv.org/content/10.1101/2026.11.01.123456v1", "10.1101/2026.11.01.123456"),
    ("https://www.medrxiv.org/content/10.1101/2026.11.01.123456v12.full.pdf?foo=bar#x", "10.1101/2026.11.01.123456"),
    ("10.1101/2026.11.01.123456.full", "10.1101/2026.11.01.123456"),
    ("10.1101/2026.11.01.123456v2.abstract", "10.1101/2026.11.01.123456"),
    ("https://doi.org/10.1000%2FABC.DEF", "10.1000/abc.def"),
    ("pubmed:10.1000/ABC", "10.1000/abc"),
    ("https://arxiv.org/abs/2611.00001v3", "arxiv:2611.00001"),
    ("https://arxiv.org/pdf/2611.00001v2.pdf", "arxiv:2611.00001"),
    ("https://arxiv.org/html/2611.00001v1", "arxiv:2611.00001"),
    ("arxiv:2611.00001v2", "arxiv:2611.00001"),
    ("https://arxiv.org/abs/q-bio/0601001v2", "arxiv:q-bio/0601001"),
    ("https://pubmed.ncbi.nlm.nih.gov/12345/", "pmid:12345"),
    ("https://www.nature.com/articles/S41586-026-12345-6.pdf", "10.1038/s41586-026-12345-6"),
    (None, None), ("https://example.com/no-paper", None),
])
def test_normalization(value, expected):
    assert probe.normalize(value) == expected


def test_link_extraction_facets_and_embeds():
    fixture = post(links=["https://doi.org/10.1000/facet"])
    fixture["record"]["facets"].append({"features": [{"$type": "app.bsky.richtext.facet#mention", "did": "did:plc:ignore"}]})
    fixture["record"]["embed"] = {"$type": "app.bsky.embed.external", "external": {"uri": "https://doi.org/10.1000/record"}}
    fixture["embed"] = {"$type": "app.bsky.embed.recordWithMedia#view", "media": {
        "$type": "app.bsky.embed.external#view", "external": {"uri": "https://arxiv.org/abs/2611.00001"}},
        "record": {"uri": "https://doi.org/10.1000/quoted"}}
    assert probe.extract_links(fixture) == {"https://doi.org/10.1000/facet", "https://doi.org/10.1000/record", "https://arxiv.org/abs/2611.00001"}
    fixture["record"]["embed"] = {"$type": "app.bsky.embed.recordWithMedia", "media": {
        "$type": "app.bsky.embed.external", "external": {"uri": "https://doi.org/10.1000/media"}}}
    assert "https://doi.org/10.1000/media" in probe.extract_links(fixture)


def test_published_doi_pmid_and_preprint_joins(items):
    index = probe.item_index(items)
    key = next(iter(items))
    assert index["10.1038/s41586-026-12345-6"] == {key}
    assert index["pmid:12345"] == {key}
    published = {"id": "pubmed:10.1000/published", "preprint_id": key}
    items[published["id"]] = published
    assert probe.item_index(items)["10.1101/2026.11.01.123456"] == {key, published["id"]}


def test_distinct_authors_and_no_double_counting(items):
    attention = probe.Attention(items)
    first = post()
    attention.add(first)
    attention.add(first)
    attention.add(post(uri="second"))
    attention.add(post(uri="third", author="did:plc:second"))
    stats = attention.items[next(iter(items))]
    assert stats == {"posts": 3, "authors": {"did:plc:private", "did:plc:second"}, "engagement": 18}
    unknown = post(uri="unknown", links=["https://doi.org/10.1000/unknown", "https://arxiv.org/abs/2611.99999v2"])
    attention.add(unknown)
    attention.add(unknown)
    assert attention.unknown_posts == 1
    assert len(attention.unknown) == 2


def test_spearman_known_case_and_ties():
    assert probe.spearman([1, 2, 3, 4, 5], [5, 6, 7, 8, 7]) == pytest.approx(0.8207826816681233)
    assert probe.spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1)
    assert probe.spearman([1, 2, 3], [0, 0, 0]) is None
    assert probe.spearman([], []) is None


def api_with(handler, budget=1000):
    sleeps = []
    api = probe.Bluesky(httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append, max_calls=budget)
    return api, sleeps


def test_session_host_and_search_parameters(items):
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path.endswith(probe.SESSION):
            assert json.loads(request.content) == {"identifier": "private-handle", "password": "secret-password"}
            return httpx.Response(200, json={"accessJwt": "secret-token", "didDoc": {"service": [
                {"id": "did:plc:private#atproto_pds", "serviceEndpoint": "https://session-host.test"}]}})
        assert request.url.host == "session-host.test"
        assert request.headers["Authorization"] == "Bearer secret-token"
        assert dict(request.url.params) == {"q": "*", "domain": probe.HOSTS[len(calls) - 2], "sort": "latest", "since": "2026-10-30", "until": "2026-11-06", "limit": "100"}
        return httpx.Response(200, json={"posts": []})
    api, sleeps = api_with(handler)
    api.login("private-handle", "secret-password")
    states, error = probe.sweep(api, probe.Attention(items), "2026-10-30", "2026-11-06", "*")
    assert api.session_calls == 1 and api.calls == 6
    assert len(sleeps) == 6 and min(sleeps) > 0
    assert error is None and all(s["status"] == "cursor end" for s in states.values())


def test_budget_stop_reports_partial_and_deduplicates_hosts(items):
    api, _ = api_with(lambda _: httpx.Response(200, json={"posts": [post(links=[
        "https://www.biorxiv.org/content/10.1101/2026.11.01.123456",
        "https://www.medrxiv.org/content/10.1101/2026.11.01.123456"])], "cursor": "next"}), budget=2)
    attention = probe.Attention(items)
    states, error = probe.sweep(api, attention, "2026-10-30", "2026-11-06", "*")
    assert api.calls == 2 and error is None
    assert all(s["partial"] and s["status"] == "budget limit" for s in states.values())
    assert attention.items[next(iter(items))]["posts"] == 1
    report = probe.render_report(items, [], attention, states, "2026-10-30", "2026-11-06", api.calls)
    assert "Partial results: YES" in report


def test_cursor_limit_and_repeated_cursor(items):
    api, _ = api_with(lambda _: httpx.Response(200, json={"posts": [post()], "cursor": "same"}))
    states, error = probe.sweep(api, probe.Attention(items), "2026-10-30", "2026-11-06", "*")
    assert api.calls == 12 and error is None
    assert all(s["partial"] and s["status"] == "cursor limit" for s in states.values())
    api, _ = api_with(lambda _: httpx.Response(200, json={"posts": [post()], "hitsTotal": 200}))
    states, _ = probe.sweep(api, probe.Attention(items), "2026-10-30", "2026-11-06", "*")
    assert all(s["partial"] for s in states.values())


def test_429_backoff_consumes_budget(items):
    api, sleeps = api_with(lambda _: httpx.Response(429, headers={"Retry-After": "3"}, text="secret-body"), budget=2)
    states, error = probe.sweep(api, probe.Attention(items), "2026-10-30", "2026-11-06", "*")
    assert error is None and api.calls == 2
    assert 3 in sleeps and 4 in sleeps
    assert all(s["partial"] for s in states.values())


@pytest.mark.parametrize("status", [401, 403, 500])
def test_failures_are_diagnostic_and_private(items, status):
    api, _ = api_with(lambda _: httpx.Response(status, text="SECRET PASSWORD TOKEN DID HANDLE POST"))
    with pytest.raises(probe.ProbeError, match=f"{probe.SESSION}: HTTP {status}") as exc:
        api.login("private-handle", "private-password")
    assert "SECRET" not in str(exc.value)
    states, error = probe.sweep(api, probe.Attention(items), "2026-10-30", "2026-11-06", "*")
    assert error == f"{probe.SEARCH}: HTTP {status}"
    assert all(s["partial"] for s in states.values())


def test_json_error_fields_are_reported_and_truncated(items):
    body = {"error": "InvalidRequest", "message": "Query must not be empty. " + "x" * 300,
            "accessJwt": "secret-token", "post": post()}
    api, _ = api_with(lambda _: httpx.Response(400, json=body))
    api.headers = {"Authorization": "Bearer secret-token"}
    states, error = probe.sweep(api, probe.Attention(items), "2026-10-30", "2026-11-06", "*")
    detail = f"error: {body['error']}; message: {body['message']}"[:200]
    assert error == f"{probe.SEARCH}: HTTP 400, {detail}"
    assert len(error.split(", ", 1)[1]) == 200
    report = probe.render_report(items, [], probe.Attention(items), states, "2026-10-30", "2026-11-06", api.calls, error=error)
    assert f"Failure: {error}" in report
    for private in ("secret-token", "Authorization", "private-person.bsky.social", "did:plc:", "PRIVATE FIXTURE POST TEXT"):
        assert private not in report


@pytest.mark.parametrize("first_qualifying", [0, 1, 2])
def test_preflight_picks_first_qualifying_form(first_qualifying):
    requests = []
    linked = post(links=["https://www.biorxiv.org/content/10.1101/2026.11.01.123456"])
    def handler(request):
        requests.append(request)
        if len(requests) - 1 < first_qualifying:
            return httpx.Response(400, json={"error": "InvalidRequest", "message": "Unsupported query"})
        return httpx.Response(200, json={"posts": [linked]})
    api, sleeps = api_with(handler)
    selected, results = probe.preflight(api, "2026-10-30", "2026-11-06")
    assert selected == probe.QUERY_FORMS[first_qualifying]
    assert [result["selected"] for result in results] == [i == first_qualifying for i in range(3)]
    assert [result["linked"] for result in results] == [int(i >= first_qualifying) for i in range(3)]
    assert api.calls == 3 and len(sleeps) == 3
    for request, query, domain in zip(requests, ("*", "domain:biorxiv.org", "biorxiv.org"), (True, False, True)):
        expected = {"q": query, "sort": "latest", "since": "2026-10-30", "until": "2026-11-06", "limit": "100"}
        if domain:
            expected["domain"] = "biorxiv.org"
        assert dict(request.url.params) == expected


def test_preflight_rejects_text_only_and_wrong_host_links():
    text_only = post(links=[])
    text_only["record"]["text"] = "biorxiv.org https://biorxiv.org/content/10.1101/fake"
    wrong_host = post(links=["https://biorxiv.org.evil.test/paper", "https://notbiorxiv.org/paper"])
    embedded = post(links=[])
    embedded["embed"] = {"$type": "app.bsky.embed.external#view", "external": {"uri": "https://biorxiv.org/paper"}}
    pages = iter([[text_only, wrong_host], [embedded], [embedded]])
    api, _ = api_with(lambda _: httpx.Response(200, json={"posts": next(pages)}))
    selected, results = probe.preflight(api, "2026-10-30", "2026-11-06")
    assert selected == "domain:{host}"
    assert [(r["status"], r["posts"], r["linked"]) for r in results] == [(200, 2, 0), (200, 1, 1), (200, 1, 1)]


def test_preflight_calls_consume_budget_without_retry():
    api, sleeps = api_with(lambda _: httpx.Response(429, headers={"Retry-After": "3"}, json={"error": "RateLimitExceeded"}), budget=2)
    selected, results = probe.preflight(api, "2026-10-30", "2026-11-06")
    assert selected is None and api.calls == 2
    assert sleeps == [probe.PAUSE, probe.PAUSE]
    assert [r["status"] for r in results] == [429, 429, "unavailable"]
    assert results[-1]["error"] == "Search call budget exhausted"


@pytest.mark.parametrize("form", probe.QUERY_FORMS)
def test_sweep_uses_selected_form_and_counts_only_verified_links(items, form):
    requests = []
    text_only = post(uri="text-only", links=[])
    text_only["record"]["text"] = "https://arxiv.org/abs/2611.00001"
    def handler(request):
        host = probe.HOSTS[len(requests)]
        requests.append(request)
        assert request.url.params["q"] == form.format(host=host)
        assert request.url.params.get("domain") == (None if form == "domain:{host}" else host)
        return httpx.Response(200, json={"posts": [text_only, post()]})
    api, _ = api_with(handler)
    attention = probe.Attention(items)
    states, error = probe.sweep(api, attention, "2026-10-30", "2026-11-06", form)
    assert error is None and api.calls == 6
    assert attention.items[next(iter(items))]["posts"] == 1
    assert attention.items["arxiv:2611.00001"]["posts"] == 0
    assert "text-only" not in attention.seen


@pytest.mark.parametrize("qualifies", [False, True])
def test_main_reports_preflight_and_fails_if_no_form_qualifies(items, monkeypatch, capsys, qualifies):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith(probe.SESSION):
            return httpx.Response(200, json={"accessJwt": "secret-token"})
        if len(requests) == 2:
            return httpx.Response(400, json={"error": "InvalidRequest", "message": "Query rejected", "token": "secret-token"})
        return httpx.Response(200, json={"posts": [post(links=[
            "https://www.biorxiv.org/content/10.1101/2026.11.01.123456"] if qualifies else [])]})
    api, _ = api_with(handler)
    monkeypatch.setattr(probe, "Bluesky", lambda _: api)
    monkeypatch.setattr(probe, "load_store", lambda *_: (items, [], "2026-10-30", "2026-11-06"))
    monkeypatch.setattr("sys.argv", ["probe.py"])
    monkeypatch.setenv("BLUESKY_HANDLE", "private-person.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "secret-password")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert probe.main() == (0 if qualifies else 1)
    report = capsys.readouterr().out
    assert f"Search calls: {9 if qualifies else 3}/1000; session calls: 1." in report
    assert "| * | biorxiv.org | 400 | 0 | 0 |" in report
    assert "error: InvalidRequest; message: Query rejected" in report
    assert f"| domain:biorxiv.org | — | 200 | 1 | {int(qualifies)} |" in report
    assert f"| biorxiv.org | biorxiv.org | 200 | 1 | {int(qualifies)} |" in report
    assert ("No search query form returned HTTP 200 with a verified link" in report) is not qualifies
    for private in ("private-person.bsky.social", "did:plc:", "PRIVATE FIXTURE POST TEXT", "at://", "secret-token", "secret-password"):
        assert private not in report


def test_rendered_report_contains_no_social_identity_or_text(items, tmp_path, monkeypatch, capsys):
    attention = probe.Attention(items)
    for i in range(3):
        attention.add(post(uri=f"private-post-{i}", author=f"did:plc:private-{i}", links=[
            "https://www.nature.com/articles/s41586-026-12345-6", "https://arxiv.org/abs/2611.00001", "https://doi.org/10.1000/unknown"]))
    rows = [{"rank": rank, "item_ids": set(items)} for rank in (1, 6, 21)]
    states = {host: {"posts": 3, "calls": 1, "status": "cursor end", "partial": False} for host in probe.HOSTS}
    report = probe.render_report(items, rows, attention, states, "2026-10-30", "2026-11-06", 6)
    for private in ("private-person.bsky.social", "did:plc:", "PRIVATE FIXTURE POST TEXT", "private-post-", "at://"):
        assert private not in report
    assert "| 1-5 | 1 | 1/1 (100.0%) | 1/1 (100.0%) |" in report
    assert "| A paper &#124; with a title | 3 | 18 | 1 |" in report
    assert "Verdict: at N = 20, 2/2 (100.0%)" in report
    assert "3 unique posts" in report
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    probe.emit(report)
    assert summary.read_text() == report
    assert capsys.readouterr().out == report + "\n"


def test_load_window_and_attached_ids(tmp_path, items):
    for folder in ("items", "topics", "days"):
        (tmp_path / folder).mkdir()
    (tmp_path / "days/2026-11-05.json").write_text('{}')
    for i, item in enumerate(items.values()):
        (tmp_path / f"items/{i}.json").write_text(json.dumps(item))
    topic = {"history": [
        {"date": "2026-10-29", "rank": 1, "item_ids": []},
        {"date": "2026-10-30", "rank": 5, "item_ids": ["paper"], "attached_item_ids": ["attached"]},
        {"date": "2026-11-05", "rank": None, "item_ids": []},
        {"date": "2026-11-06", "rank": 1, "item_ids": []},
    ]}
    (tmp_path / "topics/topic.json").write_text(json.dumps(topic))
    loaded, rows, start, end = probe.load_store(tmp_path, 7)
    assert loaded == items and (start, end) == ("2026-10-30", "2026-11-06")
    assert rows == [{"rank": 5, "item_ids": {"paper", "attached"}}]


def test_row_author_count_is_union(items):
    attention = probe.Attention(items)
    for i in range(2):
        attention.add(post(uri=f"post-{i}", author=f"did:plc:{i}", links=[
            "https://www.nature.com/articles/s41586-026-12345-6", "https://arxiv.org/abs/2611.00001"]))
    report = probe.render_report(items, [{"rank": 1, "item_ids": set(items)}], attention, {}, "2026-10-30", "2026-11-06", 0)
    assert "Verdict: at N = 20, 0/1 (0.0%)" in report


@pytest.fixture
def automated_attention(items):
    attention = probe.Attention(items)
    links = ["https://www.biorxiv.org/content/10.1101/2026.11.01.123456v1",
             "https://arxiv.org/abs/2611.00001v2",
             "https://www.medrxiv.org/content/10.1101/2026.11.01.999999v1"]
    links += [f"https://doi.org/10.1000/outside-{i}" for i in range(22)]
    for i, link in enumerate(links):
        fixture = post(uri=f"automated-{i}", author="did:plc:automated", links=[link])
        fixture["likeCount"] = 100
        fixture["quoteCount"] = 3
        attention.add(fixture)
        attention.add(fixture)
    # Another version/host is the same normalized ID, not a 26th paper.
    attention.add(post(uri="repeat", author="did:plc:automated", links=[
        "https://doi.org/10.1101/2026.11.01.123456v2"]))
    human = post(uri="human", links=links[:2])
    human["quoteCount"] = 3
    attention.add(human)
    return attention


@pytest.mark.parametrize(("threshold", "automated"), [(10, True), (20, True), (50, False)])
def test_automated_accounts_use_all_normalized_ids_and_filter_engagement(items, automated_attention, threshold, automated):
    attention = automated_attention
    assert len(attention.author_ids["did:plc:automated"]) == 25
    filtered, outside, accounts, posts = attention.non_automated(threshold)
    assert accounts == int(automated)
    assert posts == (26 if automated else 0)
    key = next(iter(items))
    assert filtered[key]["engagement"] == (9 if automated else 120)
    assert len(filtered[key]["authors"]) == (1 if automated else 2)
    assert filtered[key]["posts"] == (1 if automated else 3)
    assert len(outside) == (0 if automated else 23)


@pytest.mark.parametrize("threshold", [10, 20, 50])
def test_automated_threshold_is_inclusive(threshold):
    attention = probe.Attention({})
    attention.add(post(links=[f"https://doi.org/10.1000/{i}" for i in range(threshold)]))
    assert attention.non_automated(threshold)[2:] == (1, 1)
    assert attention.non_automated(threshold + 1)[2:] == (0, 0)


def test_row_metrics_use_paper_count_and_author_union(items, automated_attention):
    items["repo"] = {"type": "repo"}
    row = {"rank": 1, "item_ids": {*items, "missing"}}
    filtered = automated_attention.non_automated(20)[0]
    assert probe.row_metrics(row, items, filtered) == {
        "rank": 1, "paper count": 2, "non-automated authors": 1,
        "non-automated authors per paper": .5, "engagement": 18, "engagement per paper": 9,
    }
    empty = probe.row_metrics({"rank": 2, "item_ids": {"repo", "missing"}}, items, filtered)
    assert empty["paper count"] == 0
    assert empty["non-automated authors per paper"] is None
    assert empty["engagement per paper"] is None


def test_report_sensitivity_distributions_and_correlations(items, automated_attention):
    keys = list(items)
    rows = [{"rank": 1, "item_ids": set(keys)}, {"rank": 6, "item_ids": {keys[0]}},
            {"rank": 21, "item_ids": set()}]
    report = probe.render_report(items, rows, automated_attention, {}, "2026-10-30", "2026-11-06", 0)
    assert "| Automated accounts | 1 | 1 | 0 |" in report
    assert "| Share of swept unique posts from automated accounts | 26/27 (96.3%) | 26/27 (96.3%) | 0/27 (0.0%) |" in report
    assert "| all | 2 | Non-automated authors >= 2 | 0/2 (0.0%) | 0/2 (0.0%) | 2/2 (100.0%) |" in report
    assert "| all | 2 | Non-automated authors median / p90 / max | 1 / 1 / 1 | 1 / 1 / 1 | 2 / 2 / 2 |" in report
    assert "| all | 2 | Engagement median / p90 / max | 9 / 9 / 9 | 9 / 9 / 9 | 117 / 120 / 120 |" in report
    assert "| all | 2 | Engagement >= 10 | 0/2 (0.0%) | 0/2 (0.0%) | 2/2 (100.0%) |" in report
    assert "| 1-5 | 1 | 1/1 (100.0%) | 0/1 (0.0%) | 0/1 (0.0%) | 1/1 (100.0%) |" in report
    assert "| 6-20 | 1 | 1/1 (100.0%) | 0/1 (0.0%) | 0/1 (0.0%) | 1/1 (100.0%) |" in report
    assert "| 21-40 | 1 | 0/1 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) |" in report
    assert "| paper count | 3 | -1.0000 | -1.0000 | -1.0000 |" in report
    assert "| non-automated authors | 3 | -0.8660 | -0.8660 | -0.8660 |" in report
    assert "| non-automated authors per paper | 2 | 1.0000 | 1.0000 | 1.0000 |" in report
    assert "| engagement | 3 | -1.0000 | -1.0000 | -1.0000 |" in report
    assert "| engagement per paper | 2 | undefined (too few rows or constant values) |" in report
    assert "not inflated by cluster size" in report
    assert "including automated accounts" in report
    for private in ("private-person.bsky.social", "did:plc:", "PRIVATE FIXTURE POST TEXT", "automated-", "at://"):
        assert private not in report


def test_zero_attention_papers_remain_in_window_denominators(items):
    attention = probe.Attention(items)
    attention.add(post())
    report = probe.render_report(items, [], attention, {}, "2026-10-30", "2026-11-06", 0)
    assert "| all | 2 | Engagement >= 5 | 1/2 (50.0%) | 1/2 (50.0%) | 1/2 (50.0%) |" in report
    assert "| all | 2 | Engagement median / p90 / max | 3 / 6 / 6 | 3 / 6 / 6 | 3 / 6 / 6 |" in report
    assert "| arxiv | 1 | Non-automated authors median / p90 / max | 0 / 0 / 0 |" in report


def test_outside_news_exclusion_prefix_groups_and_candidate_order(items):
    attention = probe.Attention(items)
    news = "https://www.nature.com/articles/d41586-026-12345-6"
    attention.add(post(uri="news", links=[news]))
    assert attention.unknown_posts == 0
    assert not attention.unknown
    candidates = [f"{'10.64898' if i % 2 else '10.1101'}/2026.11.01.{i:06d}" for i in range(11)]
    for i, key in enumerate(candidates):
        fixture = post(uri=f"candidate-{i}", links=[f"https://doi.org/{key}"])
        fixture["quoteCount"] = i
        attention.add(fixture)
    attention.add(post(uri="others", links=[news, "https://arxiv.org/abs/2611.99999v1",
                                            "https://doi.org/10.1000/other", "https://pubmed.ncbi.nlm.nih.gov/99999/"]))
    report = probe.render_report(items, [], attention, {}, "2026-10-30", "2026-11-06", 0)
    assert "12 unique posts" in report
    assert "| bioRxiv or medRxiv DOIs | 11 | 11 | 0 | 11 |" in report
    assert "| arXiv ids | 1 | 1 | 0 | 1 |" in report
    assert "| other DOIs | 1 | 1 | 0 | 1 |" in report
    assert [line for line in report.splitlines() if line.startswith("- ")] == [f"- {key}" for key in reversed(candidates[1:])]
    assert "d41586-026-12345-6" not in report


def test_top_papers_sorted_by_engagement_and_unranked_count(items):
    items["arxiv:2611.00001"]["published_at"] = "2026-10-01"
    attention = probe.Attention(items)
    for i in range(3):
        fixture = post(uri=f"low-{i}", author=f"did:plc:low-{i}")
        fixture["likeCount"], fixture["repostCount"] = 0, 0
        attention.add(fixture)
    attention.add(post(uri="high", links=["https://arxiv.org/abs/2611.00001"]))
    rows = [{"rank": 6, "item_ids": {next(iter(items))}}, {"rank": 1, "item_ids": {next(iter(items))}}]
    report = probe.render_report(items, rows, attention, {}, "2026-10-30", "2026-11-06", 0)
    assert report.index("| Another paper | 1 | 6 | not ranked |") < report.index("| A paper &#124; with a title | 3 | 0 | 1 |")
    assert "engagement >= 5 absent from every Top 40 row in the window: 1." in report
