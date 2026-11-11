"""Task execution for BalatroLLM runs."""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from balatrobot import BalatroInstance
from balatrobot import Config as BalatrobotConfig

from . import book
from .bot import Bot
from .config import Config, Task

logger = logging.getLogger(__name__)

# Pass 6 H1g: Lovely names its log by the start second, so instances started
# in the same second share one file. Instances now start one at a time, each
# after its own new log file appears (or this many seconds, then unmapped).
LOVELY_LOG_WAIT_S = 20.0
LOVELY_LOG_SUBDIR = "pfx/drive_c/users/steamuser/AppData/Roaming/Balatro/Mods/lovely/log"
LOVELY_PORT_RE = re.compile(r"HTTP server listening on http://[^:\s]+:(\d+)")

MUTTER = ("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig", "org.gnome.Mutter.DisplayConfig")


async def wake_display() -> None:
    """Pass 5 G1g: set GNOME Mutter's PowerSaveMode to 0 (on) when it is not.
    Best effort: no session bus or no Mutter -> nothing happens."""

    async def busctl(*args: str) -> tuple[int, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "busctl", "--user", *args,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            return proc.returncode or 0, out.decode().strip()
        except (OSError, asyncio.TimeoutError):
            return 1, ""

    code, out = await busctl("get-property", *MUTTER, "PowerSaveMode")
    if code != 0 or out == "i 0":
        return
    logger.warning(f"Display power-save is on ({out}): waking it before starting Balatro")
    await busctl("set-property", *MUTTER, "PowerSaveMode", "i", "0")
    await asyncio.sleep(3)


def lovely_log_dir() -> Path | None:
    """The shared Proton prefix's Lovely log dir, or None when not found.
    Same lookup as balatrobot's Linux launcher (STEAM_COMPAT_DATA_PATH, else
    the Steam root's compatdata for Balatro)."""
    try:
        compat = os.environ.get("STEAM_COMPAT_DATA_PATH")
        if compat:
            base: Path | None = Path(compat)
        else:
            from balatrobot.platforms import linux

            root = linux._detect_steam_root()
            base = linux._detect_compat_data_path(root) if root else None
        d = base / LOVELY_LOG_SUBDIR if base else None
        return d if d is not None and d.is_dir() else None
    except Exception:  # noqa: BLE001 - a missing log dir never blocks a start
        return None


def _warn(msg: str) -> None:
    """A startup warning in both the log (stderr) and the queue log (stdout)."""
    logger.warning(msg)
    print(f"WARNING: {msg}")


def _lovely_logs(d: Path) -> set[Path]:
    try:
        return set(d.glob("lovely-*.log"))
    except OSError:
        return set()


def _lovely_port(path: Path) -> int | None:
    """The port in the balatrobot "HTTP server listening" line of a Lovely log."""
    try:
        with open(path, errors="replace") as f:
            for line in f:
                m = LOVELY_PORT_RE.search(line)
                if m:
                    return int(m.group(1))
    except OSError:
        pass
    return None


@dataclass
class Executor:
    """Executes tasks with parallelism."""

    config: Config
    tasks: list[Task]
    runs_dir: Path = field(default_factory=Path.cwd)

    _instances: dict[int, BalatroInstance] = field(
        default_factory=dict, init=False, repr=False
    )
    _port_pool: asyncio.Queue[int] = field(
        default_factory=asyncio.Queue, init=False, repr=False
    )
    _shutdown: asyncio.Event = field(
        default_factory=asyncio.Event, init=False, repr=False
    )

    async def run(self) -> None:
        """Execute all tasks."""
        ports = range(self.config.port, self.config.port + self.config.parallel)
        try:
            await self._start_instances(ports)
            await self._execute_tasks()
        except asyncio.CancelledError:
            print("\nInterrupted! Cleaning up...")
            raise
        finally:
            await self._stop_instances()
        print("Done.")

    async def _start_instances(self, ports: range) -> None:
        """Start Balatro instances.

        Pass 5 G1g: wake the display first (pass 4 L1: four startups failed the
        30 s health check with the display in power-save); every instance runs
        in one Wine prefix and a failed check runs ``wineserver -k`` on it, so on
        any failure all instances are stopped, the display woken again and the
        whole set started once more. A second failure raises.
        """
        cfg = BalatrobotConfig.from_env()
        for attempt in (1, 2):
            await wake_display()
            # Create all instances with shared session_id (pass 6 H1g: set
            # explicitly, since one-at-a-time starts span several seconds)
            session_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
            instances = [
                (port, BalatroInstance(cfg, session_id=session_id, port=port)) for port in ports
            ]
            results = await self._start_one_by_one(instances, Path(cfg.logs_path) / session_id)
            failed = [(port, r) for (port, _), r in zip(instances, results) if isinstance(r, BaseException)]
            if not failed:
                break
            for port, err in failed:
                logger.error(f"Startup attempt {attempt}: instance on port {port} failed: {err}")
            await asyncio.gather(*(i.stop() for _, i in instances), return_exceptions=True)
            if attempt == 2:
                raise RuntimeError(f"Startup failed twice ({len(failed)} instance(s) on the second try)") from failed[0][1]
            logger.warning("Startup failed: all instances stopped; waking the display and starting again once")
            await asyncio.sleep(5)

        # Register instances in pool
        for port, instance in instances:
            self._instances[port] = instance
            await self._port_pool.put(port)

    async def _start_one_by_one(
        self, instances: list[tuple[int, BalatroInstance]], session_dir: Path
    ) -> list[BaseException | None]:
        """Pass 6 H1g: start the instances one at a time, each after a NEW
        Lovely log file appears in the prefix's log dir (or LOVELY_LOG_WAIT_S,
        then the instance goes on unmapped with a warning); health waits
        overlap. Writes ``lovely_logs.json`` (port -> Lovely log file) into the
        session dir. A missing log or log dir never blocks or fails a start."""
        log_dir = lovely_log_dir()
        if log_dir is None:
            _warn("Lovely log dir not found: instances start without a port -> log map")
        seen = _lovely_logs(log_dir) if log_dir else set()
        before = set(seen)
        tasks: list[asyncio.Task[None]] = []
        found: dict[int, Path] = {}
        try:
            await self._launch_each(instances, log_dir, seen, tasks, found)
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except BaseException:
            # cancelled while starting: do not leave started instances behind
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.gather(*(i.stop() for _, i in instances), return_exceptions=True)
            raise
        if log_dir is not None:
            self._write_lovely_map(instances, found, _lovely_logs(log_dir) - before, session_dir)
        return list(results)

    @staticmethod
    async def _launch_each(
        instances: list[tuple[int, BalatroInstance]],
        log_dir: Path | None,
        seen: set[Path],
        tasks: list[asyncio.Task[None]],
        found: dict[int, Path],
    ) -> None:
        for port, instance in instances:
            task = asyncio.create_task(instance.start())
            tasks.append(task)
            if log_dir is None:
                continue
            deadline = time.monotonic() + LOVELY_LOG_WAIT_S
            new: set[Path] = set()
            while time.monotonic() < deadline and not task.done():
                await asyncio.sleep(0.25)
                new = _lovely_logs(log_dir) - seen
                if new:
                    break
            if not new:
                new = _lovely_logs(log_dir) - seen
            if new:
                path = max(new, key=lambda q: q.name)
                seen |= new
                found[port] = path
                # Lovely names the file by its start second: start the next
                # instance in a later second so the names cannot collide
                await asyncio.sleep(1.0)
            else:
                _warn(
                    f"No new Lovely log for port {port} within {LOVELY_LOG_WAIT_S:g} s: "
                    "starting the next instance (this one stays unmapped)"
                )

    @staticmethod
    def _write_lovely_map(
        instances: list[tuple[int, BalatroInstance]],
        found: dict[int, Path],
        new_logs: set[Path],
        session_dir: Path,
    ) -> None:
        """Map port -> Lovely log: the balatrobot "HTTP server listening ...
        :<port>" line in any log new since the start (a late file is still
        placed right), else start order."""
        logged = {path: _lovely_port(path) for path in new_logs | set(found.values())}
        by_line = {p: path for path, p in logged.items() if p is not None}
        mapping: dict[str, dict[str, str] | None] = {}
        for port, _ in instances:
            path = by_line.get(port)
            how = "server line"
            if path is None and port in found and logged[found[port]] is None:
                path, how = found[port], "start order"
            mapping[str(port)] = {"file": str(path), "by": how} if path else None
        files = {m["file"] for m in mapping.values() if m}
        if len(files) < len(instances):
            _warn(f"Only {len(files)} distinct Lovely log(s) for {len(instances)} instance(s)")
        # print, like the executor's other progress lines (queue log)
        print(
            "Lovely logs: "
            + ", ".join(f"{p} -> {Path(m['file']).name if m else 'unmapped'}" for p, m in mapping.items())
        )
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "lovely_logs.json").write_text(json.dumps(mapping, indent=2) + "\n")
        except OSError as e:
            _warn(f"Could not write lovely_logs.json: {e}")

    async def _stop_instances(self) -> None:
        """Stop all instances."""
        await asyncio.gather(
            *(i.stop() for i in self._instances.values()),
            return_exceptions=True,
        )
        self._instances.clear()

    async def _execute_tasks(self) -> None:
        """Execute tasks with port pool."""
        total = len(self.tasks)
        count = 0
        # Pass 5 G2: book updates merge in task (label) order as games finish;
        # each update names its own store, so every arm merges in label order
        merges = book.MergeQueue(total)

        def merged(i: int, bot: Bot | None) -> None:
            try:
                for rec in merges.done(i, getattr(bot, "book_update_path", None)):
                    logger.info(f"Book merge {rec['label']}: game {rec['game']} -> {rec['new']} {rec['edits']}")
            except Exception:
                logger.exception("Book merge failed")

        async def run_task(i: int, task: Task) -> None:
            nonlocal count
            if self._shutdown.is_set():
                merged(i, None)
                return
            port = await self._port_pool.get()
            bot: Bot | None = None
            try:
                count += 1
                instance = self._instances[port]
                log_path = instance.log_path
                print(
                    f"[{count:0{len(str(total))}d}/{total}] STARTED   | {log_path} | {task}"
                )
                bot = Bot(task=task, config=self.config, port=port)
                async with bot:
                    await bot.play(self.runs_dir)
                print(
                    f"[{count:0{len(str(total))}d}/{total}] COMPLETED | {log_path} | {task}"
                )
            except Exception:
                logger.exception(f"Run failed: {task}")
                print(
                    f"[{count:0{len(str(total))}d}/{total}] ERROR     | {log_path} | {task}"
                )
            finally:
                merged(i, bot)
                await asyncio.sleep(1)
                await self._port_pool.put(port)

        pending = [asyncio.create_task(run_task(i, t)) for i, t in enumerate(self.tasks)]
        try:
            await asyncio.gather(*pending, return_exceptions=True)
            merges.flush()
        except asyncio.CancelledError:
            self._shutdown.set()
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            try:
                merges.flush()
            except Exception:
                logger.exception("Book merge failed")
            raise
