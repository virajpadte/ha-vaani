"""Tests for the direct Tavily web search tool."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addons" / "pipecat_assist"))

from app.web_search_tool import create_web_search_handler, run_tavily_search, web_search_schema  # noqa: E402


_RealAsyncClient = httpx.AsyncClient


def _client_with_transport(handler):
    def factory(*_args, **_kwargs):
        return _RealAsyncClient(transport=httpx.MockTransport(handler))

    return factory


class RunTavilySearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_query_short_circuits_without_a_request(self):
        self.assertEqual(await run_tavily_search("key", ""), "No search query was provided.")

    async def test_uses_bearer_auth_and_returns_answer_field(self):
        seen: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("authorization")
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"answer": "It is sunny today.", "results": []})

        with patch("app.web_search_tool.httpx.AsyncClient", _client_with_transport(handler)):
            answer = await run_tavily_search("tavily-secret", "weather today")

        self.assertEqual(answer, "It is sunny today.")
        self.assertEqual(seen["auth"], "Bearer tavily-secret")
        self.assertEqual(seen["url"], "https://api.tavily.com/search")

    async def test_falls_back_to_result_snippets_when_no_answer(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "answer": None,
                    "results": [{"content": "Snippet one."}, {"content": "Snippet two."}],
                },
            )

        with patch("app.web_search_tool.httpx.AsyncClient", _client_with_transport(handler)):
            answer = await run_tavily_search("key", "some query")

        self.assertEqual(answer, "Snippet one. Snippet two.")

    async def test_no_results_returns_fallback_message(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"answer": None, "results": []})

        with patch("app.web_search_tool.httpx.AsyncClient", _client_with_transport(handler)):
            answer = await run_tavily_search("key", "some query")

        self.assertEqual(answer, "I could not find a useful web result.")

    async def test_http_error_propagates(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "invalid key"})

        with patch("app.web_search_tool.httpx.AsyncClient", _client_with_transport(handler)):
            with self.assertRaises(httpx.HTTPStatusError):
                await run_tavily_search("bad-key", "some query")


class WebSearchSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_handler_calls_search_runner_and_result_callback(self):
        calls: list[str] = []

        async def fake_search(query: str) -> str:
            calls.append(query)
            return "the answer"

        schema = web_search_schema(fake_search)
        self.assertEqual(schema.name, "web_search")

        results: list[str] = []

        class _Params:
            arguments = {"query": "is it raining"}

            @staticmethod
            async def result_callback(value):
                results.append(value)

        handler = create_web_search_handler(fake_search)
        await handler(_Params())

        self.assertEqual(calls, ["is it raining"])
        self.assertEqual(results, ["the answer"])

    async def test_handler_reports_failure_without_raising(self):
        async def failing_search(query: str) -> str:
            raise RuntimeError("network down")

        results: list[str] = []

        class _Params:
            arguments = {"query": "anything"}

            @staticmethod
            async def result_callback(value):
                results.append(value)

        handler = create_web_search_handler(failing_search)
        await handler(_Params())

        self.assertEqual(results, ["Web search is not available right now."])


if __name__ == "__main__":
    unittest.main()
