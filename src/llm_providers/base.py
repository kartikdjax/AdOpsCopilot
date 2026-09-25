"""
Provider-agnostic LLM interface for the tool-use loop.

Different providers structure tool-calling wire formats quite differently:
  - Anthropic: assistant content is a list of blocks (text + tool_use);
    tool results go back as ONE user message containing tool_result blocks.
  - OpenAI-compatible (Groq, OpenAI, etc.): assistant message has a
    `tool_calls` list; each tool result goes back as its OWN separate
    message with role="tool".

Rather than let the orchestrator assume one shape, every provider
implements the same small interface and hands back normalized
LLMTurnResult objects. Swapping providers (or supporting several,
letting a customer choose) means adding one new provider file, not
touching orchestrator.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    id: str
    name: str
    input: dict


@dataclass(frozen=True, slots=True)
class ToolResultItem:
    tool_call_id: str
    name: str
    content: str
    is_error: bool


@dataclass(frozen=True, slots=True)
class LLMTurnResult:
    is_final: bool
    text: str | None
    tool_calls: list[ToolCallRequest]
    assistant_message: dict  # ready to append to `messages` as-is for this provider


class LLMProvider(Protocol):
    def convert_mcp_tools(self, mcp_tools: list[dict]) -> list[dict]:
        """Converts generic {name, description, input_schema} tool defs
        into this provider's tool-schema format."""
        ...

    async def get_turn(self, messages: list[dict], tools: list[dict], system: str) -> LLMTurnResult:
        """Sends the conversation so far and returns either a final answer
        or a list of tool calls to execute."""
        ...

    def build_tool_result_messages(self, results: list[ToolResultItem]) -> list[dict]:
        """Formats executed tool results into whatever message(s) this
        provider expects appended to history next."""
        ...
