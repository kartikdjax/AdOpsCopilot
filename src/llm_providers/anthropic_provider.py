"""
Anthropic provider - conforms to the same LLMProvider interface as Groq.
Not usable without ANTHROPIC_API_KEY, but ready to swap in with zero
orchestrator changes once available (or to offer as a customer-selectable
option in Phase 6's packaging).
"""
from __future__ import annotations

import asyncio
import logging

from anthropic import AsyncAnthropic

from src.config import Settings
from src.llm_providers.base import LLMTurnResult, ToolCallRequest, ToolResultItem

logger = logging.getLogger(__name__)


class AnthropicProvider:
    def __init__(self, settings: Settings) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.llm_model
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_llm_calls)

    def convert_mcp_tools(self, mcp_tools: list[dict]) -> list[dict]:
        # Anthropic's tool schema already matches {name, description, input_schema} directly.
        return mcp_tools

    async def get_turn(self, messages: list[dict], tools: list[dict], system: str) -> LLMTurnResult:
        async with self._semaphore:
            response = await self._client.messages.create(
                model=self._model, max_tokens=1024, system=system, tools=tools, messages=messages,
            )

        if response.stop_reason != "tool_use":
            final_text = "".join(b.text for b in response.content if b.type == "text")
            return LLMTurnResult(is_final=True, text=final_text, tool_calls=[],
                                  assistant_message={"role": "assistant", "content": response.content})

        tool_calls = [
            ToolCallRequest(id=b.id, name=b.name, input=b.input)
            for b in response.content if b.type == "tool_use"
        ]
        return LLMTurnResult(is_final=False, text=None, tool_calls=tool_calls,
                              assistant_message={"role": "assistant", "content": response.content})

    def build_tool_result_messages(self, results: list[ToolResultItem]) -> list[dict]:
        # Anthropic-style: ONE user message containing ALL tool_result blocks.
        return [{
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": r.tool_call_id,
                 "content": r.content, "is_error": r.is_error}
                for r in results
            ],
        }]
