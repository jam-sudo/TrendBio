"""Inspect dated editions using their stored evidence, rankings and embeddings."""
from collections import Counter, defaultdict, deque
from datetime import date, timedelta
from hashlib import sha256

from pipeline.cluster import cluster_items
from pipeline.config import load_scoring, load_taxonomy
from pipeline.score import rank
from pipeline.store import Store


def _doi(value):
    return (value or '').strip().lower().removeprefix('https://doi.org/').removeprefix('doi:')


def top_dois(store, day):
    identifiers = set()
    for row in day.ranked[:10]:
        topic = store.get_topic(row.slug)
        entry = next(x for x in topic.history if x.date == day.date)
        identifiers.update(entry.item_ids)
    papers = [store.get_item(identifier) for identifier in sorted(identifiers)]
    if any(paper is None for paper in papers):
        raise ValueError('A ranked topic references missing evidence')
    return {_doi(p.doi) for p in papers if p.doi}, sum(not p.doi for p in papers)


def _review_sample(cases, limit=10):
    # Round-robin across dates, decisions and subjects so the largest subject cannot fill a sample.
    groups = defaultdict(deque)
    for case in sorted(cases, key=lambda c: sha256(f'{c["date"]}/{c["id"]}'.encode()).digest()):
        groups[case['date'], case['decision'], case['category']].append(case)
    queues = deque(groups[key] for key in sorted(groups, key=lambda key: sha256(str(key).encode()).digest()))
    result, seen = [], set()
    while queues and len(result) < limit:
        group = queues.popleft()
        case = group.popleft()
        if case['id'] not in seen:
            result.append(case)
            seen.add(case['id'])
        if group:
            queues.append(group)
    return result


def audit_edition(store: Store, start: date, end: date, references=()):
    if end < start:
        raise ValueError('End precedes start')
    cfg = load_scoring()
    taxonomy = load_taxonomy(store.domain)
    topics = store.all_topics()
    histories = defaultdict(list)
    for topic in topics:
        for entry in topic.history:
            if entry.item_ids and start <= entry.date <= end:
                histories[entry.date].append((topic, entry))
    records = store.items_between(start - timedelta(days=cfg.window_days - 1), end,
                                  by_publication=taxonomy.window_by_publication)
    samples = {k: [] for k in ('top', 'bottom', 'excluded')}
    report = {'domain': store.domain, 'from': str(start), 'to': str(end), 'days': [], 'missing_days': []}
    ref_results = []
    for i in range((end - start).days + 1):
        when = start + timedelta(days=i)
        day = store.get_day(when)
        if day is None:
            report['missing_days'].append(str(when))
            ref_results.extend({**ref, 'stored': None, 'clustered': None, 'ranked': None}
                               for ref in references if ref['date'] == str(when))
            continue
        first = when - timedelta(days=cfg.window_days - 1)
        papers = {item.id: item for item in records if item.type in {'preprint', 'published'}
                  and item.first_seen <= when and first <= (item.published_at if taxonomy.window_by_publication
                                                            else item.first_seen) <= when}
        ranks = {r.slug: r for r in day.ranked}
        top = {r.slug for r in day.ranked[:10]}
        bottom = {r.slug for r in day.ranked[-10:]} - top
        counts, venues = defaultdict(Counter), Counter()
        for paper in papers.values():
            cat = paper.primary_category or taxonomy.fallback_category
            counts[cat]['stored'] += 1
            counts[cat]['relevant'] += int(paper.relevant)
            venues[paper.metadata.get('journal') or paper.source] += 1
        yesterday = store.get_day(when - timedelta(days=1))
        previous = {r.slug for r in yesterday.ranked} if yesterday else set()
        clustered, ranked_ids, top_ids, alt_rows = set(), set(), set(), []
        assignments = defaultdict(Counter)
        unsaved_categories = 0
        for topic, entry in histories[when]:
            row = ranks.get(topic.slug)
            cat = row.category if row else entry.category or topic.category
            unsaved_categories += int(row is None and entry.category is None)
            counts[cat]['clusters'] += 1
            counts[cat]['ranked'] += int(row is not None)
            clustered.update(entry.item_ids)
            for identifier in entry.item_ids:
                paper = papers[identifier]
                assignments[paper.primary_category or taxonomy.fallback_category][cat] += 1
            if row:
                ranked_ids.update(entry.item_ids)
            if topic.slug in top:
                top_ids.update(entry.item_ids)
            bucket = 'top' if topic.slug in top else 'bottom' if topic.slug in bottom else 'excluded' if not row else None
            if bucket:
                samples[bucket].append({'date': str(when), 'id': topic.slug, 'category': cat,
                                        'decision': 'ranked' if row else 'unranked-cluster', 'evidence': entry.item_ids})
            subtotal = .75 * entry.scores.rise + .25 * entry.scores.volume
            penalty = cfg.yesterday_penalty * subtotal if topic.slug in previous else 0
            score = entry.scores.model_copy(update={'total': subtotal - penalty, 'penalty': penalty})
            alt_rows.append((topic.model_copy(update={'category': cat}), entry.signals, score))
        for paper in papers.values():
            if paper.id not in clustered:
                samples['excluded'].append({'date': str(when), 'id': paper.id, 'category': paper.primary_category,
                                            'decision': 'unclustered' if paper.relevant else 'irrelevant',
                                            'evidence': [paper.id]})
        alternative = {t.slug for t, _, _ in rank(alt_rows, cfg)[:10]}
        metrics = {'date': str(when), 'status': day.run.status, 'backfilled': day.run.backfilled,
                   'elapsed_seconds': (day.run.finished - day.run.started).total_seconds(),
                   'model_cost_usd': day.run.model_cost_usd, 'source_status': day.run.source_status,
                   'categories': dict(counts), 'venues': venues, 'paper_to_cluster_categories': dict(assignments),
                   'top10_evidence_venues': Counter(papers[i].metadata.get('journal') or papers[i].source for i in top_ids),
                   'top10_evidence_items': len(top_ids), 'legacy_unranked_categories': unsaved_categories,
                   'alternative_top10': {'retained': len(top & alternative), 'official': len(top)}}
        if store.domain == 'biology':
            comp = Store(store.root, 'computational')
            other = comp.get_day(when)
            metrics['compbio_top10'] = None
            if other:
                bio_ids, bio_missing = top_dois(store, day)
                comp_ids, comp_missing = top_dois(comp, other)
                metrics['compbio_top10'] = {'biology_dois': len(bio_ids), 'compbio_dois': len(comp_ids),
                                            'shared': len(bio_ids & comp_ids), 'union': len(bio_ids | comp_ids),
                                            'missing_doi': [bio_missing, comp_missing]}
        report['days'].append(metrics)
        for ref in references:
            if ref['date'] != str(when):
                continue
            matches = {p.id for p in papers.values() if p.id == ref['id'] or
                       (_doi(p.doi) and _doi(p.doi) == _doi(ref['id']))}
            ref_results.append({**ref, 'stored': bool(matches), 'clustered': bool(matches & clustered),
                                'ranked': bool(matches & ranked_ids)})
    report['review_samples'] = {key: _review_sample(value) for key, value in samples.items()}
    report['references'] = ref_results
    measured = [d['model_cost_usd'] for d in report['days'] if not d['backfilled'] and d['model_cost_usd'] is not None]
    report['measured_cost_days'] = len(measured)
    report['projected_30d_usd'] = round(sum(measured) * 30 / len(measured), 4) if measured else None
    return report


