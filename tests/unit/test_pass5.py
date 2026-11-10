"""Pass 5 harness fixes (one small test per fix that changes a score or could block a legal move)."""

from typing import Any

from balatrollm import analysis

from .test_analysis import card, joker, make_state


def _n05(two_debuffed: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """A1 N05 at The Pillar: Pair 8♥ 8♣ with K♣, Q♦ (debuffed), J♠, 9♥, 7♦, Steel 2♠ (debuffed) held."""
    jokers = [
        joker("j_mad", "Mad Joker"),
        joker("j_raised_fist", "Raised Fist"),
        joker("j_riff_raff", "Riff-raff", edition="FOIL"),
        joker("j_sly", "Sly Joker"),
        joker("j_gros_michel", "Gros Michel"),
    ]
    G = make_state("C_K D_Q S_J H_9 H_8 C_8 D_7 S_2", jokers, boss="The Pillar", boss_current=True,
                   hands_left=1, discards_left=0)
    cards = G["hand"]["cards"]
    cards[1]["state"] = {"debuff": True}
    cards[7]["modifier"] = {"enhancement": "STEEL"}
    cards[7]["set"] = "ENHANCED"
    if two_debuffed:
        cards[7]["state"] = {"debuff": True}
    played = [cards[4], cards[5]]
    held = [c for i, c in enumerate(cards) if i not in (4, 5)]
    return G, played, held


def test_raised_fist_picks_a_debuffed_lowest_card_and_adds_nothing() -> None:
    G, played, held = _n05()
    # chips 10 + 8 + 8 + 50 (Foil) + 50 (Sly) = 126; mult 2 + 0 (Raised Fist on the debuffed 2♠) + 15 = 17
    assert analysis.estimate_play(G, played, held)["score"] == 2142


def test_raised_fist_still_fires_on_a_live_lowest_card() -> None:
    G, played, held = _n05(two_debuffed=False)
    # Steel 2♠ live: mult (2 x 1.5) + 4 (Raised Fist) + 15 = 22 -> 126 x 22
    assert analysis.estimate_play(G, played, held)["score"] == 2772


def test_raised_fist_tie_goes_to_the_last_card_in_hand() -> None:
    G = make_state("H_A D_A H_7 D_7", [joker("j_raised_fist", "Raised Fist")])
    cards = G["hand"]["cards"]
    played = cards[:2]
    cards[3]["state"] = {"debuff": True}  # 7♦ debuffed and last: the game picks it -> +0
    base = analysis.estimate_play(G, played, [cards[2], cards[3]])["score"]
    flipped = analysis.estimate_play(G, played, [cards[3], cards[2]])["score"]  # 7♥ last -> +14
    assert base == (10 + 22) * 2
    assert flipped == (10 + 22) * (2 + 14)


def test_the_mouth_lock_is_the_first_type_played() -> None:
    G = make_state("H_A D_A S_9 C_7 H_5", boss="The Mouth", boss_current=True, hands_left=2)
    # Flush played first, then a (blocked) High Card: both read played_this_round
    G["hands"]["Flush"]["played_this_round"] = 1
    G["hands"]["High Card"]["played_this_round"] = 1
    G["luna"] = {"mouth_lock": "Flush"}
    A = analysis.play_advice(G)
    assert all(p["blocked"] for p in A["plays"] if p["hand"] != "Flush")
    assert not A["action"]["why"].startswith("best play (High Card")


def test_no_discard_suggested_with_no_discards_left() -> None:
    G = make_state("H_A D_K S_9 C_7 H_5", boss="The Fish", boss_current=True, hands_left=2, discards_left=0)
    for c in G["hand"]["cards"]:
        c["state"] = {"hidden": True}
    A = analysis.play_advice(G)
    assert A["action"]["tool"] == "play" and len(A["action"]["cards"]) == 5


def test_wrong_item_check_ignores_a_leading_the() -> None:
    offers = {0: "The High Priestess", 1: "Jolly Joker"}
    assert analysis.wrong_item_veto(offers, 0, "High Priestess makes two planets.") is None
    # a longer name containing a shorter one does not name the shorter one
    offers = {0: "The Moon", 1: "Shoot the Moon"}
    assert analysis.wrong_item_veto(offers, 1, "Shoot the Moon adds mult for held Queens.") is None
    assert analysis.wrong_item_veto(offers, 0, "Shoot the Moon adds mult for held Queens.") is not None
    assert analysis.wrong_item_veto(offers, 1, "The Moon makes Clubs.") is not None


async def test_policy_400_identical_retry_then_reworded_then_error_call() -> None:
    import json as _json
    from unittest.mock import AsyncMock, patch

    import httpx
    import pytest
    import respx

    from balatrollm.llm import POLICY_REWORD, LLMClient, LLMPolicyRefusalError

    ok = {"id": "x", "object": "chat.completion", "created": 0, "model": "m",
          "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "hi"}}]}
    flagged = httpx.Response(400, json={"error": {"message": "Invalid prompt: flagged as potentially violating our usage policy",
                                                  "type": "invalid_request_error"}})
    url = "https://api.test.com/v1/chat/completions"
    msgs = [{"role": "user", "content": "x"}]
    with patch("asyncio.sleep", new_callable=AsyncMock):
        with respx.mock() as mock:
            route = mock.post(url).mock(side_effect=[flagged, flagged, httpx.Response(200, json=ok)])
            async with LLMClient(base_url="https://api.test.com/v1", api_key="k") as client:
                assert (await client.call(model="m", messages=msgs, tools=[])).choices[0].message.content == "hi"
            bodies = [_json.loads(c.request.content) for c in route.calls]
            assert bodies[0] == bodies[1]  # first retry identical
            assert bodies[2]["messages"][-1]["content"].endswith(POLICY_REWORD)
            assert msgs == [{"role": "user", "content": "x"}]  # caller's messages untouched
        with respx.mock() as mock:
            mock.post(url).mock(side_effect=[flagged, flagged, flagged])
            async with LLMClient(base_url="https://api.test.com/v1", api_key="k") as client:
                with pytest.raises(LLMPolicyRefusalError):
                    await client.call(model="m", messages=msgs, tools=[])
