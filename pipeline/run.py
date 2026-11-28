"""Daily pipeline and resumable historical collection."""

import copy
import json
import logging
import os
import shutil
import tempfile
from collections import Counter
from time import perf_counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from functools import cache
from pathlib import Path

import httpx
import numpy as np

from pipeline.attention import collect_attention
from pipeline.budget import Budget
from pipeline.cohesion import review_clusters
from pipeline.cluster import (
    append_history, attach_items, cluster_items, continuity_candidates, fill_unranked_days, match_or_create,
)
from pipeline.collect import PAPER_SOURCES, PARTIAL_REASONS, AllPaperSourcesFailed, all_paper_sources_failed, initial_source_status, intake_status, prepare_collected
from pipeline.config import Scoring, Taxonomy
from pipeline.dedupe import parallel_openedition_ids
from pipeline.embed import l2_normalize
from pipeline.enrich import enrich_items, fallback_summary, hints_for, screen_window
from pipeline.llm import Enrichment, LLM
from pipeline.models import Day, RankedTopic, RunInfo, Signals
from pipeline.score import rank, score_topics, signals_for
from pipeline.sources.arxiv import ArxivAdapter
from pipeline.sources.arxiv_announcements import PhysicsAnnouncements
from pipeline.sources.base import load_config
from pipeline.sources.github import GithubAdapter, seed_star_history
from pipeline.sources.pubmed import PubmedAdapter, pubmed_in_scope
from pipeline.store import Store
from pipeline.topic_map import build_map, published_map_editions
from pipeline.synthesize import fallback_copy, synthesize_top, tier_model, top_evidence
from pipeline.wipe import reset_derived, validate_month_range


logger = logging.getLogger(__name__)


@contextmanager
def _stage(name: str, **counts):
    started = perf_counter()
    logger.info('stage=%s event=start elapsed=0.000 %s', name,
                ' '.join(f'{key}={value}' for key, value in counts.items()))
    status = 'ok'
    try:
        yield counts
    except BaseException:
        status = 'failed'
        raise
    finally:
        logger.info('stage=%s event=end elapsed=%.3f status=%s %s', name,
                    perf_counter() - started, status,
                    ' '.join(f'{key}={value}' for key, value in counts.items()))


@dataclass
class Deps:
    adapters: list
    llm: LLM
    embedder: object
    budget: Budget
    cfg: Scoring
    taxonomy: Taxonomy
    hints_cfg: dict
    client: httpx.Client


def _same_synthesis_signals(previous: Signals, current: Signals) -> bool:
    if previous.rise_baseline is None:
        # Older editions stored the ratio without its baseline name.
        previous = previous.model_copy(update={'rise_baseline': current.rise_baseline})
    return previous == current


def _restore_archived_copy(topic, original, day, read_edition):
    current = next(h for h in topic.history if h.date == day)
    sources = set(current.item_ids + current.attached_item_ids)
    topic.headline = topic.summary = topic.synthesis = topic.synthesized_on = topic.synthesis_model = None
    for old in sorted(original.history, key=lambda h: h.date, reverse=True):
        if old.date > day or old.rank is None or not old.item_ids:
            continue
        if not sources.issuperset(old.item_ids + old.attached_item_ids):
            continue
        if (old.research_question, old.result_passages, old.result_review) != (
                current.research_question, current.result_passages, current.result_review):
            continue
        issue = read_edition(old.date)
        if not issue or (old.date != day and f'synthesis-fallback:{topic.slug}' in issue.run.notes):
            continue
        row = next((row for row in issue.ranked if row.slug == topic.slug), None)
        if row and row.headline:
            topic.headline, topic.summary, topic.synthesis = row.headline, row.summary, row.synthesis
            topic.synthesized_on, topic.synthesis_model = old.date, issue.run.synthesis_model
            return


def _commit(staged: Store, store: Store) -> None:
    """Replace changed files, restoring originals if a replacement fails."""
    changed = []
    created_dirs = []
    try:
        for source in sorted((staged.root / store.domain).rglob('*')):
            if not source.is_file():
                continue
            relative = source.relative_to(staged.root)
            target = store.root / relative
            if target.exists() and source.read_bytes() == target.read_bytes():
                continue
            backup = staged.root / '.rollback' / relative
            existed = target.exists()
            if existed:
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            parent = target.parent
            missing = []
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            target.parent.mkdir(parents=True, exist_ok=True)
            created_dirs.extend(reversed(missing))
            os.replace(source, target)
            changed.append((target, backup if existed else None))
    except BaseException:
        for target, backup in reversed(changed):
            if backup is None:
                target.unlink()
            else:
                os.replace(backup, target)
        for directory in reversed(created_dirs):
            directory.rmdir()
        raise


@contextmanager
def _staging(store: Store, deps: Deps, *, dry_run: bool = False):
    # Keep staging on the destination filesystem so replacement is atomic per file.
    store.root.parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='.pipeline-stage-', dir=store.root.parent))
    keep = False
    try:
        source = store.root / store.domain
        if source.exists():
            shutil.copytree(source, root / store.domain)
        budget = copy.copy(deps.budget)
        budget.path = root / store.domain / 'llm_spend.json'
        llm = copy.copy(deps.llm)
        llm.budget = budget
        staged_deps = replace(deps, budget=budget, llm=llm,
                              adapters=[copy.copy(adapter) for adapter in deps.adapters])
        before, before_usage = budget.month_spend_usd(), budget.usage()
        staged = Store(root, store.domain)
        yield staged, staged_deps
        with _stage('commit', dry_run=dry_run):
            if dry_run:
                usage = {model: {key: value - before_usage.get(model, {}).get(key, 0)
                                 for key, value in totals.items()}
                         for model, totals in budget.usage().items()}
                print(json.dumps({'staging_root': str(root), 'usage': usage,
                                  'estimated_usd': budget.month_spend_usd() - before}, sort_keys=True))
                keep = True
            else:
                _commit(staged, store)
    finally:
        if not keep:
            shutil.rmtree(root)


