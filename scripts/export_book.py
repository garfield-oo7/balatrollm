"""Export one arm's write-only log book to Markdown (pass 5 G2).

    .venv/bin/python scripts/export_book.py <store> <arm> <out.md>

<store> is ``<runs_dir>/runs/book/<arm>``. Writes a header (arm, code commit,
games, store HEAD), one section per writeups.jsonl row in label order (label,
finish reason, final ante, write-up, edits proposed / kept / rejected), then
the final rule list from HEAD. The output is run through the book's Redactor
and seed / hand-position checks; only counts are printed (never a seed).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from balatrollm import book

ROOT = Path(book.__file__).resolve().parent


def _label_key(row: dict) -> tuple:
    label = str(row.get("label") or "")
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", label)), int(row.get("game") or 0)


def _commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "?"


def _words() -> set[str]:
    texts = [(ROOT / "knowledge.py").read_text(), book.writeup_system(book.EMPTY)]
    for name in ("mastery", "mastery-noadvice"):
        for f in sorted((ROOT / "strategies" / name).glob("*.jinja")):
            texts.append(f.read_text())
    return book.known_words(*texts)


def _edit_text(e: object) -> str:
    if not isinstance(e, dict):
        return f"(malformed: {str(e)[:120]})"
    out = str(e.get("op") or "?")
    if e.get("id"):
        out += f" {e['id']}"
    if e.get("text"):
        out += f": {e['text']}"
    return out


def export(store: Path, arm: str) -> tuple[str, list[str]]:
    """(markdown, bodies to check: write-ups, kept edits, final rules;
    rejected edits are shown but expected to fail the checks)."""
    rows = []
    path = store / "writeups.jsonl"
    if path.exists():
        rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    rows.sort(key=_label_key)
    head = (store / "HEAD").read_text().strip() if (store / "HEAD").exists() else None
    version = book.read_version(store, head) if head else dict(book.EMPTY)
    bodies: list[str] = []
    out = [f"# Luna's book: {arm}", "",
           f"- Arm: {arm}", f"- Code commit: {_commit()}", f"- Games: {version.get('games', 0)} "
           f"({len(rows)} write-up rows)", f"- Store HEAD: {head}", ""]
    for r in rows:
        out += [f"## {r.get('label')} (game {r.get('game')})", "",
                f"- Finish: {r.get('finish_reason')}; final ante {r.get('final_ante')}"]
        if r.get("error"):
            out.append(f"- Call error: {r['error']}")
        wu = r.get("writeup")
        out.append(f"- Write-up: {wu}" if wu else f"- Write-up: (none: {', '.join(r.get('writeup_problems') or []) or 'no reply'}); "
                   f"code summary: {r.get('code_summary')}")
        if wu:
            bodies.append(wu)
        proposed = r.get("proposed") if isinstance(r.get("proposed"), list) else []
        out.append(f"- Edits proposed: {len(proposed)}, kept {len(r.get('kept') or [])}, rejected {len(r.get('rejected') or [])}")
        for e, m in zip(r.get("kept") or [], r.get("merge") or []):
            out.append(f"  - kept: {_edit_text(e)} -> {m.get('result')}{' ' + m['id'] if m.get('id') and m.get('op') == 'add' else ''}")
            if isinstance(e, dict) and e.get("text"):
                bodies.append(e["text"])
        for rej in r.get("rejected") or []:
            out.append(f"  - rejected: {_edit_text(rej.get('edit'))} ({'; '.join(rej.get('why') or [])})")
        out.append("")
    rules = version.get("rules") or []
    out += [f"## Final rules ({len(rules)})", ""]
    for rule in rules:
        out.append(f"- [{rule['id']}] {rule['text']} (added game {rule.get('added_game')}, changed game {rule.get('changed_game')})")
        bodies.append(rule["text"])
    return "\n".join(out) + "\n", bodies


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    store, arm, dest = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    text, bodies = export(store, arm)
    words = _words()
    redacted = book.Redactor(None, words)(text)
    n_redacted = redacted.count(book.REDACTED) - text.count(book.REDACTED)
    seed_hits = sum(1 for b in bodies if any("seed" in p for p in book.text_problems(b, None, words, one_seed=False)))
    position_hits = sum(1 for b in bodies if any("position" in p for p in book.text_problems(b, None, words, one_seed=False)))
    dest.write_text(redacted)
    print(f"wrote {dest}: {len(bodies)} texts checked; redacted {n_redacted}; seed problems {seed_hits}; "
          f"hand-position problems {position_hits}")


if __name__ == "__main__":
    main()
