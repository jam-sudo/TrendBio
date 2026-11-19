"""Four-week metadata surveys and independent coverage checks for candidate editions."""
from collections import Counter
from datetime import date, datetime, timedelta
import re
from hashlib import sha256

import httpx

from pipeline.sources.base import request
from pipeline.sources.crossref import crossref_works, datacite_type, full_date, related_dois, related_work_dois, vor_cc_by


def reference_dois(client, venue, start, end):
    if venue.get('reference') == 'europepmc':
        endpoint = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'
        params = {'query': f'ISSN:{venue["issn"]} AND FIRST_PDATE:[{start} TO {end}]',
                  'format': 'json', 'pageSize': 1000, 'cursorMark': '*'}
        dois, seen_ids = set(), set()
        while True:
            page = request(client, endpoint, params=params).json()
            records = page['resultList']['result']
            previous = len(seen_ids)
            seen_ids.update((r['source'], r['id']) for r in records)
            dois.update(r['doi'].lower().strip() for r in records if r.get('doi'))
            if len(seen_ids) >= page['hitCount']:
                return dois, len(seen_ids)
            if not records or len(seen_ids) == previous:
                raise ValueError('Incomplete Europe PMC result')
            params['cursorMark'] = page['nextCursorMark']
    if 'copernicus' in venue:
        journal = venue['copernicus']
        base = f'https://{journal}.copernicus.org/articles/'
        index = request(client, base).text
        volumes = {int(year): volume for volume, year in re.findall(r'>Volume\s+(\d+)</a>,\s*(\d{4})', index)}
        dois = set()
        for year in range(start.year, end.year + 1):
            if year not in volumes:
                raise ValueError(f'No {year} publisher volume listed for {journal}')
            html = request(client, base + volumes[year] + '/').text
            entries = html.split('class="published-date"')[1:]
            if not entries:
                raise ValueError(f'Unrecognized publisher table of contents for {journal}')
            for entry in entries:
                stamp = re.match(r'>\s*(\d{1,2} [A-Za-z]{3} \d{4})\s*</div>', entry)
                citation = re.search(r'https://doi\.org/(10\.5194/[A-Za-z0-9.-]+)', entry)
                if not stamp or not citation:
                    raise ValueError(f'Missing publication date or DOI in {journal} contents')
                day = datetime.strptime(stamp[1], '%d %b %Y').date()
                if start <= day <= end:
                    dois.add(citation[1].lower().rstrip('.'))
        return dois, len(dois)
    return None


def survey_venue(client: httpx.Client, venue: dict, end: date):
    start = end - timedelta(days=27)
    container = 'journals/' + venue['issn'] if 'issn' in venue else 'prefixes/' + str(venue['prefix'])
    endpoint = f'https://api.crossref.org/{container}/works'
    work_type = venue.get('type', 'journal-article')
    weeks = [{'from': str(start + timedelta(weeks=i)), 'to': str(start + timedelta(weeks=i, days=6)),
              'published': 0, 'with_abstract': 0, 'created': 0, 'created_imprecise_publication_day': 0,
              'languages': Counter(), 'types': Counter(), 'with_license_url': 0,
              'with_abstract_and_vor_cc_by': 0} for i in range(4)]
    published, discovered, abstracts, pub_filter = set(), set(), set(), set()
    linked_works = {}
    versions = {}
    for axis, field in [('pub', 'published'), ('created', 'created')]:
        filters = f'type:{work_type},from-{axis}-date:{start},until-{axis}-date:{end}'
        for doi, work in crossref_works(client, endpoint, filters):
            discovered.add(doi)
            if field == 'published':
                pub_filter.add(doi)
            if (work.get('abstract') or '').strip():
                abstracts.add(doi)
            day = full_date(work, field)
            if day is None or not start <= day <= end:
                continue
            week = weeks[(day - start).days // 7]
            if field == 'published':
                week['published'] += 1
                week['with_abstract'] += int(doi in abstracts)
                week['with_license_url'] += int(any(lic.get('URL') for lic in work.get('license', [])))
                week['with_abstract_and_vor_cc_by'] += int(doi in abstracts and bool(vor_cc_by(work, end)))
                week['languages'][work.get('language') or 'und'] += 1
                week['types'][work['type']] += 1
                published.add(doi)
                if container == 'prefixes/10.26434' and work_type == 'posted-content':
                    version = re.fullmatch(r'(10\.26434/chemrxiv[.-].+?)(?:/v|[.-]v)([1-9]\d*)', doi)
                    versions[doi] = (version[1] if version else doi, int(version[2]) if version else None,
                                     related_dois(work, 'is-preprint-of'))
                if venue.get('data_link_sample'):
                    links = related_work_dois(work)
                    if links:
                        linked_works[doi] = (related_dois(work, 'has-preprint'), links)
            else:
                week['created'] += 1
                week['created_imprecise_publication_day'] += int(full_date(work, 'published') is None)
    result = {'subject': venue['subject'], 'container': container, 'work_type': work_type, 'weeks': weeks,
              'unique_discovered': len(discovered), 'publication_filter_records': len(pub_filter),
              'publication_filter_without_exact_day_in_window': len(pub_filter - published),
              'status': 'ok', 'reference': None}
    if versions:
        result['versions'] = {'doi_records': len(versions), 'distinct_roots_in_window': len({r for r, _, _ in versions.values()}),
                              'first_versions': sum(v == 1 for _, v, _ in versions.values()),
                              'later_versions': sum(v is not None and v > 1 for _, v, _ in versions.values()),
                              'unparsed': sum(v is None for _, v, _ in versions.values()),
                              'journal_links': {doi: links for doi, (_, _, links) in sorted(versions.items()) if links}}
    if venue.get('data_link_sample'):
        key = lambda text: sha256(text.encode()).digest()
        sample = []
        for paper in sorted(linked_works, key=key)[:venue['data_link_sample']]:
            preprints, links = linked_works[paper]
            identifier = min(links, key=key)
            sample.append({'paper': paper, 'preprints': preprints, 'related': identifier,
                           'datacite_type': datacite_type(client, identifier)})
        result['related_works'] = {'papers_with_related_dois': len(linked_works), 'sample': sample}
    try:
        refs = reference_dois(client, venue, start, end)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        result['reference'] = {'status': 'failed', 'reason': str(exc)}
        return result
    if refs is not None:
        ids, total = refs
        result['reference'] = {
            'source': 'Copernicus published volume' if 'copernicus' in venue else 'Europe PMC',
            'status': 'ok', 'records': total, 'unique_dois': len(ids),
            'found_by_publication_day': len(ids & published), 'found_by_either_date': len(ids & discovered),
            'found_with_abstract': len(ids & abstracts),
            'example_missing_dois': sorted(ids - discovered)[:10],
        }
    return result
