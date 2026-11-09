"""B0b (pass 4): SDK retries off, 120 s per attempt; a single stall is retried by
LLMClient itself and the call still succeeds (no step toward llm_abort)."""

import logging
from unittest.mock import AsyncMock, patch

import httpx
import respx

from balatrollm.llm import LLMClient

OK = {
    "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "m",
    "choices": [{"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": "hi"}}],
}


async def test_sdk_client_has_no_internal_retries() -> None:
    client = LLMClient(base_url="https://api.test.com/v1", api_key="k")
    async with client:
        assert client._client.max_retries == 0
        assert client._client.timeout == 120.0


async def test_one_stall_then_success_is_a_success(caplog) -> None:
    client = LLMClient(base_url="https://api.test.com/v1", api_key="k")
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://api.test.com/v1/chat/completions").mock(
            side_effect=[httpx.ReadTimeout("stall"), httpx.Response(200, json=OK)]
        )
        with patch("asyncio.sleep", new_callable=AsyncMock), caplog.at_level(logging.ERROR):
            async with client:
                result = await client.call(model="m", messages=[{"role": "user", "content": "x"}], tools=[])
    assert result.choices[0].message.content == "hi"
    assert route.call_count == 2
    # the stall was seen by LLMClient (not hidden in an SDK retry) and then cleared
    assert any("LLM timeout (1/3)" in r.getMessage() for r in caplog.records)
    assert client.consecutive_timeouts == 0
