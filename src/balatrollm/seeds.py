"""Private seed labels: runs are reported as "SEED-A", "SEED-B", ... while the
real game seeds live only in a private JSON map.

A task seed of ``RANDOM`` gets a fresh seed generated here (the game's own
seedless start repeats under the bot: its seed comes from the cursor position and
a frame-counted timer, both constant). The seed is recorded under the next free
label BEFORE the game starts, and the bot checks the game started on it.
A task seed of ``SEED-<label>`` replays a recorded game by its label.
"""

import json
import os
import secrets
from pathlib import Path
from typing import Any

RANDOM = "RANDOM"
PREFIX = "SEED-"
# Balatro's own seed alphabet (random_string in functions/misc_functions.lua): no 0, no O.
ALPHABET = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
SEED_LENGTH = 8
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


def generate(existing: set[str]) -> str:
    """A random seed from the game's alphabet that is not in ``existing``."""
    while True:
        seed = "".join(secrets.choice(ALPHABET) for _ in range(SEED_LENGTH))
        if seed not in existing:
            return seed


def new_random() -> tuple[str, str]:
    """Generate a fresh seed, record it under the next free label, and return
    ``(SEED-<label>, seed)``. Recorded before the game starts."""
    data = _load()
    labels = data.setdefault("labels", {})
    used = {str(v.get("seed")) for v in labels.values() if v.get("seed")}
    seed = generate(used)
    label = _label_name(len(labels))
    labels[label] = {"seed": seed}
    _save(data)
    return PREFIX + label, seed


def started_on(seed: str, gamestate: dict[str, Any]) -> bool:
    """True if the gamestate returned by ``start`` is on ``seed``."""
    return str(gamestate.get("seed") or "") == seed


def resolve(task_seed: str) -> str:
    """Real seed for ``SEED-<label>``; raises KeyError if unknown or unrecorded."""
    seed = _load().get("labels", {}).get(task_seed[len(PREFIX) :].upper(), {}).get("seed")
    if not seed:
        raise KeyError(f"No recorded seed for {task_seed}")
    return str(seed)
