from datetime import date

import httpx

from pipeline.edition_audit import audit_beta, audit_edition, compare_windows
from pipeline.store import Store
from pipeline.survey import reference_dois, survey_venue


def test_dated_audit_preserves_missing_days_and_checks_independent_ids(fixtures_root):
    first, last = date(2026, 10, 31), date(2026, 11, 1)
    refs = [{'date': str(d), 'id': 'arxiv:numerical-analysis-fixture-1', 'source': 'independent fixture'}
            for d in [first, last]]
    report = audit_edition(Store(fixtures_root / 'data', 'math'), first, last, refs)
    assert report['missing_days'] == [str(first)]
    assert [r['ranked'] for r in report['references']] == [None, True]
    assert report['days'][0]['categories']['numerical-analysis'] == {'stored': 3, 'relevant': 3, 'ranked': 1, 'clusters': 1}
    assert report['review_samples']['top'][0]['id'] == 'quadrature-fixture'
    assert report['days'][0]['paper_to_cluster_categories'] == {'numerical-analysis': {'numerical-analysis': 3}}
    assert report['projected_30d_usd'] is None


def test_beta_tracks_live_dates_and_excludes_backfills(tmp_path, fixtures_root):
    import shutil
    shutil.copytree(fixtures_root / 'data' / 'math', tmp_path / 'math')
    store = Store(tmp_path, 'math')
    day = store.get_day(date(2026, 11, 1))
    day.run.backfilled = False
    store.put_day(day)
    day = day.model_copy(deep=True, update={'date': date(2026, 11, 3), 'ranked': []})
    day.run.backfilled = True
    store.put_day(day)
    result = audit_beta(store, date(2026, 11, 3))
    assert result['live_editions'] == 1 and result['backfilled_dates'] == ['2026-11-03']
    assert result['missing_days'] == ['2026-11-02'] and result['target_editions'] == 14


def test_sparse_edition_samples_disjoint_ranks_and_reports_review_exclusions(tmp_path, fixtures_root):
    import shutil
    shutil.copytree(fixtures_root / 'data' / 'math', tmp_path / 'math')
    store = Store(tmp_path, 'math')
    when = date(2026, 11, 1)
    day = store.get_day(when)
    first = day.ranked[0]
    topic = store.get_topic(first.slug)
    for i in range(2, 7):
        slug = f'topic-{i}'
        store.put_topic(topic.model_copy(update={'slug': slug}))
        day.ranked.append(first.model_copy(update={'slug': slug, 'rank': i}))
    store.put_day(day)
    paper = store.get_item(topic.history[-1].item_ids[0]).model_copy(update={'id': 'unqualified'})
    store.put_item(paper)
    store._write(tmp_path / 'math/audits' / f'cohesion-{when}.json',
                 {'minimum': 3, 'candidates': [{'review': 'example', 'items': [paper.id], 'qualified': [], 'failed': False}]})
    result = audit_edition(store, when, when)
    samples = result['review_samples']
    assert {s['id'] for s in samples['top']} == {first.slug, 'topic-2', 'topic-3'}
    assert {s['id'] for s in samples['bottom']} == {'topic-4', 'topic-5', 'topic-6'}
    assert next(s for s in samples['excluded'] if s['id'] == paper.id)['decision'] == 'below-minimum-reviewed-group'
    assert result['days'][0]['alternative_top10']['official'] == 6


def test_28_day_experiment_recovers_a_sparse_group(tmp_path, fixtures_root):
    import numpy as np

    store = Store(tmp_path, 'math')
    item = Store(fixtures_root / 'data', 'math').get_item('arxiv:numerical-analysis-fixture-1')
    for i, d in enumerate([1, 10, 20]):
        when = date(2026, 11, d)
        paper = item.model_copy(update={'id': f'example:{i}', 'type': 'published', 'relevant': True,
                                        'first_seen': when, 'published_at': when})
        store.put_item(paper)
        store.put_embedding(paper.id, np.array([1.0, 0.0]))
    result = compare_windows(store, date(2026, 11, 28))
    assert result['weekly_clusters'] == [0, 0, 0, 0]
    assert result['clusters_28d'] == 1 and len(result['newly_clustered_ids']) == 3


