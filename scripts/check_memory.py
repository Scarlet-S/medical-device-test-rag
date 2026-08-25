import asyncio
import sys
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.memory import RedisConversationMemory


async def main() -> None:
    memory = RedisConversationMemory.from_env()
    conversation_id = f"smoke-{uuid4().hex}"
    try:
        connected = await memory.ping()
        await memory.append_exchange(
            conversation_id,
            "这是一条Redis记忆连通性测试问题。",
            "这是一条临时测试回答。",
        )
        history = await memory.get_history(conversation_id)
        deleted = await memory.delete(conversation_id)

        print("Redis 记忆连接成功" if connected else "Redis 连接异常")
        print(f"临时会话：{conversation_id}")
        print(f"写入并读取消息数：{len(history)}")
        print(f"临时会话已清理：{deleted}")

        if not connected or len(history) != 2 or not deleted:
            raise RuntimeError("Redis记忆读写验收未通过")
    finally:
        await memory.close()


if __name__ == "__main__":
    asyncio.run(main())
