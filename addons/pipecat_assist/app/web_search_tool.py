"""Web search tool exposed directly to the model.

No LLM does the searching: the model calls this tool, which hits Tavily's
search API directly and returns a short, already-ranked answer. This is
simpler and lower-latency than the old approach of asking a second LLM
(OpenAI/Gemini) to run a search on the model's behalf, which was removed
along with those providers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import httpx
from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema

if TYPE_CHECKING:
    from pipecat.services.llm_service import FunctionCallParams


WEB_SEARCH_TOOL_NAME = "web_search"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
SearchRunner = Callable[[str], Awaitable[str]]


async def run_tavily_search(api_key: str, query: str) -> str:
    """Run a Tavily search and return a short, speakable answer."""

    query = (query or "").strip()
    if not query:
        return "No search query was provided."

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            TAVILY_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "search_depth": "basic",
                "include_answer": True,
                "max_results": 3,
            },
        )
        response.raise_for_status()
    data = response.json()

    answer = str(data.get("answer") or "").strip()
    if answer:
        return answer

    results = data.get("results") if isinstance(data.get("results"), list) else []
    snippets = [
        str(item.get("content") or "").strip()
        for item in results
        if isinstance(item, dict) and item.get("content")
    ]
    if snippets:
        return " ".join(snippets[:2])[:500]
    return "I could not find a useful web result."


def create_web_search_handler(search_runner: SearchRunner):
    """Return a Pipecat function-call handler for web search."""

    async def handler(params: "FunctionCallParams") -> None:
        query = str((params.arguments or {}).get("query", "")).strip()
        logger.info("web_search called: {!r}", query)
        try:
            answer = await search_runner(query)
        except Exception as err:
            logger.warning("web_search failed: {}", err)
            answer = "Web search is not available right now."
        await params.result_callback(answer)

    return handler


def web_search_schema(search_runner: SearchRunner) -> FunctionSchema:
    """Return the Pipecat function schema for web search."""

    return FunctionSchema(
        name=WEB_SEARCH_TOOL_NAME,
        description=(
            "Search the public internet for current, recent, factual, or external "
            "information such as news, weather, sports scores, opening hours, prices, "
            "travel information, or facts outside the assistant context. Do not use "
            "this for smart-home control; use Home Assistant tools for devices."
        ),
        properties={
            "query": {
                "type": "string",
                "description": "A clear natural-language search query in the user's language.",
            }
        },
        required=["query"],
        handler=create_web_search_handler(search_runner),
    )
