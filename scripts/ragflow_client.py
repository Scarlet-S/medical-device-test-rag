import os
from pathlib import Path

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def normalize_chunks(reference):
    if not isinstance(reference, dict):
        return []

    chunks = reference.get("chunks", [])

    if isinstance(chunks, dict):
        return list(chunks.values())

    if isinstance(chunks, list):
        return chunks

    return []


class RAGFlowClient:
    def __init__(self, chat_name=None):
        load_dotenv(PROJECT_ROOT / ".env")

        self.base_url = os.getenv("RAGFLOW_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("RAGFLOW_API_KEY", "")
        self.chat_name = (
            chat_name
            or os.getenv("RAGFLOW_CHAT_NAME", "")
        ).strip()
        # Chat and batch evaluation should fail fast without shortening
        # the longer timeout used by document ingestion operations.
        self.timeout = int(
            os.getenv("RAGFLOW_CHAT_TIMEOUT_SECONDS", "30")
        )

        missing = [
            name
            for name, value in {
                "RAGFLOW_BASE_URL": self.base_url,
                "RAGFLOW_API_KEY": self.api_key,
                "RAGFLOW_CHAT_NAME": self.chat_name,
            }.items()
            if not value
        ]

        if missing:
            raise RuntimeError(
                f".env 缺少配置：{', '.join(missing)}"
            )

        self.http = requests.Session()
        self.http.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

        self.chat = self._find_chat()
        self.chat_id = self.chat["id"]

    def _find_chat(self):
        response = self.http.get(
            f"{self.base_url}/api/v1/chats",
            params={"name": self.chat_name},
            timeout=self.timeout,
        )
        response.raise_for_status()

        payload = response.json()

        if payload.get("code") != 0:
            raise RuntimeError(
                payload.get("message", "获取助手失败")
            )

        data = payload.get("data", {})
        chats = (
            data.get("chats", [])
            if isinstance(data, dict)
            else data
        )

        if not chats:
            raise RuntimeError(
                f"没有找到助手：{self.chat_name}"
            )

        return chats[0]

    def ask(self, question):
        if not question or not question.strip():
            raise ValueError("问题不能为空")

        response = self.http.post(
            f"{self.base_url}/api/v1/chat/completions",
            json={
                "chat_id": self.chat_id,
                "question": question.strip(),
                "stream": False,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()

        payload = response.json()

        if payload.get("code") != 0:
            raise RuntimeError(
                payload.get("message", "RAGFlow问答失败")
            )

        data = payload.get("data", {})

        if not isinstance(data, dict):
            raise RuntimeError(
                "RAGFlow没有返回有效的问答数据"
            )

        return {
            "question": question.strip(),
            "answer": data.get("answer", ""),
            "references": normalize_chunks(
                data.get("reference", {})
            ),
            "session_id": data.get("session_id", ""),
            "chat_id": self.chat_id,
        }
