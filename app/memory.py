import json
import os
from datetime import datetime, timezone
from pathlib import Path

import redis.asyncio as redis
from dotenv import load_dotenv

from app.models import ConversationMessage


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RedisConversationMemory:
    def __init__(
        self,
        url: str,
        ttl_seconds: int = 86400,
        max_messages: int = 20,
        key_prefix: str = "mdtr:memory:v1",
        password: str | None = None,
    ) -> None:
        self.url = url
        self.ttl_seconds = ttl_seconds
        self.max_messages = max_messages
        self.key_prefix = key_prefix
        self.client = redis.from_url(
            url,
            decode_responses=True,
            password=password or None,
            max_connections=20,
            socket_connect_timeout=3,
            socket_timeout=3,
        )

    @classmethod
    def from_env(cls) -> "RedisConversationMemory":
        load_dotenv(PROJECT_ROOT / ".env")
        return cls(
            url=os.getenv(
                "REDIS_MEMORY_URL",
                "redis://localhost:6379/15",
            ),
            ttl_seconds=int(
                os.getenv("REDIS_MEMORY_TTL_SECONDS", "86400")
            ),
            max_messages=int(
                os.getenv("REDIS_MEMORY_MAX_MESSAGES", "20")
            ),
            password=os.getenv("REDIS_MEMORY_PASSWORD", ""),
        )

    def key(self, conversation_id: str) -> str:
        return f"{self.key_prefix}:{conversation_id}"

    async def ping(self) -> bool:
        return bool(await self.client.ping())

    async def get_history(
        self,
        conversation_id: str,
    ) -> list[ConversationMessage]:
        raw_messages = await self.client.lrange(
            self.key(conversation_id),
            0,
            -1,
        )
        messages: list[ConversationMessage] = []
        for raw in raw_messages:
            try:
                messages.append(
                    ConversationMessage.model_validate_json(raw)
                )
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
        return messages

    async def append_exchange(
        self,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        values = [
            ConversationMessage(
                role="user",
                content=user_message,
                created_at=now,
            ).model_dump_json(),
            ConversationMessage(
                role="assistant",
                content=assistant_message,
                created_at=now,
            ).model_dump_json(),
        ]
        key = self.key(conversation_id)
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.rpush(key, *values)
            pipe.ltrim(key, -self.max_messages, -1)
            pipe.expire(key, self.ttl_seconds)
            await pipe.execute()

    async def delete(self, conversation_id: str) -> bool:
        return bool(await self.client.delete(self.key(conversation_id)))

    async def close(self) -> None:
        await self.client.aclose()


def build_memory_context(
    question: str,
    history: list[ConversationMessage],
    max_history_messages: int = 6,
    max_chars_per_message: int = 1200,
) -> str:
    if not history:
        return question

    lines = [
        "以下历史对话仅用于理解上下文，不得作为法规或事实证据："
    ]
    for message in history[-max_history_messages:]:
        role = "用户" if message.role == "user" else "助手"
        content = message.content[:max_chars_per_message]
        lines.append(f"{role}：{content}")
    lines.extend(["", f"当前用户问题：{question}"])
    return "\n".join(lines)
