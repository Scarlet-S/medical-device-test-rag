import sys

import requests

from ragflow_client import RAGFlowClient


QUESTION = "医疗器械软件安全性级别分为哪三级？"


def main():
    try:
        client = RAGFlowClient()
        result = client.ask(QUESTION)
    except requests.ConnectionError:
        print("测试失败：无法连接RAGFlow服务。")
        return 1
    except requests.Timeout:
        print("测试失败：RAGFlow请求超时。")
        return 1
    except requests.HTTPError as exc:
        print(f"测试失败：HTTP {exc.response.status_code}")
        print(exc.response.text[:500])
        return 1
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(f"测试失败：{exc}")
        return 1

    answer = result["answer"]
    references = result["references"]

    print("=" * 60)
    print(f"问题：{result['question']}")
    print("=" * 60)
    print("回答：")
    print(answer)
    print("=" * 60)
    print(f"引用片段数量：{len(references)}")

    for index, chunk in enumerate(references[:5], start=1):
        document_name = (
            chunk.get("document_name")
            or chunk.get("doc_name")
            or "未知文档"
        )
        similarity = chunk.get("similarity")
        similarity_text = (
            f"{similarity:.4f}"
            if isinstance(similarity, (int, float))
            else "未知"
        )

        print(
            f"{index}. {document_name}"
            f"｜相似度：{similarity_text}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())