def _related(topics) -> None:
    if not topics:
        return
    vectors = l2_normalize([topic.centroid for topic in topics])
    for i, topic in enumerate(topics):
        distances = vectors @ vectors[i]
        neighbors = sorted((j for j in range(len(topics)) if i != j),
                           key=lambda j: (-float(distances[j]), topics[j].slug))
        topic.related = [topics[j].slug for j in neighbors[:3]]


def is_degraded(notes: list[str], source_status: dict[str, str], *,
                over_ceiling: bool, window_item_ids: set[str], cfg: Scoring) -> bool:
    count = sum(note.startswith('enrichment-fallback:') and note.split(':', 1)[1] in window_item_ids
                for note in set(notes))
    attempted = len(window_item_ids)
    return ((count > cfg.degraded_fallback_min and count > cfg.degraded_fallback_rate * attempted)
            or sum(note.startswith('synthesis-fallback:') for note in set(notes)) >= cfg.degraded_synthesis_fallback_min
            or any(note.startswith('cohesion-review-failed:') for note in notes)
            or any(source_status.get(name) in {'partial', 'failed'} for name in PAPER_SOURCES)
            or over_ceiling)


def _arxiv_categories(adapters) -> list[str] | None:
    return next((a.config['arxiv']['categories'] for a in adapters if isinstance(a, ArxivAdapter)), None)


