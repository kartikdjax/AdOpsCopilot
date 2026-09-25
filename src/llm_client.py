"""Anthropic API client, concurrency-capped per Week 1 Day 2's semaphore pattern."""
from __future__ import annotations

import asyncio
import logging

from anthropic import AsyncAnthropic

from src.config import Settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.raw_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.llm_model
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_llm_calls)

    async def create_message(self, **kwargs):
        async with self._semaphore:
            return await self.raw_client.messages.create(model=self.model, **kwargs)
