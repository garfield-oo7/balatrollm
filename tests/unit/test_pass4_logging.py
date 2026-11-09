"""B0a (pass 4): parallel games in one process log to their own run.log."""

import asyncio
import logging
from types import SimpleNamespace

from balatrollm import bot as botmod


def _fake_bot(run_dir):
    b = botmod.Bot.__new__(botmod.Bot)
    b._collector = SimpleNamespace(run_dir=run_dir)
    return b


def test_two_games_two_files(tmp_path):
    dirs = [tmp_path / "g1", tmp_path / "g2"]
    for d in dirs:
        d.mkdir()
    sdk = logging.getLogger("openai._base_client")  # SDK lines must follow the game too

    async def game(i: int, d):
        b = _fake_bot(d)
        b._setup_file_logging()
        try:
            for step in range(3):
                botmod.logger.info(f"game{i} step{step}")
                sdk.info(f"game{i} sdk{step}")
                await asyncio.sleep(0)  # interleave the two games
        finally:
            b._teardown_file_logging()

    async def main():
        await asyncio.gather(game(1, dirs[0]), game(2, dirs[1]))

    asyncio.run(main())
    t1 = (dirs[0] / "run.log").read_text()
    t2 = (dirs[1] / "run.log").read_text()
    assert t1.count("game1") == 6 and "game2" not in t1
    assert t2.count("game2") == 6 and "game1" not in t2
    # line format unchanged (digest regexes): "<date> <time> - <name> - INFO - <msg>"
    first = t1.splitlines()[0]
    assert " - balatrollm.bot - INFO - game1 step0" in first
    # handlers removed after the games
    assert not [h for h in logging.getLogger().handlers if isinstance(h.filters[0] if h.filters else None, botmod._RunFilter)]


def test_line_outside_a_game_goes_to_no_run_log(tmp_path):
    d = tmp_path / "g"
    d.mkdir()

    async def main():
        b = _fake_bot(d)
        b._setup_file_logging()
        botmod.logger.info("inside")
        b._teardown_file_logging()

    asyncio.run(main())
    botmod.logger.info("outside")
    assert (d / "run.log").read_text().count("inside") == 1
    assert "outside" not in (d / "run.log").read_text()