def run_day(domain: str, day: date, store: Store, deps: Deps, *, backfill: bool = False,
            dry_run: bool = False, skip_collect: bool = False,
            only_missing_synthesis: bool = False, replay: bool = False, window_days: int | None = None,
            arxiv_announcements: bool = False) -> Day:
    if domain != store.domain:
        raise ValueError('domain does not match store')
    attention_store = store
    started = datetime.now(timezone.utc)
    with _staging(store, deps, dry_run=dry_run) as (store, deps):
        previous = store.get_day(day)
        latest = store.latest_day()
        uses_mailings = latest is not None and latest.run.arxiv_mailings is not None
        if arxiv_announcements and (domain != 'physics-expanded' or (latest and not uses_mailings)):
            raise ValueError('Start the Physics announcement comparison in a separate expanded Physics store')
        if uses_mailings and backfill:
            raise ValueError('Use the field pilot to advance a Physics announcement edition')
        if arxiv_announcements or uses_mailings:
            if not any(isinstance(a, ArxivAdapter) for a in deps.adapters):
                raise ValueError('The announcement comparison requires an arXiv source')
            deps = replace(deps, adapters=[PhysicsAnnouncements(a.config) if isinstance(a, ArxivAdapter) else a
                                           for a in deps.adapters])
        if window_days is not None:
            if window_days not in (7, 28):
                raise ValueError('Choose a 7-day or 28-day evidence window')
            if latest and latest.run.window_days != window_days:
                raise ValueError('Use a separate data root for a different evidence window')
        else:
            window_days = latest.run.window_days if latest else deps.cfg.window_days
        deps = replace(deps, cfg=deps.cfg.model_copy(update={'window_days': window_days}))
        spend_before = deps.budget.total_spend_usd()
        start = day - timedelta(days=deps.cfg.window_days - 1)
        notes = []
        source_status = initial_source_status(deps.adapters)
        arxiv_categories = previous.run.arxiv_categories if previous else None
        mailings = previous.run.arxiv_mailings if previous else None
        if replay:
            if previous is None or latest.date != day:
                raise ValueError('replay requires the latest saved edition for this field')
            backfill, skip_collect = previous.run.backfilled, True
            source_status = previous.run.source_status.copy()
            notes.extend(note for note in previous.run.notes if not note.startswith(('cohesion-review-failed:', 'synthesis-fallback:')))
            new_items = []
        elif skip_collect:
            checkpoint = store.root / domain / '.backfill_state.json'
            if checkpoint.exists():
                state = json.loads(checkpoint.read_text(encoding='utf-8'))
                arxiv_categories = state.get('arxiv_categories')
                source_status.update(dict.fromkeys(state['done_sources'], 'ok'))
                for chunk in state.get('failed_chunks', []):
                    if date.fromisoformat(chunk['start']) <= day and date.fromisoformat(chunk['end']) >= start:
                        source_status[chunk['source']] = 'failed'
                notes.extend(state.get('notes', []))
            checkpoint = store.root / domain / '.reprocess_state.json'
            if checkpoint.exists():
                state = json.loads(checkpoint.read_text(encoding='utf-8'))
                if state['range']['from'] <= day.isoformat() <= state['range']['to']:
                    original = state['runs'].get(day.isoformat(), {})
                    if original:
                        arxiv_categories = original.get('arxiv_categories')
                    source_status.update(original.get('source_status', {}))
                    notes.extend(original.get('notes', []))
                    notes.extend(state.get('notes', []))
            new_items = []
        else:
            arxiv_categories = _arxiv_categories(deps.adapters)
            collected_items = []
            for adapter in deps.adapters:
                if isinstance(adapter, GithubAdapter):
                    adapter.star_counts = store.star_counts()
                    adapter.store = store
                with _stage('collect', source=adapter.name, items=0) as counts:
                    try:
                        items = adapter.fetch(start, day, deps.client)
                        if isinstance(adapter, PhysicsAnnouncements):
                            mailings = adapter.mailings
                        counts['dropped_revisions'] = getattr(adapter, 'dropped_revisions', 0)
                    except Exception as error:
                        if isinstance(adapter, PhysicsAnnouncements):
                            raise
                        logger.warning('source=%s failed error=%s', adapter.name, type(error).__name__)
                        source_status[adapter.name] = 'failed'
                    else:
                        collected_items.extend(items)
                        source_status[adapter.name] = intake_status(adapter)
                        notes.extend(f'{reason}:{adapter.name}:{key}' for key, reason in
                                     getattr(adapter, 'decisions', {}).items() if reason in PARTIAL_REASONS)
                        counts['items'] = len(items)
                    counts['source_status'] = source_status[adapter.name]
            if all_paper_sources_failed(source_status):
                raise AllPaperSourcesFailed('All paper sources failed')
            with _stage('dedupe', items=len(collected_items)) as counts:
                successful = [a for a in deps.adapters if source_status[a.name] == 'ok']
                new_items = prepare_collected(collected_items, store, start, day, successful)
                counts['items'] = len(new_items)
            for adapter in deps.adapters:
                if isinstance(adapter, GithubAdapter) and source_status[adapter.name] == 'ok':
                    stars = store.star_counts()
                    for repo, count in adapter.observations.items():
                        history = dict(stars.get(repo, []))
                        history[day] = count
                        stars[repo] = sorted(history.items())
                    store.put_star_counts(stars)
        share_decisions = deps.taxonomy.share_editorial_decisions and not skip_collect
        refreshed = {i.id for i in new_items if i.source == 'europepmc' or
                     (i.source == 'crossref' and (i.summary is None or i.metadata.get('correction_links')))}
        with _stage('enrich', new=sum(item.summary is None for item in new_items), llm_fallbacks=0) as counts:
            new_items.sort(key=lambda item: item.id)
            for item in new_items:
                store.put_item(item)
            if share_decisions:
                active = store.items_between(start, day, by_publication=deps.taxonomy.window_by_publication)
                eligible = [i for i in active if not i.metadata.get('screening_status')]
                enrichment_notes, irrelevant = screen_window(eligible, store, deps.llm, deps.taxonomy, deps.hints_cfg, day)
            else:
                _, enrichment_notes, irrelevant = enrich_items(new_items, store, deps.llm, None,
                                                               deps.taxonomy, deps.hints_cfg)
            notes.extend(enrichment_notes)
            counts['llm_fallbacks'] = len(enrichment_notes)
            reasons = getattr(deps.llm, 'fallback_reasons', {})
            counts['fallback_reasons'] = dict(Counter(
                reasons.get(note.split(':', 1)[1], 'unknown') for note in enrichment_notes
            ))
            counts['irrelevant'] = irrelevant
        with _stage('embed', items=0) as counts:
            window = sorted(store.items_between(start, day, by_publication=deps.taxonomy.window_by_publication),
                            key=lambda item: item.id)
            window_item_ids = {item.id for item in window}
            window = [item for item in window if item.relevant]
            missing = []
            for item in window:
                if item.id in refreshed:
                    missing.append(item)
                    continue
                try:
                    store.get_embeddings([item.id])
                except KeyError:
                    missing.append(item)
            if missing:
                vectors = l2_normalize(deps.embedder.embed([item.title + '\n' + item.abstract for item in missing]))
                for item, vector in zip(missing, vectors, strict=True):
                    store.put_embedding(item.id, vector)
            counts['items'] = len(missing)
        with _stage('cluster', items=0, clusters=0) as counts:
            linked = {item.preprint_id for item in window if item.type == 'published'}
            if store.domain == 'humanities-arts':
                linked.update(parallel_openedition_ids(window))
            window = [item for item in window if item.id not in linked]
            papers = [item for item in window if item.type in {'preprint', 'published'}]
            ids = [item.id for item in papers]
            embeddings = store.get_embeddings(ids)
            clusters = cluster_items(ids, embeddings, deps.cfg)
            comparisons = {}
            if deps.taxonomy.review_cluster_cohesion:
                counts['candidates'] = len(clusters)
                clusters, review_notes, comparisons = review_clusters(clusters, papers, store, deps, day,
                                                                      share_decisions=share_decisions)
                notes.extend(review_notes)
            counts.update(items=len(ids), clusters=len(clusters))
        with _stage('continuity', topics_new=0, topics_continued=0) as counts:
            vectors_by_id = dict(zip(ids, embeddings, strict=True))
            extras = [item for item in window if item.type in {'code', 'industry'}]
            vectors_by_id.update(zip([item.id for item in extras],
                                     store.get_embeddings([item.id for item in extras]), strict=True))
            items_by_id = {item.id: item for item in window}
            topics = {topic.slug: topic for topic in store.all_topics()}
            newer_topics = {}
            if latest and latest.date > day:
                newer_topics = {slug: topic for slug, topic in topics.items()
                                if (topic.synthesized_on and topic.synthesized_on > day)
                                or any(h.rank is not None and h.date > day for h in topic.history)}
                for slug, topic in newer_topics.items():
                    topics[slug] = topic.model_copy(update={'item_one_liners': {}})
            previous_slugs = set(topics)
            items_by_topic = {}
            unchanged = set()
            centroids = [l2_normalize([np.mean([vectors_by_id[id] for id in cluster], axis=0)])[0]
                         for cluster in clusters]
            attached = attach_items(extras, vectors_by_id, centroids, deps.cfg)
            matches = sorted([
                (jaccard, similarity, index, topic.slug)
                for index, (cluster, centroid) in enumerate(zip(clusters, centroids, strict=True))
                for jaccard, similarity, topic in continuity_candidates(
                    cluster, centroid, list(topics.values()), day, deps.cfg)
            ], key=lambda row: (-row[0], -row[1], tuple(sorted(clusters[row[2]])), row[3]))
            assignments, used = {}, set()
            for _, _, index, slug in matches:
                if index not in assignments and slug not in used:
                    assignments[index] = slug
                    used.add(slug)
            week_start = day - timedelta(days=6)
            for index, (cluster, centroid) in enumerate(zip(clusters, centroids, strict=True)):
                existing = topics.get(assignments.get(index))
                comparison = comparisons.get(tuple(cluster), {})
                question = comparison.get('topic')
                review = comparison.get('result_review')
                passages = {}
                for anchor in comparison.get('evidence', []):
                    if 'reported_output' in anchor:
                        source = ' '.join(getattr(items_by_id[anchor['id']], anchor['field']).split())
                        passages[anchor['id']] = source[anchor['start']:anchor['start'] + anchor['length']]
                if existing and any(entry.date == day and entry.item_ids == cluster
                                    and entry.attached_item_ids == attached[index]
                                    and entry.research_question == question and entry.result_passages == passages
                                    and entry.result_review == review
                                    for entry in existing.history):
                    unchanged.add(existing.slug)
                topic = match_or_create(cluster, centroid, list(topics.values()),
                                        day, deps.cfg, [items_by_id[id].title for id in cluster],
                                        [item.title for item in papers], items_by_id,
                                        excluded_slugs=set(topics) - {assignments.get(index)})
                count_7d = sum((items_by_id[i].published_at if deps.taxonomy.window_by_publication
                                else items_by_id[i].first_seen) >= week_start for i in cluster)
                append_history(topic, day, cluster, count_7d, attached[index],
                               research_question=question, result_passages=passages, result_review=review)
                fill_unranked_days(topic, day, deps.cfg.continuity_max_gap_days)
                topics[topic.slug] = topic
                items_by_topic[topic.slug] = [items_by_id[id] for id in cluster + attached[index]]
            for slug, topic in topics.items():
                if slug not in items_by_topic:
                    topic.history = [entry for entry in topic.history if entry.date != day]
            counts.update(topics_new=len(set(items_by_topic) - previous_slugs),
                          topics_continued=len(set(items_by_topic) & previous_slugs))
        with _stage('score_rank'):
            stars = {repo: [(when, count) for when, count in history if when <= day]
                     for repo, history in store.star_counts().items()}
            topics_today = [(topics[slug], signals_for(topics[slug], items, stars),
                             sum(item.type in {'preprint', 'published'} for item in items))
                            for slug, items in sorted(items_by_topic.items())]
            yesterday = store.get_day(day - timedelta(days=1))
            scored = score_topics(topics_today, {row.slug for row in yesterday.ranked} if yesterday else set(),
                                  deps.cfg, day)
            ranked = rank(scored, deps.cfg)
            previous_ranked = {row.slug: row for row in previous.ranked} if previous else {}
            cached = {topic.slug for topic, signals, scores in ranked
                      if topic.slug in unchanged and topic.slug in previous_ranked
                      and _same_synthesis_signals(previous_ranked[topic.slug].signals, signals)
                      and previous_ranked[topic.slug].scores == scores
                      and previous.run.backfilled == backfill}
            read_edition = cache(store.get_day)
            for topic, _, _ in ranked:
                if topic.slug not in newer_topics or not (only_missing_synthesis or topic.slug in cached):
                    continue
                _restore_archived_copy(topic, newer_topics[topic.slug], day, read_edition)
                if not topic.headline:
                    cached.discard(topic.slug)
            if only_missing_synthesis:
                cached = {topic.slug for topic, _, _ in ranked if topic.headline}
            if refreshed:
                cached = {slug for slug in cached if not any(i.id in refreshed for i in items_by_topic[slug])}
        with _stage('synthesize', model=tier_model(1, deps.cfg, backfill, deps.budget.over_ceiling())) as counts:
            _, model, synthesis_notes = synthesize_top(
                ranked, items_by_topic,
                deps.llm, deps.budget, deps.cfg, day, backfill=backfill, skip_slugs=cached, load_day=store.get_day,
            )
            notes.extend(synthesis_notes)
            if previous:
                notes.extend(note for note in previous.run.notes if (
                    note.startswith('enrichment-fallback:') and not share_decisions and note.split(':', 1)[1] in window_item_ids
                    or note.startswith('synthesis-fallback:') and note.split(':', 1)[1] in cached))
                if ranked and ranked[0][0].slug in cached:
                    model = ranked[0][0].synthesis_model or previous.run.synthesis_model
            counts['model'] = model
        with _stage('write') as counts:
            ranks = {topic.slug: index for index, (topic, _, _) in enumerate(ranked, 1)}
            for topic, signals, scores in scored:
                entry = next(entry for entry in topic.history if entry.date == day)
                entry.rank, entry.signals, entry.scores = ranks.get(topic.slug), signals, scores
                entry.category = topic.category
                entry.secondary_categories = list(topic.secondary_categories)
            # A backfill updates that day's history, while later published topic metadata stays current.
            stored_topics = [newer_topics[slug].model_copy(update={'history': topic.history})
                             if slug in newer_topics else topic for slug, topic in topics.items()]
            _related(stored_topics)
            for topic in stored_topics:
                store.put_topic(topic)
            degraded = is_degraded(notes, source_status,
                                   over_ceiling=deps.budget.over_ceiling(),
                                   window_item_ids=window_item_ids, cfg=deps.cfg)
            same_mode = previous is not None and previous.run.backfilled == backfill
            cost = previous.run.model_cost_usd if same_mode else 0.0
            run_cost = max(0.0, deps.budget.total_spend_usd() - spend_before)
            if cost is not None:
                cost += run_cost
            result = Day(domain=domain, date=day, ranked=[RankedTopic(
                slug=topic.slug, rank=index, headline=topic.headline or topic.label.title(),
                summary=topic.summary or '', synthesis=topic.synthesis if topic.synthesized_on == day
                and f'synthesis-fallback:{topic.slug}' not in notes else None,
                category=topic.category, signals=signals, scores=scores,
            ) for index, (topic, signals, scores) in enumerate(ranked, 1)], run=RunInfo(
                started=previous.run.started if same_mode else started,
                finished=previous.run.finished if same_mode else datetime.now(timezone.utc),
                status='degraded' if degraded else 'ok', backfilled=backfill, synthesis_model=model, window_days=window_days,
                model_cost_usd=None if backfill else cost,
                source_status=source_status, arxiv_categories=arxiv_categories, arxiv_mailings=mailings,
                notes=sorted(set(notes)),
            ))
            store.put_day(result)
            counts['edition_receipt'] = json.dumps({
                'domain': domain, 'date': str(day), 'status': result.run.status, 'source_status': source_status,
                'attempt_model_cost_usd': run_cost, 'cumulative_model_cost_usd': result.run.model_cost_usd,
            }, separators=(',', ':'))
        if not backfill:
            with _stage('map'):
                store.put_map(build_map(store, deps.cfg, previous=store.get_map()))
    # Optional output commits separately so its write failure cannot roll back the day.
    if not backfill and not skip_collect and not dry_run:
        try:
            with _stage('attention'):
                payload = collect_attention(day, attention_store, deps.cfg.attention, deps.client)
                if payload is not None:
                    attention_store.put_attention(payload)
                if payload is None or payload['partial']:
                    logger.warning('stage=attention unavailable or incomplete; daily ranking unchanged')
        except Exception:
            # Never interpolate exceptions: remote responses can contain identities or tokens.
            logger.warning('stage=attention unavailable or incomplete; daily ranking unchanged')
    return result


