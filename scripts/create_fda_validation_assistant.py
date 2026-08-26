import argparse
import copy
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.ingest_single_document import RAGFlowIngestionClient


DEFAULT_DATASET_NAME = "FDA AI 医疗器械验证案例库"
DEFAULT_CHAT_NAME = "FDA AI 医疗器械验证案例助手"
DEFAULT_TEMPLATE_CHAT_NAME = "医疗器械控制软件测试知识助手"

SYSTEM_PROMPT = """你是FDA AI医疗器械验证案例助手。

只依据本轮检索返回的FDA 510(k)决定摘要回答，不使用外部知识补充事实。
用户可以使用中文或英文提问；回答应使用用户所用语言。

回答要求：
1. 先直接回答问题，再说明对应的510(k)编号、器械名称和证据。
2. 涉及预期用途、性能验证、算法、软件或监管分类时，只陈述检索片段明确支持的内容。
3. 不把单个器械案例概括为适用于所有医疗器械的普遍监管要求。
4. 若证据不足，明确指出缺少哪部分证据，不得猜测。
5. 保留RAGFlow来源引用，使答案可以追溯到原始决定摘要。
"""


def parse_args():
    parser = argparse.ArgumentParser(description="幂等创建FDA案例知识助手")
    parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    parser.add_argument("--chat-name", default=DEFAULT_CHAT_NAME)
    parser.add_argument("--template-chat-name", default=DEFAULT_TEMPLATE_CHAT_NAME)
    return parser.parse_args()


def list_chats(client):
    data = client.request("GET", "/api/v1/chats", params={"page_size": 100})
    return data.get("chats", []) if isinstance(data, dict) else data


def main():
    args = parse_args()
    client = RAGFlowIngestionClient()
    dataset = client.find_dataset(args.dataset_name)
    chats = list_chats(client)
    existing = [chat for chat in chats if chat.get("name") == args.chat_name]
    if existing:
        chat = existing[0]
        if chat.get("dataset_ids") != [dataset["id"]]:
            raise RuntimeError(
                "同名助手已存在，但关联知识库不一致，请先人工核对。"
            )
        print("助手已存在，无需重复创建")
        print(f"名称：{chat['name']}")
        print(f"ID：{chat['id']}")
        return 0

    templates = [
        chat for chat in chats if chat.get("name") == args.template_chat_name
    ]
    if not templates:
        raise RuntimeError(f"未找到模板助手：{args.template_chat_name}")
    template = templates[0]
    prompt_config = copy.deepcopy(template.get("prompt_config") or {})
    prompt_config.update(
        {
            "system": SYSTEM_PROMPT,
            "quote": True,
            "cross_languages": ["English"],
            "parameters": [{"key": "knowledge", "optional": False}],
        }
    )
    payload = {
        "name": args.chat_name,
        "description": "FDA AI-enabled medical device 510(k) validation case retrieval assistant",
        "dataset_ids": [dataset["id"]],
        "llm_id": template.get("llm_id"),
        "llm_setting": template.get("llm_setting") or {"model_type": ["chat"]},
        "prompt_config": prompt_config,
        "rerank_id": template.get("rerank_id"),
        "similarity_threshold": 0.2,
        "vector_similarity_weight": 0.5,
        "top_n": 8,
        "top_k": 128,
    }
    chat = client.request("POST", "/api/v1/chats", json=payload)
    print("助手创建成功")
    print(f"名称：{chat['name']}")
    print(f"ID：{chat['id']}")
    print(f"关联知识库：{args.dataset_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