def test_survey_keeps_date_precision_and_reference_denominators():
    full = {'DOI': '10.1/A', 'created': {'date-parts': [[2026, 10, 22]]},
            'published': {'date-parts': [[2026, 10, 22]]}, 'abstract': 'text', 'type': 'journal-article'}
    partial = {**full, 'DOI': '10.1/B', 'published': {'date-parts': [[2026]]}}

    def reply(req):
        if req.url.path.endswith('/search'):
            return httpx.Response(200, json={'hitCount': 2, 'resultList': {'result': [
                {'source': 'MED', 'id': '1', 'doi': '10.1/a'}, {'source': 'MED', 'id': '2'}]}})
        return httpx.Response(200, json={'message': {'items': [full, partial], 'total-results': 2}})

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        result = survey_venue(client, {'issn': '0000-0000', 'subject': 'fixture', 'reference': 'europepmc'}, date(2026, 11, 18))
    assert result['unique_discovered'] == 2 and result['publication_filter_without_exact_day_in_window'] == 1
    assert [(w['published'], w['created']) for w in result['weeks']] == [(1, 2), (0, 0), (0, 0), (0, 0)]
    assert result['reference']['records'] == 2 and result['reference']['found_with_abstract'] == 1


def test_publisher_contents_uses_article_publication_dates():
    def reply(req):
        page = ('<a>Volume 17</a>, 2026' if req.url.path == '/articles/' else
                '<div class="published-date">18 Nov 2026</div> https://doi.org/10.5194/se-17-a-2026,'
                '<div class="published-date">18 Dec 2026</div> https://doi.org/10.5194/se-17-b-2026,')
        return httpx.Response(200, text=page)

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        assert reference_dois(client, {'copernicus': 'se'}, date(2026, 10, 22),
                              date(2026, 11, 18)) == ({'10.5194/se-17-a-2026'}, 1)


def test_chemrxiv_survey_separates_revisions_and_explicit_journal_links():
    from pipeline.window_trial import trial_records
    stamp = {'date-parts': [[2026, 11, 1]]}
    base = {'published': stamp, 'created': stamp, 'type': 'posted-content', 'abstract': 'Summary'}
    records = [{**base, 'DOI': '10.26434/chemrxiv.99/v1'},
               {**base, 'DOI': '10.26434/chemrxiv.99/v2',
                'relation': {'is-preprint-of': [{'id-type': 'doi', 'id': '10.1/J'}]}}]
    venue = {'subject': 'chemistry-preprints', 'prefix': '10.26434', 'type': 'posted-content', 'survey_only': 'licences'}
    with httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={'message': {'items': records, 'total-results': len(records)}})
    )) as client:
        report = survey_venue(client, venue, date(2026, 11, 18))
        assert list(trial_records('other-field', [venue], date(2026, 10, 22), date(2026, 11, 18), client)) == []
    assert report['versions'] == {'doi_records': 2, 'distinct_roots_in_window': 1, 'first_versions': 1,
                                  'later_versions': 1, 'unparsed': 0,
                                  'journal_links': {'10.26434/chemrxiv.99/v2': ['10.1/j']}}
    assert sum(w['with_license_url'] for w in report['weeks']) == 0


def test_trial_counts_a_book_and_its_chapters_once():
    import numpy as np
    from pipeline.window_trial import run_window_trial

    day = date(2026, 11, 18)
    records = [(doi, day, 'Title', 'Abstract text', kind, parent, ['heritage']) for doi, kind, parent in [
        ('book', 'edited-book', None), ('ch1', 'book-chapter', 'book'), ('ch2', 'book-chapter', 'book'),
        ('ch3', 'book-chapter', None)]]

    class Embedder:
        def embed(self, texts):
            assert len(texts) == 1
            return np.array([[1, 0]])

    result = run_window_trial('humanities-arts', records, day, Embedder())
    assert result['unique_source_works'] == 4 and result['clusters_28d'] == 0
    assert result['excluded'] == {'chapter_with_sampled_parent': 2, 'chapter_without_sampled_parent': 1}


def test_publication_version_replaces_a_preprint_only_inside_the_same_trial_window():
    from datetime import date, timedelta
    import numpy as np
    from pipeline.edition_audit import cluster_publication_windows

    start = date(2026, 10, 1)
    ids = ['arxiv:a', 'doi:b', 'arxiv:c', 'doi:d']
    dates = [start, start + timedelta(days=9), start, start]
    result = cluster_publication_windows(ids, dates, np.array([[1., 0.]] * len(ids)), start + timedelta(days=27),
                                         {'doi:b': 'arxiv:a', 'doi:d': 'arxiv:c'})
    assert result['linked_preprints_suppressed_28d'] == 2
    assert result['weekly_linked_preprints_suppressed'] == [1, 0, 0, 0]
    assert result['clusters_28d'] == 0
