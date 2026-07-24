import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


def main():
    load_dotenv(ENV_FILE)

    base_url = os.getenv("RAGFLOW_BASE_URL", "").rstrip("/")
    api_key = os.getenv("RAGFLOW_API_KEY", "")
    chat_name = os.getenv("RAGFLOW_CHAT_NAME", "")
    timeout = int(os.getenv("RAGFLOW_TIMEOUT_SECONDS", "120"))

    missing = [
        name
        for name, value in {
            "RAGFLOW_BASE_URL": base_url,
            "RAGFLOW_API_KEY": api_key,
            "RAGFLOW_CHAT_NAME": chat_name,
        }.items()
        if not value
    ]

    if missing:
        print(f"连接失败：.env 缺少配置：{', '.join(missing)}")
        return 1

    url = f"{base_url}/api/v1/chats"
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"name": chat_name}

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.ConnectionError:
        print(f"连接失败：无法访问 {base_url}")
        print("请确认 RAGFlow 和 Docker Desktop 正在运行。")
        return 1
    except requests.Timeout:
        print(f"连接失败：请求超过 {timeout} 秒。")
        return 1
    except requests.HTTPError as exc:
        print(f"连接失败：HTTP {exc.response.status_code}")
        return 1
    except ValueError:
        print("连接失败：服务器没有返回有效的 JSON。")
        return 1

    if payload.get("code") != 0:
        print(f"连接失败：{payload.get('message', '未知 API 错误')}")
        return 1

    data = payload.get("data", {})
    chats = data.get("chats", []) if isinstance(data, dict) else data

    if not chats:
        print("RAGFlow API 连接成功，但没有找到指定助手。")
        print(f"助手名称：{chat_name}")
        return 1

    chat = chats[0]
    knowledge_bases = chat.get("kb_names", [])

    print("RAGFlow 连接成功")
    print(f"助手名称：{chat.get('name')}")
    print(f"助手 ID：{chat.get('id')}")
    print(
        "关联知识库："
        + ("、".join(knowledge_bases) if knowledge_bases else "未返回知识库名称")
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())