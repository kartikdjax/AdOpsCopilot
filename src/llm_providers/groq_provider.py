"""
Groq provider - free tier, OpenAI-compatible tool calling, fast (LPU
inference). Default choice for evaluation/development without an
Anthropic API key.

Hardened with a model fallback chain: Groq deprecates/rotates its free
model catalog on its own schedule (we already hit this once with
llama-3.3-70b-versatile), so a single hardcoded model WILL eventually
404 in production. 429 (rate limit) also triggers fallback, since
different models draw from separate per-model rate-limit buckets on
Groq's free tier - trying a different model is often faster than waiting
out a rate limit on the same one.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

import groq
from groq import AsyncGroq

from src.config import Settings
from src.llm_providers.base import LLMTurnResult, ToolCallRequest, ToolResultItem

logger = logging.getLogger(__name__)


class AllModelsFailedError(RuntimeError):
    """Raised when every model in the fallback chain failed. Distinct
    exception type so callers (chat_demo, orchestrator) can show a clear,
    actionable message instead of an opaque provider stack trace."""


class GroqProvider:
    def __init__(self, settings: Settings) -> None:
        self._client = AsyncGroq(api_key=settings.groq_api_key)
        self._models = [settings.groq_model] + [
            m.strip() for m in settings.groq_fallback_models.split(",") if m.strip()
        ]
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_llm_calls)

    def convert_mcp_tools(self, mcp_tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in mcp_tools
        ]

    async def _create_with_fallback(self, **kwargs):
        """Tries each model in self._models in order. Auth errors (401)
        fail immediately - the same bad key will fail on every model, so
        retrying is pointless and just delays a clear error message. 404
        (deprecated/unknown model) and 429 (rate limited) move to the
        next model in the chain."""
        last_error: Exception | None = None

        for model in self._models:
            try:
                async with self._semaphore:
                    return await self._client.chat.completions.create(model=model, **kwargs)
            except groq.AuthenticationError as exc:
                raise AllModelsFailedError(
                    f"Groq authentication failed: {exc}. Check GROQ_API_KEY in .env - "
                    f"get a free key at https://console.groq.com/keys"
                ) from exc
            except groq.NotFoundError as exc:
                logger.warning("Model %r not found (likely deprecated) - trying next fallback", model)
                last_error = exc
            except groq.RateLimitError as exc:
                logger.warning("Model %r rate-limited - trying next fallback", model)
                last_error = exc
            except groq.APIStatusError as exc:
                logger.warning("Model %r failed (%s) - trying next fallback", model, exc)
                last_error = exc

        raise AllModelsFailedError(
            f"All {len(self._models)} configured Groq models failed. Last error: {last_error}. "
            f"Check https://console.groq.com/docs/models for current model IDs and update "
            f"GROQ_MODEL / GROQ_FALLBACK_MODELS in .env."
        ) from last_error

    async def get_turn(self, messages: list[dict], tools: list[dict], system: str) -> LLMTurnResult:
        full_messages = messages
        if not messages or messages[0].get("role") != "system":
            full_messages = [{"role": "system", "content": system}, *messages]

        response = await self._create_with_fallback(
            messages=full_messages, tools=tools, tool_choice="auto", max_tokens=1024,
            parallel_tool_calls=True,
        )

        choice = response.choices[0]
        message = choice.message

        if choice.finish_reason != "tool_calls" or not message.tool_calls:
            assistant_message = {"role": "assistant", "content": message.content or ""}
            return LLMTurnResult(is_final=True, text=message.content or "",
                                  tool_calls=[], assistant_message=assistant_message)

        tool_calls = [
            ToolCallRequest(
                id=tc.id or str(uuid.uuid4()),
                name=tc.function.name,
                input=json.loads(tc.function.arguments) if tc.function.arguments else {},
            )
            for tc in message.tool_calls
        ]

        assistant_message = {
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in message.tool_calls
            ],
        }

        return LLMTurnResult(is_final=False, text=None, tool_calls=tool_calls,
                              assistant_message=assistant_message)

    def build_tool_result_messages(self, results: list[ToolResultItem]) -> list[dict]:
        return [
            {"role": "tool", "tool_call_id": r.tool_call_id, "content": r.content}
            for r in results
        ]