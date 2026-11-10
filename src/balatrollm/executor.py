"""Task execution for BalatroLLM runs."""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

from balatrobot import BalatroInstance
from balatrobot import Config as BalatrobotConfig

from . import book
from .bot import Bot
from .config import Config, Task

logger = logging.getLogger(__name__)

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
            # Create all instances with shared session_id
            instances = [(port, BalatroInstance(cfg, port=port)) for port in ports]
            results = await asyncio.gather(
                *(instance.start() for _, instance in instances), return_exceptions=True
            )
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
