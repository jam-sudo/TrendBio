import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from pipeline.models import Item


def dump(model: BaseModel, path: Path) -> None:
    text = json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def load[T: BaseModel](cls: type[T], path: Path) -> T:
    return cls.model_validate_json(path.read_text(encoding="utf-8"))


def item_path(root: Path, domain: str, item: Item) -> Path:
    filename = item.id.replace(":", "_").replace("/", "_") + ".json"
    return root / domain / "items" / item.first_seen.strftime("%Y/%m") / filename


def topic_path(root: Path, domain: str, slug: str) -> Path:
    return root / domain / "topics" / f"{slug}.json"


def day_path(root: Path, domain: str, day: date) -> Path:
    return root / domain / "days" / f"{day.isoformat()}.json"


def embeddings_shard_path(root: Path, domain: str, month: str) -> tuple[Path, Path]:
    directory = root / domain / "embeddings"
    return directory / f"{month}.npy", directory / f"{month}.index.json"
