"""Small, auditable GraphRAG retrieval layer for the online pilot.

The graph is deliberately optional.  It can load the frozen pilot graph or an
index built from real RAGFlow chunks by ``scripts/build_graphrag_index.py``.
No external graph database is required for this small-scale experiment.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX_PATH = (
    PROJECT_ROOT / "evaluation" / "graphrag" / "medical_device_graph_v1.json"
)


def text_terms(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    result = set(re.findall(r"[a-z0-9][a-z0-9_.-]+", normalized))
    for block in re.findall(r"[\u4e00-\u9fff]+", normalized):
        result.add(block)
        for size in (2, 3, 4):
            result.update(
                block[index : index + size]
                for index in range(len(block) - size + 1)
            )
    return {item for item in result if item}


@dataclass(frozen=True)
class GraphSearchResult:
    detected_entities: list[str]
    paths: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    confidence: float


class GraphRAGIndex:
    """In-memory entity graph with lexical ranking and evidence paths."""

    def __init__(self, dataset: dict[str, Any], source_path: Path | None = None):
        self.dataset = dataset
        self.source_path = source_path
        self.nodes = {
            str(item["id"]): item for item in dataset.get("nodes", [])
        }
        self.chunks = {
            str(item["id"]): item for item in dataset.get("chunks", [])
        }
        self.adjacency: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for relation in dataset.get("relations", []):
            source = str(relation["source"])
            target = str(relation["target"])
            predicate = str(relation.get("predicate") or "related_to")
            evidence = str(relation.get("evidence_chunk") or "")
            self.adjacency[source].append((target, predicate, evidence))
            self.adjacency[target].append((source, predicate, evidence))

        self._chunk_terms = {
            chunk_id: text_terms(
                f"{chunk.get('title', '')} {chunk.get('text', '')}"
            )
            for chunk_id, chunk in self.chunks.items()
        }
        self._term_frequency = Counter(
            term for terms in self._chunk_terms.values() for term in terms
        )

    @classmethod
    def from_path(cls, path: Path | str | None = None) -> "GraphRAGIndex":
        configured = path or os.getenv("GRAPHRAG_INDEX_PATH", "").strip()
        resolved = Path(configured) if configured else DEFAULT_INDEX_PATH
        if not resolved.is_absolute():
            resolved = PROJECT_ROOT / resolved
        with resolved.open("r", encoding="utf-8-sig") as handle:
            dataset = json.load(handle)
        return cls(dataset, source_path=resolved.resolve())

    def detect_entities(self, question: str) -> list[str]:
        normalized = re.sub(r"\s+", "", question.lower())
        matches: list[tuple[int, int, str]] = []
        for node_id, node in self.nodes.items():
            aliases = [str(node.get("label") or ""), *node.get("aliases", [])]
            occurrences = []
            for alias in aliases:
                normalized_alias = re.sub(r"\s+", "", alias.lower())
                if not normalized_alias:
                    continue
                position = normalized.find(normalized_alias)
                if position >= 0:
                    occurrences.append((position, -len(normalized_alias)))
            if occurrences:
                position, negative_length = min(occurrences)
                matches.append((position, negative_length, node_id))
        return [node_id for _, _, node_id in sorted(matches)]

    def _shortest_path(
        self,
        source: str,
        target: str,
        max_hops: int,
        semantic_only: bool = False,
    ) -> tuple[list[str], list[str], list[str]]:
        if source == target:
            return [source], [], []
        queue = deque([(source, [source], [], [])])
        visited = {source}
        while queue:
            node, node_path, predicates, chunk_path = queue.popleft()
            if len(chunk_path) >= max_hops:
                continue
            for neighbor, predicate, chunk_id in self.adjacency.get(node, []):
                if semantic_only and predicate == "co_occurs_in_evidence":
                    continue
                if neighbor in visited:
                    continue
                next_nodes = [*node_path, neighbor]
                next_predicates = [*predicates, predicate]
                next_chunks = [*chunk_path, chunk_id]
                if neighbor == target:
                    return next_nodes, next_predicates, next_chunks
                visited.add(neighbor)
                queue.append(
                    (neighbor, next_nodes, next_predicates, next_chunks)
                )
        return [], [], []

    def _lexical_scores(self, question: str) -> dict[str, float]:
        query_terms = text_terms(question)
        total = max(len(self.chunks), 1)
        scores: dict[str, float] = {}
        for chunk_id, chunk_terms in self._chunk_terms.items():
            overlap = query_terms & chunk_terms
            weighted = sum(
                math.log((total + 1) / (self._term_frequency[term] + 0.5)) + 1
                for term in overlap
            )
            denominator = math.sqrt(
                max(len(query_terms), 1) * max(len(chunk_terms), 1)
            )
            scores[chunk_id] = weighted / denominator
        return scores

    def lexical_evidence(
        self,
        question: str,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        """Return the non-graph baseline used by the pilot comparison."""
        scores = self._lexical_scores(question)
        ranked = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
        return [
            {
                "chunk_id": chunk_id,
                "document_code": str(
                    self.chunks[chunk_id].get("document_code") or ""
                ),
                "title": str(self.chunks[chunk_id].get("title") or ""),
                "content": str(self.chunks[chunk_id].get("text") or ""),
                "score": round(scores[chunk_id], 6),
                "entities": [
                    str(item)
                    for item in self.chunks[chunk_id].get("entities", [])
                ],
            }
            for chunk_id in ranked[:top_k]
        ]

    def search(
        self,
        question: str,
        top_k: int = 4,
        max_hops: int = 4,
    ) -> GraphSearchResult:
        entities = self.detect_entities(question)
        lexical_scores = self._lexical_scores(question)
        path_records: list[dict[str, Any]] = []
        path_chunk_ids: list[str] = []

        # Evaluate semantic paths before using broad co-occurrence edges. A
        # good path covers the concepts explicitly named in the question and
        # retains useful intermediate steps.
        endpoint_pairs = [
            (source, target)
            for left_index, source in enumerate(entities)
            for target in entities[left_index + 1 :]
        ]
        for source, target in endpoint_pairs:
            nodes, predicates, chunks = self._shortest_path(
                source, target, max_hops, semantic_only=True
            )
            if chunks:
                path_records.append(
                    {
                        "nodes": nodes,
                        "node_labels": [
                            str(self.nodes.get(node, {}).get("label") or node)
                            for node in nodes
                        ],
                        "predicates": predicates,
                        "evidence_chunks": chunks,
                        "hop_count": len(chunks),
                    }
                )

        detected_set = set(entities)
        path_records.sort(
            key=lambda item: (
                -len(detected_set.intersection(item["nodes"])),
                -item["hop_count"],
                item["evidence_chunks"],
            )
        )
        if not path_records and len(entities) >= 2:
            nodes, predicates, chunks = self._shortest_path(
                entities[0], entities[-1], max_hops
            )
            if chunks:
                path_records.append(
                    {
                        "nodes": nodes,
                        "node_labels": [
                            str(self.nodes.get(node, {}).get("label") or node)
                            for node in nodes
                        ],
                        "predicates": predicates,
                        "evidence_chunks": chunks,
                        "hop_count": len(chunks),
                    }
                )
        # One strongest explanatory path is easier to audit than every pair.
        selected_paths = path_records[:1]
        for path in selected_paths:
            path_chunk_ids.extend(path["evidence_chunks"])

        ranked = []
        for chunk_id, chunk in self.chunks.items():
            score = lexical_scores.get(chunk_id, 0.0)
            if chunk_id in path_chunk_ids:
                score += 2.0 + (len(path_chunk_ids) - path_chunk_ids.index(chunk_id)) * 0.01
            ranked.append((score, chunk_id, chunk))
        ranked.sort(key=lambda item: (-item[0], item[1]))

        score_by_id = {chunk_id: score for score, chunk_id, _ in ranked}
        ordered_ids = list(dict.fromkeys(path_chunk_ids))
        ordered_ids.extend(
            chunk_id for _, chunk_id, _ in ranked if chunk_id not in ordered_ids
        )
        evidence = []
        for chunk_id in ordered_ids[:top_k]:
            chunk = self.chunks[chunk_id]
            evidence.append(
                {
                    "chunk_id": chunk_id,
                    "document_code": str(chunk.get("document_code") or ""),
                    "document_name": str(chunk.get("document_name") or ""),
                    "title": str(chunk.get("title") or ""),
                    "content": str(chunk.get("text") or ""),
                    "score": round(score_by_id.get(chunk_id, 0.0), 6),
                    "entities": [str(item) for item in chunk.get("entities", [])],
                    "source": "graph",
                }
            )

        if selected_paths:
            confidence = min(1.0, 0.65 + selected_paths[0]["hop_count"] * 0.08)
        elif entities and evidence and evidence[0]["score"] > 0:
            confidence = 0.45
        else:
            confidence = 0.0
        return GraphSearchResult(
            detected_entities=entities,
            paths=selected_paths,
            evidence=evidence,
            confidence=round(confidence, 3),
        )


def build_graph_dataset_from_chunks(
    chunks: list[dict[str, Any]],
    schema: dict[str, Any],
    name: str,
    max_evidence_per_pair: int = 0,
) -> dict[str, Any]:
    """Create an evidence graph from real RAGFlow chunk records.

    Entity extraction is deterministic alias matching. Relations are explicit
    co-occurrences within one chunk, so every edge remains traceable to source
    evidence and no LLM-generated fact is silently introduced.
    """

    nodes = schema.get("nodes", [])
    detector = GraphRAGIndex({"nodes": nodes, "chunks": [], "relations": []})
    normalized_chunks = []
    relations: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for index, raw in enumerate(chunks, start=1):
        content = str(
            raw.get("content")
            or raw.get("content_with_weight")
            or raw.get("text")
            or ""
        )
        title = str(raw.get("title") or raw.get("document_name") or "")
        chunk_id = str(raw.get("id") or raw.get("chunk_id") or f"RF{index:06d}")
        entities = detector.detect_entities(f"{title} {content}")
        normalized_chunks.append(
            {
                "id": chunk_id,
                "document_code": str(raw.get("document_code") or ""),
                "document_name": str(raw.get("document_name") or ""),
                "title": title,
                "entities": entities,
                "text": content,
            }
        )
        for left_index, source in enumerate(entities):
            for target in entities[left_index + 1 :]:
                pair = tuple(sorted((source, target)))
                key = (pair[0], "co_occurs_in_evidence", pair[1], chunk_id)
                relations[key] = {
                    "source": pair[0],
                    "predicate": "co_occurs_in_evidence",
                    "target": pair[1],
                    "evidence_chunk": chunk_id,
                }
    # Overlay the curated domain relation schema, but only when a real source
    # chunk directly mentions both endpoints. This retains the explainable
    # multi-hop semantics while replacing pilot evidence IDs with real
    # RAGFlow chunk IDs.
    schema_chunks = {
        str(item.get("id") or ""): item for item in schema.get("chunks", [])
    }
    for relation in schema.get("relations", []):
        source = str(relation.get("source") or "")
        target = str(relation.get("target") or "")
        predicate = str(relation.get("predicate") or "related_to")
        pilot_evidence = schema_chunks.get(
            str(relation.get("evidence_chunk") or ""), {}
        )
        expected_document = str(pilot_evidence.get("document_code") or "")
        expected_terms = text_terms(
            f"{pilot_evidence.get('title', '')} {pilot_evidence.get('text', '')}"
        )

        def mapping_score(chunk: dict[str, Any]) -> float:
            score = 0.0
            if expected_document and chunk["document_code"] == expected_document:
                score += 3.0
            score += 2.0 * int(source in chunk["entities"])
            score += 2.0 * int(target in chunk["entities"])
            chunk_terms = text_terms(f"{chunk['title']} {chunk['text']}")
            if expected_terms:
                score += len(expected_terms.intersection(chunk_terms)) / len(
                    expected_terms
                )
            return score

        scored = [
            (mapping_score(chunk), -len(chunk["text"]), chunk)
            for chunk in normalized_chunks
        ]
        scored = [item for item in scored if item[0] >= 3.0]
        if not scored:
            continue
        best_score, _, evidence = max(
            scored,
            key=lambda item: (item[0], item[1], item[2]["id"]),
        )
        key = (source, predicate, target, evidence["id"])
        relations[key] = {
            "source": source,
            "predicate": predicate,
            "target": target,
            "evidence_chunk": evidence["id"],
            "mapping": "curated_relation_to_real_chunk",
            "mapping_score": round(best_score, 4),
        }
    relation_values = list(relations.values())
    if max_evidence_per_pair > 0:
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        curated = []
        for relation in relation_values:
            if relation.get("predicate") == "co_occurs_in_evidence":
                key = (
                    str(relation["source"]),
                    str(relation["predicate"]),
                    str(relation["target"]),
                )
                grouped[key].append(relation)
            else:
                curated.append(relation)
        relation_values = list(curated)
        for key in sorted(grouped):
            evidence = sorted(
                grouped[key], key=lambda item: str(item["evidence_chunk"])
            )
            relation_values.extend(evidence[:max_evidence_per_pair])

    return {
        "schema_version": 1,
        "name": name,
        "description": (
            "由RAGFlow真实切片通过确定性实体别名匹配构建；"
            "关系表示同一证据切片中的共现，不替代法规原文。"
        ),
        "nodes": nodes,
        "chunks": normalized_chunks,
        "relations": relation_values,
        "cases": [],
    }