def run_backfill(domain: str, start: date, end: date, store: Store, deps: Deps, *, resume: bool) -> None:
    if start > end:
        raise ValueError('start must not be after end')
    if domain != store.domain:
        raise ValueError('domain does not match store')
    latest = store.latest_day()
    if latest and latest.run.arxiv_mailings is not None:
        raise ValueError('Use the field pilot to advance a Physics announcement edition')
    path = store.root / domain / '.backfill_state.json'
    requested_range = {'from': start.isoformat(), 'to': end.isoformat()}
    state = {
        'range': requested_range, 'stage': 'collect', 'done_sources': [], 'last_day': None,
        'arxiv_categories': _arxiv_categories(deps.adapters),
    }
    if resume and path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if saved.get('range') == requested_range:
            if saved['stage'] == 'collect' and saved.get('arxiv_categories') != state['arxiv_categories']:
                saved['arxiv_categories'] = None
            state = saved
        else:
            previous = saved.get('range') or {}
            logger.warning('stage=backfill event=checkpoint_ignored reason=range_mismatch previous=%s..%s',
                           previous.get('from', 'unknown'), previous.get('to', 'unknown'))
    state.setdefault('failed_chunks', [])
    state.setdefault('next_chunk', {})
    state.setdefault('successful_sources', list(state['done_sources']))
    state.setdefault('collected', 0)
    store._write(path, state)
    adapters = {adapter.name: adapter for adapter in deps.adapters}

    def collect_chunk(adapter, chunk_start, chunk_end, *, retry=False):
        chunk = {'source': adapter.name, 'start': chunk_start.isoformat(), 'end': chunk_end.isoformat()}
        if isinstance(adapter, GithubAdapter):
            adapter.store = store
        with _stage('collect', source=adapter.name, chunk=f'{chunk_start}..{chunk_end}', items=0) as counts:
            try:
                items = adapter.fetch(chunk_start, chunk_end, deps.client)
                counts['dropped_revisions'] = getattr(adapter, 'dropped_revisions', 0)
                # Historical first-seen dates must not collapse onto the chunk's final day.
                items = [item.model_copy(update={'first_seen': item.published_at}) for item in items
                         if chunk_start <= item.published_at <= chunk_end]
                items = prepare_collected(sorted(items, key=lambda item: item.id), store, chunk_start, chunk_end, [adapter])
                for item in items:
                    store.put_item(item)
                if intake_status(adapter) == 'partial':
                    raise ValueError(f'Incomplete {adapter.name} collection')
            except Exception as error:
                logger.warning('stage=collect event=chunk_failed source=%s chunk=%s..%s error=%s',
                               adapter.name, chunk_start, chunk_end, type(error).__name__)
                if chunk not in state['failed_chunks']:
                    state['failed_chunks'].append(chunk)
                counts['source_status'] = 'failed'
            else:
                if isinstance(adapter, GithubAdapter) and not adapter.config['github'].get('history_seeding', False):
                    logger.info('stage=github_history event=skipped reason=disabled_in_config')
                elif isinstance(adapter, GithubAdapter):
                    discovered = sorted(adapter.repo_cache.get('repos', {}).values(),
                                        key=lambda repo: (-repo['stargazers_count'], repo['full_name']))
                    repos = list(dict.fromkeys(adapter.config['github']['watchlist'] + [
                        repo['full_name'] for repo in discovered
                        if repo['full_name'] not in adapter.config['github']['watchlist']
                    ][:100]))
                    with _stage('github_star_history', repos=len(repos)):
                        stars = store.star_counts()
                        stars.update(seed_star_history(repos, deps.client))
                        store.put_star_counts(stars, keep_days=400)
                        adapter.star_counts = stars
                counts.update(items=len(items), source_status='ok')
                state['collected'] += len(items)
                if adapter.name not in state['successful_sources']:
                    state['successful_sources'].append(adapter.name)
                if chunk in state['failed_chunks']:
                    state['failed_chunks'].remove(chunk)
                if retry and state['stage'] != 'collect':
                    # Recovered data must be enriched and included in already-written days.
                    state['stage'] = 'enrich'
                    state['last_day'] = None
            if not retry:
                state['next_chunk'][adapter.name] = (chunk_end + timedelta(days=1)).isoformat()
            store._write(path, state)

    if resume:
        for chunk in list(state['failed_chunks']):
            collect_chunk(adapters[chunk['source']], date.fromisoformat(chunk['start']),
                          date.fromisoformat(chunk['end']), retry=True)
    if state['stage'] == 'collect':
        for adapter in deps.adapters:
            if adapter.name in state['done_sources']:
                continue
            chunk_days = getattr(adapter, 'config', {}).get(adapter.name, {}).get('backfill_chunk_days', 30)
            if chunk_days < 1:
                raise ValueError('backfill_chunk_days must be positive')
            chunk_start = date.fromisoformat(state['next_chunk'].get(adapter.name, start.isoformat()))
            while chunk_start <= end:
                chunk_end = end if adapter.name == 'github' else min(chunk_start + timedelta(days=chunk_days - 1), end)
                collect_chunk(adapter, chunk_start, chunk_end)
                chunk_start = chunk_end + timedelta(days=1)
            state['done_sources'].append(adapter.name)
            store._write(path, state)
    papers = PAPER_SOURCES.intersection(adapters)
    if papers and not papers.intersection(state['successful_sources']):
        raise AllPaperSourcesFailed('All paper source chunks failed')
    if state['stage'] == 'collect':
        state['stage'] = 'enrich'
        store._write(path, state)
    if state['stage'] == 'enrich':
        pending = [item for item in store.items_between(date.min, date.max) if item.summary is None]
        for offset in range(0, len(pending), 2_000):
            chunk = pending[offset:offset + 2_000]
            hints = {item.id: hints_for(item, deps.hints_cfg) for item in chunk}
            with _stage('enrich_batch', items=len(chunk), chunk=offset // 2_000 + 1, waited=0.0) as counts:
                started = perf_counter()
                try:
                    results = deps.llm.enrich_batch(chunk, deps.taxonomy, hints)
                finally:
                    counts['waited'] = round(perf_counter() - started, 3)
                reasons = getattr(deps.llm, 'fallback_reasons', {})
                counts['fallback_reasons'] = dict(Counter(
                    reasons.get(item.id, 'unknown') for item in chunk if results.get(item.id) is None
                ))
                counts['llm_fallbacks'] = sum(counts['fallback_reasons'].values())
                counts['irrelevant'] = sum(result is not None and not result.relevant for result in results.values())
            # shortcut: batch embeds irrelevant items too; filter if embedding cost warrants a more complex chunk loop.
            vectors = l2_normalize(deps.embedder.embed([item.title + '\n' + item.abstract for item in chunk]))
            for item, vector in zip(chunk, vectors, strict=True):
                result = results.get(item.id)
                if result is None:
                    result = Enrichment(summary=fallback_summary(item)[:160],
                                        primary=next(iter(hints[item.id]), deps.taxonomy.fallback_category), secondary=[],
                                        relevant=item.type in {'preprint', 'published'})
                    state.setdefault('notes', []).append(f'enrichment-fallback:{item.id}')
                    store._write(path, state)
                store.put_embedding(item.id, vector)
                item.summary, item.primary_category = result.summary, result.primary
                item.secondary_categories = result.secondary
                item.relevant = result.relevant
                store.put_item(item)
        state['stage'] = 'days'
        store._write(path, state)
    day = max(start, date.fromisoformat(state['last_day']) + timedelta(days=1)) if state['last_day'] else start
    while day <= end:
        with _stage('day', day=day, topics=0, ranked=0) as counts:
            result = run_day(domain, day, store, deps, backfill=True, skip_collect=True)
            counts.update(topics=len(store.all_topics()), ranked=len(result.ranked))
        state['last_day'] = day.isoformat()
        store._write(path, state)
        day += timedelta(days=1)
    with _stage('map'):
        store.put_map(build_map(store, deps.cfg, previous=store.get_map()))
    summary = f"backfill_summary collected={state['collected']} failed_chunks={len(state['failed_chunks'])}"
    print(summary)
    if state['failed_chunks']:
        logger.warning(summary)
    else:
        path.unlink()
        logger.info('stage=backfill event=complete range=%s..%s', start, end)


def run_reprocess(domain: str, start: date, end: date, store: Store, deps: Deps, *,
                  reenrich: bool = False, model: str = 'claude-haiku-5-5',
                  only_missing_synthesis: bool = False, rebuild_topics: bool = False) -> None:
    validate_month_range(start, end)
    if domain != store.domain:
        raise ValueError('domain does not match store')
    latest = store.latest_day()
    if latest and latest.run.arxiv_mailings is not None:
        raise ValueError('Use replay or repair-synthesis for an existing Physics announcement edition')
    items = sorted(store.items_between(start, end), key=lambda item: item.id)
    item_ids = {item.id for item in items}
    path = store.root / domain / '.reprocess_state.json'
    request = {'command': 'reprocess', 'range': {'from': str(start), 'to': str(end)},
               'reenrich': reenrich, 'model': model, 'only_missing_synthesis': only_missing_synthesis,
               'rebuild_topics': rebuild_topics}
    if path.exists():
        state = json.loads(path.read_text(encoding='utf-8'))
        if any(state.get(key, False if key in {'only_missing_synthesis', 'rebuild_topics'} else None) != value
               for key, value in request.items()):
            raise ValueError('unfinished reprocess checkpoint has different range or options')
    else:
        runs = {}
        for result in store.all_days():
            if start <= result.date <= end:
                runs[str(result.date)] = {
                    'source_status': result.run.source_status,
                    'arxiv_categories': result.run.arxiv_categories,
                    'notes': [note for note in result.run.notes
                              if not note.startswith('synthesis-fallback:')
                              and not (reenrich and note.startswith('enrichment-fallback:')
                                       and note.split(':', 1)[1] in item_ids)],
                }
        state = {**request, 'stage': 'scope', 'next_item': 0, 'last_day': None,
                 'reenriched': 0, 'out_of_scope': 0, 'notes': [], 'runs': runs}
        store._write(path, state)
    source_cfg = next((adapter.config for adapter in deps.adapters
                       if isinstance(adapter, PubmedAdapter)), None)
    if source_cfg is None:
        source_cfg = load_config(domain)
    if state['stage'] == 'scope':
        with _stage('pubmed_scope', items=len(items), out_of_scope=0) as counts:
            for item in items:
                if not pubmed_in_scope(item, source_cfg):
                    item.relevant = False
                    item.metadata['relevance_reason'] = 'venue'
                    store.put_item(item)
                    counts['out_of_scope'] += 1
                elif item.metadata.get('relevance_reason') == 'venue':
                    item.metadata.pop('relevance_reason')
                    item.relevant = True
                    store.put_item(item)
            state['out_of_scope'] = counts['out_of_scope']
        state['stage'] = 'enrich' if reenrich else 'reset'
        store._write(path, state)
    if state['stage'] == 'enrich':
        for offset in range(state['next_item'], len(items), 2_000):
            chunk = items[offset:offset + 2_000]
            hints = {item.id: hints_for(item, deps.hints_cfg) for item in chunk}
            with _stage('enrich_batch', items=len(chunk), chunk=offset // 2_000 + 1, waited=0.0) as counts:
                started = perf_counter()
                try:
                    results = deps.llm.enrich_batch(chunk, deps.taxonomy, hints, model=model)
                finally:
                    counts['waited'] = round(perf_counter() - started, 3)
                reasons = getattr(deps.llm, 'fallback_reasons', {})
                counts['fallback_reasons'] = dict(Counter(
                    reasons.get(item.id, 'unknown') for item in chunk if results.get(item.id) is None
                ))
                counts['llm_fallbacks'] = sum(counts['fallback_reasons'].values())
                for item in chunk:
                    result = results.get(item.id)
                    if result is None:
                        result = Enrichment(summary=fallback_summary(item)[:160],
                                            primary=next(iter(hints[item.id]), deps.taxonomy.fallback_category),
                                            secondary=[], relevant=item.type in {'preprint', 'published'})
                        state['notes'].append(f'enrichment-fallback:{item.id}')
                    item.summary, item.primary_category = result.summary, result.primary
                    item.secondary_categories = result.secondary
                    item.relevant = result.relevant and not item.metadata.get('screening_status') and pubmed_in_scope(item, source_cfg)
                    store.put_item(item)
                counts['irrelevant'] = sum(not item.relevant for item in chunk)
            state['next_item'] = offset + len(chunk)
            state['reenriched'] = state['next_item']
            store._write(path, state)
        state['stage'] = 'reset'
        store._write(path, state)
    if state['stage'] == 'reset':
        with _stage('reset') as counts:
            if rebuild_topics:
                for topic in store.all_topics():
                    if topic.history and all(start <= entry.date <= end for entry in topic.history):
                        topic.headline = topic.summary = topic.synthesis = None
                        topic.synthesis_model = topic.synthesized_on = None
                        topic.item_one_liners = {}
                        store.put_topic(topic)
            # Keep topic identities and synthesis when expanding an existing leaderboard.
            if rebuild_topics or not only_missing_synthesis:
                counts.update(reset_derived(store, start, end))
        state['stage'] = 'days'
        store._write(path, state)
    day = date.fromisoformat(state['last_day']) + timedelta(days=1) if state['last_day'] else start
    while day <= end:
        with _stage('day', day=day, topics=0, ranked=0) as counts:
            result = run_day(domain, day, store, deps, backfill=True, skip_collect=True,
                             only_missing_synthesis=only_missing_synthesis)
            counts.update(topics=len(store.all_topics()), ranked=len(result.ranked))
        state['last_day'] = str(day)
        store._write(path, state)
        day += timedelta(days=1)
    with _stage('map'):
        store.put_map(build_map(store, deps.cfg, previous=store.get_map()))
    print(f"reprocess_summary days={(end - start).days + 1} "
          f"reenriched={state['reenriched']} out_of_scope={state['out_of_scope']}")
    path.unlink()


def synthesis_repair_targets(store: Store, start: date, end: date, *, retry_fallbacks: bool = False):
    """Plan repairs without writing data or making LLM calls."""
    if start > end:
        raise ValueError('start must not be after end')
    days = [day for day in store.all_days() if start <= day.date <= end]
    topics = {topic.slug: topic for topic in store.all_topics()}
    missing, rows, jobs, evidence = {}, {}, {}, {}

    def truncated(value):
        return any(text and text.endswith('…') for text in (value.headline, value.summary))

    def add_job(topic, entry):
        key = (entry.date, topic.slug)
        if key not in jobs:
            items = [store.get_item(id) for id in entry.item_ids + entry.attached_item_ids]
            if not items or any(item is None for item in items):
                raise ValueError(f'missing evidence for topic: {topic.slug} on {entry.date}')
            jobs[key], evidence[key] = entry, items
        return key

    for day in days:
        for row in day.ranked:
            topic = topics.get(row.slug)
            if topic is None:
                raise ValueError(f'missing topic: {row.slug}')
            if (not topic.headline or truncated(topic)) and topic.slug not in missing:
                entry = max((entry for entry in topic.history if entry.rank is not None),
                            key=lambda entry: entry.date, default=None)
                if entry is None:
                    raise ValueError(f'missing ranked history for topic: {topic.slug}')
                missing[topic.slug] = add_job(topic, entry)
            retry = retry_fallbacks and f'synthesis-fallback:{row.slug}' in day.run.notes
            if (retry or not row.summary or not row.headline or truncated(row)
                    or row.headline.casefold() in {topic.label.casefold(), 'untitled topic'}):
                entry = next((entry for entry in topic.history if entry.date == day.date), None)
                if entry is None:
                    raise ValueError(f'missing history for topic: {topic.slug} on {day.date}')
                key = add_job(topic, entry)
                if retry and max(e.date for e in topic.history if e.rank is not None) == day.date:
                    missing[topic.slug] = key
                item = top_evidence(evidence[key])
                # Recognize a completed item fallback even when enrichment has no summary.
                if (not retry and f'synthesis-fallback:{row.slug}' in day.run.notes
                        and (row.headline, row.summary) == fallback_copy(item)):
                    if key not in missing.values():
                        jobs.pop(key)
                        evidence.pop(key)
                    continue
                rows[key] = row
    return days, topics, missing, rows, jobs, evidence


def run_repair_synthesis(domain: str, start: date, end: date, store: Store, deps: Deps, *,
                         model: str = 'claude-haiku-5-5', retry_fallbacks: bool = False) -> None:
    """Repair synthesis only; preserve historical ranks, evidence, and map coordinates."""
    if domain != store.domain:
        raise ValueError('domain does not match store')
    days, topics, missing, rows, jobs, evidence = synthesis_repair_targets(store, start, end, retry_fallbacks=retry_fallbacks)
    degraded_before = sum(day.run.status == 'degraded' for day in days)
    fallback_rows = 0
    estimated_usd = 0.0
    if jobs:
        with _staging(store, deps) as (staged, staged_deps):
            before = staged_deps.budget.month_spend_usd()
            # Repair uses the requested model for every job, independent of leaderboard tier.
            cfg = deps.cfg.model_copy(update={'backfill_synthesis_model': model})
            editions = {day.date: day for day in days}
            for when in sorted({key[0] for key in jobs}):
                keys = sorted(key for key in jobs if key[0] == when)
                ranked = [(topics[slug].model_copy(deep=True), jobs[when, slug].signals,
                           jobs[when, slug].scores) for _, slug in keys]
                repaired, _, notes = synthesize_top(
                    ranked, {slug: evidence[when, slug] for _, slug in keys},
                    staged_deps.llm, staged_deps.budget, cfg, when, backfill=True,
                    load_day=lambda date: editions.get(date) or staged.get_day(date),
                )
                for key, topic in zip(keys, repaired, strict=True):
                    if missing.get(topic.slug) == key:
                        topic.label = topics[topic.slug].label
                        topics[topic.slug] = topic
                        staged.put_topic(topic)
                    if key in rows:
                        row = rows[key]
                        row.headline, row.summary = topic.headline, topic.summary
                        note = f'synthesis-fallback:{topic.slug}'
                        row.synthesis = topic.synthesis if topic.synthesized_on == when and note not in notes else None
                        day = editions[when]
                        day.run.notes = [saved for saved in day.run.notes if saved != note]
                        if note in notes:
                            day.run.notes.append(note)
                            fallback_rows += 1
            changed_days = [day for day in days if any((day.date, row.slug) in rows for row in day.ranked)]
            if changed_days:
                items = staged.items_between(
                    min(day.window_start for day in changed_days),
                    max(day.date for day in changed_days),
                    by_publication=deps.taxonomy.window_by_publication,
                )
                for day in changed_days:
                    window_start = day.window_start
                    degraded = is_degraded(
                        day.run.notes, day.run.source_status, over_ceiling=False, cfg=cfg,
                        window_item_ids={item.id for item in items if item.first_seen <= day.date
                                         and window_start <= (item.published_at if deps.taxonomy.window_by_publication
                                                              else item.first_seen) <= day.date},
                    )
                    day.run.status = 'degraded' if degraded else 'ok'
                    staged.put_day(day)
            if layout := staged.get_map():
                staged.put_map(published_map_editions(layout, staged))
            estimated_usd = staged_deps.budget.month_spend_usd() - before
    degraded_after = sum(day.run.status == 'degraded' for day in days)
    print(f'repair_synthesis_summary topics_repaired={len(missing)} rows_repaired={len(rows)} '
          f'rows_on_item_fallback={fallback_rows} days_degraded_before={degraded_before} '
          f'days_degraded_after={degraded_after} estimated_usd={estimated_usd:.6f}')
