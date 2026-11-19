"""Retrospective, model-spend-free publication metadata trials for proposed editions."""
from collections import Counter
from datetime import timedelta

from pipeline.edition_audit import cluster_publication_windows
from pipeline.enrich import hints_for
from pipeline.sources.arxiv import ArxivAdapter
from pipeline.sources.base import load_config
from pipeline.sources.crossref import CrossrefAdapter, crossref_works, full_date, plain_text, related_dois


def trial_records(domain, venues, start, end, client):
    if domain in {'earth-environment', 'math', 'chemistry', 'astronomy'}:
        config = load_config(domain)
        adapter = (ArxivAdapter if 'arxiv' in config else CrossrefAdapter)(config)
        for item in adapter.fetch(start, end, client):
            yield item.id, item.published_at, item.title, item.abstract, item.type, None, hints_for(item, config['hints'])
        return

    for venue in venues:
        if venue.get('survey_only'):
            continue
        container = 'journals/' + venue['issn'] if 'issn' in venue else 'prefixes/' + venue['prefix']
        kind = venue.get('type', 'journal-article')
        filters = f'type:{kind},from-pub-date:{start},until-pub-date:{end}'
        for doi, work in crossref_works(client, f'https://api.crossref.org/{container}/works', filters):
            day = full_date(work, 'published')
            if not day or not start <= day <= end or work.get('update-to'):
                continue
            parent = None
            if kind == 'book-chapter':
                parents = related_dois(work, 'is-part-of')
                parent = parents[0] if len(parents) == 1 else None
            title = plain_text((work.get('title') or [''])[0])
            yield doi, day, title, plain_text(work.get('abstract')), kind, parent, [venue['subject']]


def run_window_trial(domain, records, end, embedder):
    works = {r[0]: r for r in records}
    eligible, omitted = [], Counter()
    for identifier, record in sorted(works.items()):
        _, day, title, abstract, kind, parent, subjects = record
        if kind == 'book-chapter':
            # One book's chapters cannot supply the three independent works needed for a trend.
            reason = 'chapter_with_sampled_parent' if parent and parent in works else 'chapter_without_sampled_parent'
            omitted[reason] += 1
        elif not title or not abstract:
            omitted['missing_title_or_abstract'] += 1
        else:
            eligible.append(record)
    ids = [r[0] for r in eligible]
    dates = [r[1] for r in eligible]
    vectors = embedder.embed([r[2] + '\n' + r[3] for r in eligible])
    result = cluster_publication_windows(ids, dates, vectors, end)
    result.update(domain=domain, collection='retrospective-publication-date', unique_source_works=len(works),
                  work_types=dict(Counter(r[4] for r in works.values())), excluded=dict(omitted),
                  eligible_by_subject=dict(Counter(s for r in eligible for s in (r[6] or ['unmapped-primary']))))
    return result
