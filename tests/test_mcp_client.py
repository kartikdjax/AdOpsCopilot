"""
Test the MCP server directly in Python - in-memory connection, no
subprocess/Node dependency. Run: python -m tests.test_mcp_client
"""
from __future__ import annotations

import asyncio

from mcp import Client

from src.mcp_server import mcp


async def call_and_print(client: Client, tool_name: str, args: dict) -> None:
    print("=" * 70)
    print(f"Calling {tool_name}({args})")
    print("=" * 70)
    result = await client.call_tool(tool_name, args)

    # Diagnostic: check BOTH structured_content and isError, so a real
    # failure never silently prints as an unexplained None again.
    if result.is_error:
        print(f"TOOL ERROR: {result.content}")
    elif result.structured_content is not None:
        print(result.structured_content)
    else:
        print("structured_content was None - printing raw content instead:")
        print(result.content)
    print()


async def main() -> None:
    async with Client(mcp) as client:
        print(f"Connected. Server: {client.server_info}\n")

        await call_and_print(client, "list_campaigns", {})
        await call_and_print(client, "search_knowledge_base",
                              {"query": "why do we cap lookalike audiences?", "top_k": 2})
        # Once list_campaigns above shows real IDs, try:
        # await call_and_print(client, "get_kpi_summary", {"campaign_id": 1, "days": 30})
        # await call_and_print(client, "detect_campaign_anomalies", {"campaign_id": 3, "days": 60})


if __name__ == "__main__":
    asyncio.run(main())