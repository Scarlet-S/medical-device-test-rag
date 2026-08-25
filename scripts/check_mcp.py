import asyncio
import os
import sys

from mcp.client import Client


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


async def check() -> None:
    url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8080/mcp")
    async with Client(url) as client:
        result = await client.list_tools()

    names = [tool.name for tool in result.tools]
    print("MCP 连接成功")
    print(f"服务地址：{url}")
    print(f"工具数量：{len(names)}")
    print("工具列表：" + "、".join(names))


if __name__ == "__main__":
    asyncio.run(check())