def compare_windows(store: Store, end: date):
    """Recluster the same dated cohort once over 28 days and in four separate weeks."""
    start = end - timedelta(days=27)
    papers = [p for p in store.items_between(start, end, by_publication=True)
              if p.relevant and p.type in {'preprint', 'published'}]
    linked = {p.preprint_id for p in papers if p.type == 'published'}
    papers = sorted((p for p in papers if p.id not in linked), key=lambda p: p.id)
    ids = [p.id for p in papers]
    return cluster_publication_windows(ids, [p.published_at for p in papers], store.get_embeddings(ids), end)


def cluster_publication_windows(ids, dates, vectors, end):
    cfg = load_scoring()
    start = end - timedelta(days=27)
    if not len(ids) == len(set(ids)) == len(dates) == len(vectors) or any(not start <= d <= end for d in dates):
        raise ValueError('Window trial requires unique dated works and one embedding per work')
    long = cluster_items(ids, vectors, cfg)
    weekly = []
    for week in range(4):
        idx = [i for i, day in enumerate(dates) if (day - start).days // 7 == week]
        weekly.append(cluster_items([ids[i] for i in idx], vectors[idx], cfg))
    short_ids = {identifier for groups in weekly for group in groups for identifier in group}
    long_ids = {identifier for group in long for identifier in group}
    return {'from': str(start), 'to': str(end), 'papers_with_embeddings': len(ids),
            'weekly_papers': [sum((d - start).days // 7 == i for d in dates) for i in range(4)],
            'weekly_clusters': list(map(len, weekly)), 'clusters_28d': len(long),
            'newly_clustered_ids': sorted(long_ids - short_ids),
            'lost_clustered_ids': sorted(short_ids - long_ids),
            'new_group_examples': [group for group in long if set(group) - short_ids][:10]}
