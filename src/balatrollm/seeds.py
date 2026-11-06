"""Private seed labels: runs are reported as "SEED-A", "SEED-B", ... while the
real game seeds live only in a private JSON map.

A task seed of ``RANDOM`` starts a game without a seed (the game picks one); the
bot then allocates the next free label and records the real seed after start.
A task seed of ``SEED-<label>`` replays a recorded game by its label.
"""

import json
import os
from pathlib import Path
from typing import Any

RANDOM = "RANDOM"
PREFIX = "SEED-"
DEFAULT_MAP = Path.home() / "personal_projects" / "luna-notes" / "private" / "seed_labels.json"


def map_path() -> Path:
    return Path(os.environ.get("BALATROLLM_SEED_LABELS") or DEFAULT_MAP)


def _load() -> dict[str, Any]:
    path = map_path()
    if not path.exists():
        return {"labels": {}}
    return json.loads(path.read_text())


def _save(data: dict[str, Any]) -> None:
    path = map_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)


def _label_name(n: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA, ..."""
    name = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        name = chr(ord("A") + r) + name
    return name


def is_random(seed: str) -> bool:
    return seed.upper() == RANDOM


def is_label(seed: str) -> bool:
    return seed.upper().startswith(PREFIX)


def allocate() -> str:
    """Reserve the next free label (seed filled in by ``record``)."""
    data = _load()
    labels = data.setdefault("labels", {})
    label = _label_name(len(labels))
    labels[label] = {"seed": None}
    _save(data)
    return PREFIX + label


def record(task_seed: str, seed: str) -> None:
    data = _load()
    data.setdefault("labels", {})[task_seed[len(PREFIX) :]] = {"seed": seed}
    _save(data)


def resolve(task_seed: str) -> str:
    """Real seed for ``SEED-<label>``; raises KeyError if unknown or unrecorded."""
    seed = _load().get("labels", {}).get(task_seed[len(PREFIX) :].upper(), {}).get("seed")
    if not seed:
        raise KeyError(f"No recorded seed for {task_seed}")
    return str(seed)
