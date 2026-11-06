import json
import os
import tempfile
from datetime import date, timedelta
from glob import escape
from pathlib import Path

import numpy as np

from pipeline.jsonio import day_path, dump, embeddings_shard_path, item_path, load, topic_path
from pipeline.models import Day, Item, MapData, Topic


class Store:
    def __init__(self, root: Path, domain: str):
        self.root = root
        self.domain = domain

    def _write(self, path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        os.close(descriptor)
        temporary = Path(name)
        try:
            if isinstance(value, np.ndarray):
                with temporary.open("wb") as stream:
                    np.save(stream, value, allow_pickle=False)
            elif isinstance(value, dict):
                temporary.write_text(
                    json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            else:
                dump(value, temporary)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _item_paths(self, id: str | None = None) -> list[Path]:
        # Only id and first_seen are used by the shared path helper.
        probe = Item.model_construct(id=id or "", first_seen=date(2000, 1, 1))
        path = item_path(self.root, self.domain, probe)
        filename = escape(path.name) if id is not None else "*.json"
        return sorted(path.parents[2].glob(f"*/*/{filename}"))

    def put_item(self, item: Item) -> None:
        existing = self.get_item(item.id)
        if existing is not None:
            # Rediscovery must preserve the original item and embedding shard.
            item = item.model_copy(update={"first_seen": existing.first_seen})
        self._write(item_path(self.root, self.domain, item), item)

    def get_item(self, id: str) -> Item | None:
        for path in self._item_paths(id):
            item = load(Item, path)
            if item.id == id:
                return item
        return None

    def items_between(self, start: date, end: date) -> list[Item]:
        items = (load(Item, path) for path in self._item_paths())
        return sorted(
            (item for item in items if start <= item.first_seen <= end),
            key=lambda item: (item.first_seen, item.id),
        )

    def has_item(self, id: str) -> bool:
        return self.get_item(id) is not None

    def put_topic(self, topic: Topic) -> None:
        self._write(topic_path(self.root, self.domain, topic.slug), topic)

    def get_topic(self, slug: str) -> Topic | None:
        path = topic_path(self.root, self.domain, slug)
        return load(Topic, path) if path.exists() else None

    def all_topics(self) -> list[Topic]:
        directory = topic_path(self.root, self.domain, "").parent
        return [load(Topic, path) for path in sorted(directory.glob("*.json"))]

    def put_map(self, data: MapData) -> None:
        self._write(self.root / self.domain / 'map.json', data)

    def get_map(self) -> MapData | None:
        path = self.root / self.domain / 'map.json'
        return load(MapData, path) if path.exists() else None

    def put_attention(self, payload: dict) -> None:
        self._write(self.root / self.domain / 'attention' / f"{payload['date']}.json", payload)

    def put_day(self, day: Day) -> None:
        self._write(day_path(self.root, self.domain, day.date), day)

    def get_day(self, date: date) -> Day | None:
        path = day_path(self.root, self.domain, date)
        return load(Day, path) if path.exists() else None

    def all_days(self) -> list[Day]:
        directory = day_path(self.root, self.domain, date.min).parent
        return [load(Day, path) for path in sorted(directory.glob("*.json"))]

    def put_embedding(self, item_id: str, vec: np.ndarray) -> None:
        item = self.get_item(item_id)
        if item is None:
            raise KeyError(item_id)
        vec = np.asarray(vec)
        if vec.ndim != 1 or vec.size == 0:
            raise ValueError("embedding must be a nonempty vector")
        if not np.isfinite(vec).all() or np.any(np.abs(vec) > np.finfo(np.float16).max):
            raise ValueError("embedding must contain finite float16 values")
        vec = vec.astype(np.float16)
        path, index_path = embeddings_shard_path(
            self.root, self.domain, item.first_seen.strftime("%Y-%m")
        )
        index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
        if index:
            # Discard a trailing row left by an interrupted index write.
            matrix = np.load(path, allow_pickle=False)[:len(index)]
            if matrix.shape[1] != vec.size:
                raise ValueError("embedding dimension differs from the month shard")
        else:
            matrix = np.empty((0, vec.size), dtype=np.float16)
        if item_id in index:
            matrix[index[item_id]] = vec
        else:
            index[item_id] = len(index)
            matrix = np.vstack((matrix, vec))
        # Data precedes the index so an interruption cannot publish a missing row.
        self._write(path, matrix)
        self._write(index_path, index)

    def get_embeddings(self, ids: list[str]) -> np.ndarray:
        shards = {}
        rows = []
        for item_id in ids:
            item = self.get_item(item_id)
            if item is None:
                raise KeyError(item_id)
            month = item.first_seen.strftime("%Y-%m")
            if month not in shards:
                path, index_path = embeddings_shard_path(self.root, self.domain, month)
                if not path.exists() or not index_path.exists():
                    raise KeyError(item_id)
                shards[month] = (
                    np.load(path, allow_pickle=False),
                    json.loads(index_path.read_text(encoding="utf-8")),
                )
            matrix, index = shards[month]
            if item_id not in index:
                raise KeyError(item_id)
            rows.append(matrix[index[item_id]])
        return np.stack(rows).astype(np.float32) if rows else np.empty((0, 0), dtype=np.float32)

    def github_repos(self) -> dict:
        path = self.root / self.domain / "github_repos.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def put_github_repos(self, payload: dict) -> None:
        self._write(self.root / self.domain / "github_repos.json", payload)

    def star_counts(self) -> dict[str, list[tuple[date, int]]]:
        path = self.root / self.domain / "github_stars.json"
        if not path.exists():
            return {}
        return {
            repo: [(date.fromisoformat(row["date"]), row["stars"]) for row in history]
            for repo, history in json.loads(path.read_text(encoding="utf-8")).items()
        }

    def put_star_counts(self, counts: dict[str, list[tuple[date, int]]], *, keep_days: int = 60) -> None:
        """Replace history, retaining keep_days calendar days ending at its latest date."""
        if keep_days < 1:
            raise ValueError('keep_days must be positive')
        latest = max((day for history in counts.values() for day, _ in history), default=None)
        cutoff = latest - timedelta(days=keep_days - 1) if latest is not None else date.min
        self._write(self.root / self.domain / "github_stars.json", {
            repo: [{"date": day.isoformat(), "stars": stars}
                   for day, stars in sorted(history) if day >= cutoff]
            for repo, history in counts.items()
        })
