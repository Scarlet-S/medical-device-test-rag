import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def get_chat(base_url, api_key, chat_name, timeout):
    response = requests.get(
        f"{base_url}/api/v1/chats",
        headers={"Authorization": f"Bearer {api_key}"},
        params={"name": chat_name},
        timeout=timeout,
    )
    response.raise_for_status()

    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(payload.get("message", "获取助手失败"))

    data = payload.get("data", {})
    chats = data.get("chats", []) if isinstance(data, dict) else data

    if not chats:
        raise RuntimeError(f"没有找到助手：{chat_name}")

    return chats[0]


def normalize_chunks(reference):
    if not isinstance(reference, dict):
        return []

    chunks = reference.get("chunks", [])

    if isinstance(chunks, dict):
        return list(chunks.values())

    if isinstance(chunks, list):
        return chunks

    return []


def main():
    base_url = os.getenv("RAGFLOW_BASE_URL", "").rstrip("/")
    api_key = os.getenv("RAGFLOW_API_KEY", "")
    chat_name = os.getenv("RAGFLOW_CHAT_NAME", "")
    timeout = int(os.getenv("RAGFLOW_TIMEOUT_SECONDS", "120"))

    question = "医疗器械软件安全性级别分为哪三级？"

    if not base_url or not api_key or not chat_name:
        print("测试失败：请检查 .env 配置。")
        return 1

    try:
        chat = get_chat(base_url, api_key, chat_name, timeout)

        response = requests.post(
            f"{base_url}/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "chat_id": chat["id"],
                "question": question,
                "stream": False,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()

        if payload.get("code") != 0:
            raise RuntimeError(
                payload.get("message", "RAGFlow 问答接口返回错误")
            )

        data = payload.get("data", {})

        if not isinstance(data, dict):
            raise RuntimeError("RAGFlow 没有返回有效的问答数据")

        answer = data.get("answer", "")
        chunks = normalize_chunks(data.get("reference", {}))

    except requests.ConnectionError:
        print(f"测试失败：无法连接 {base_url}")
        return 1
    except requests.Timeout:
        print(f"测试失败：请求超过 {timeout} 秒。")
        return 1
    except requests.HTTPError as exc:
        print(f"测试失败：HTTP {exc.response.status_code}")
        print(exc.response.text[:500])
        return 1
    except (KeyError, IndexError, TypeError, ValueError, RuntimeError) as exc:
        print(f"测试失败：{exc}")
        return 1

    print("=" * 60)
    print(f"问题：{question}")
    print("=" * 60)
    print("回答：")
    print(answer)
    print("=" * 60)
    print(f"引用片段数量：{len(chunks)}")

    for index, chunk in enumerate(chunks[:5], start=1):
        document_name = chunk.get("document_name", "未知文档")
        similarity = chunk.get("similarity")
        similarity_text = (
            f"{similarity:.4f}"
            if isinstance(similarity, (int, float))
            else "未知"
        )

        print(f"{index}. {document_name}｜相似度：{similarity_text}")

    return 0


if __name__ == "__main__":
    sys.exit(main())