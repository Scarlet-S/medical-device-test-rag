"""Create the expanded GraphRAG ontology and frozen 40-case holdout set."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_SCHEMA = (
    PROJECT_ROOT / "evaluation" / "graphrag" / "medical_device_graph_v1.json"
)
SCHEMA_OUTPUT = (
    PROJECT_ROOT / "evaluation" / "graphrag" / "medical_device_graph_v2.json"
)
HOLDOUT_OUTPUT = (
    PROJECT_ROOT / "evaluation" / "graphrag" / "online_multihop_holdout_v3.json"
)
HOLDOUT_CHECKSUM = HOLDOUT_OUTPUT.with_suffix(".sha256")


ADDITIONAL_NODES = [
    {"id": "user_need", "label": "用户需求与预期用途", "aliases": ["用户需求", "预期用途", "intended use", "indications for use"]},
    {"id": "software_requirement", "label": "软件需求规范", "aliases": ["软件需求规范", "软件需求", "software requirements", "performance specification"]},
    {"id": "architecture_design", "label": "软件架构设计", "aliases": ["软件架构", "架构设计", "software architecture", "architecture design"]},
    {"id": "unit_test", "label": "单元测试", "aliases": ["单元测试", "unit testing", "unit test"]},
    {"id": "integration_test", "label": "集成测试", "aliases": ["集成测试", "integration testing", "integration test"]},
    {"id": "system_test", "label": "系统测试", "aliases": ["系统测试", "system testing", "system test"]},
    {"id": "user_test", "label": "用户测试", "aliases": ["用户测试", "可用性确认", "user testing", "user validation"]},
    {"id": "traceability_matrix", "label": "可追溯性矩阵", "aliases": ["可追溯性矩阵", "追溯矩阵", "traceability matrix"]},
    {"id": "review_record", "label": "评审记录", "aliases": ["评审记录", "设计评审", "review record", "design review"]},
    {"id": "configuration_item", "label": "软件配置项", "aliases": ["软件配置项", "配置项", "configuration item"]},
    {"id": "version_baseline", "label": "版本基线", "aliases": ["版本基线", "配置基线", "version baseline", "configuration baseline"]},
    {"id": "change_request", "label": "变更请求", "aliases": ["变更请求", "更新请求", "change request"]},
    {"id": "change_approval", "label": "变更批准", "aliases": ["变更批准", "更新批准", "change approval"]},
    {"id": "release_record", "label": "软件发布记录", "aliases": ["软件发布记录", "发布记录", "release record", "release documentation"]},
    {"id": "ots_inventory", "label": "现成软件清单", "aliases": ["现成软件清单", "OTS清单", "SOUP清单", "off-the-shelf software", "software bill of materials", "SBOM"]},
    {"id": "supplier_evaluation", "label": "供应商评价", "aliases": ["供应商评价", "供应商审核", "supplier evaluation", "supplier assessment"]},
    {"id": "vulnerability_monitoring", "label": "漏洞监测", "aliases": ["漏洞监测", "漏洞监控", "vulnerability monitoring", "vulnerability surveillance"]},
    {"id": "patch_evaluation", "label": "补丁影响评价", "aliases": ["补丁评价", "补丁影响", "patch evaluation", "patch assessment"]},
    {"id": "cybersecurity_requirement", "label": "网络安全需求", "aliases": ["网络安全需求", "安全需求", "cybersecurity requirements", "security requirements"]},
    {"id": "authentication", "label": "身份认证", "aliases": ["身份认证", "用户认证", "authentication", "user authentication"]},
    {"id": "authorization", "label": "授权与访问控制", "aliases": ["授权控制", "访问控制", "authorization", "access control"]},
    {"id": "encryption", "label": "数据加密", "aliases": ["数据加密", "传输加密", "encryption", "encrypted transmission"]},
    {"id": "backup_restore", "label": "备份与恢复", "aliases": ["备份与恢复", "数据恢复", "backup and restore", "data recovery"]},
    {"id": "incident_response", "label": "网络安全事件响应", "aliases": ["事件响应", "网络安全事件", "incident response", "cybersecurity incident"]},
    {"id": "use_scenario", "label": "使用场景", "aliases": ["使用场景", "使用情景", "use scenario", "use environment"]},
    {"id": "critical_task", "label": "关键任务", "aliases": ["关键任务", "关键操作", "critical task"]},
    {"id": "formative_evaluation", "label": "形成性评价", "aliases": ["形成性评价", "形成性测试", "formative evaluation"]},
    {"id": "summative_evaluation", "label": "总结性评价", "aliases": ["总结性评价", "可用性验证", "summative evaluation", "usability validation"]},
    {"id": "ai_model", "label": "AI模型与算法", "aliases": ["AI模型", "人工智能算法", "machine learning model", "artificial intelligence algorithm", "AI algorithm"]},
    {"id": "validation_dataset", "label": "独立验证数据集", "aliases": ["验证数据集", "独立测试集", "validation dataset", "independent test set"]},
    {"id": "clinical_performance", "label": "临床性能评价", "aliases": ["临床性能", "临床评价", "clinical performance", "clinical validation"]},
    {"id": "predicate_device", "label": "对比器械", "aliases": ["对比器械", "等同性比较", "predicate device", "substantial equivalence"]},
]


# source, predicate, target, document, title, auditable paraphrase
ADDITIONAL_RELATIONS = [
    ("user_need", "specified_as", "software_requirement", "DOC001", "用户需求到软件需求", "用户需求和预期用途应转化为可验证的软件需求规范。"),
    ("software_requirement", "allocated_to", "architecture_design", "DOC001", "需求分配到架构", "软件需求应分配到软件架构和软件项，并保持追溯。"),
    ("architecture_design", "implemented_by", "design_code", "DOC003", "架构到实现", "软件架构设计应细化为软件设计并落实到代码实现。"),
    ("design_code", "verified_by", "unit_test", "DOC003", "实现的单元验证", "代码实现应通过源代码审核、静态分析和单元测试进行验证。"),
    ("unit_test", "feeds", "integration_test", "DOC001", "单元到集成测试", "单元测试完成后应对组合的软件单元开展集成测试。"),
    ("integration_test", "feeds", "system_test", "DOC001", "集成到系统测试", "集成测试证据支持后续软件系统测试。"),
    ("system_test", "supports", "user_test", "DOC004", "系统到用户测试", "系统测试完成后通过真实或模拟使用环境下的用户测试确认预期用途。"),
    ("user_test", "produces", "test_evidence", "DOC004", "用户测试证据", "用户测试应形成测试记录、测试报告和评审记录。"),
    ("software_requirement", "traced_by", "traceability_matrix", "DOC003", "需求追溯矩阵", "可追溯性分析应记录软件需求与设计、测试和风险控制之间的关系。"),
    ("traceability_matrix", "links", "test_evidence", "DOC003", "追溯矩阵到证据", "追溯矩阵将软件需求映射到测试用例、执行结果和评审证据。"),
    ("architecture_design", "reviewed_in", "review_record", "DOC004", "架构评审", "软件架构与详细设计应经过评审并形成评审记录。"),
    ("review_record", "supports", "test_evidence", "DOC004", "评审支持验证证据", "评审记录是验证活动和测试充分性的组成证据。"),
    ("configuration_item", "controlled_by", "version_baseline", "DOC003", "配置项与基线", "软件配置项应纳入版本基线并记录配置状态。"),
    ("version_baseline", "released_as", "release_record", "DOC003", "基线到发布记录", "批准的软件版本基线应与发布记录和交付版本保持一致。"),
    ("release_record", "evidences", "test_evidence", "DOC003", "发布证据", "软件发布记录应引用已完成的验证确认结果和批准证据。"),
    ("change_request", "requires", "impact_analysis", "DOC004", "变更请求影响分析", "软件变更请求应先开展影响分析和风险评价。"),
    ("impact_analysis", "supports", "change_approval", "DOC004", "影响分析支持批准", "变更批准应基于影响分析、风险评价和验证确认计划。"),
    ("change_approval", "authorizes", "software_update", "DOC004", "批准的软件更新", "经批准的变更进入软件更新实施并形成记录。"),
    ("supplier_evaluation", "controls", "ots_inventory", "DOC003", "供应商与现成软件", "现成软件供应商应接受评价，采购的软件组件应纳入清单。"),
    ("ots_inventory", "monitored_by", "vulnerability_monitoring", "DOC002", "现成软件漏洞监测", "现成软件清单支持持续监测已知漏洞、补丁和停止维护状态。"),
    ("vulnerability_monitoring", "triggers", "patch_evaluation", "DOC002", "漏洞触发补丁评价", "新漏洞或补丁信息应触发安全影响与补丁适用性评价。"),
    ("patch_evaluation", "feeds", "impact_analysis", "DOC002", "补丁影响分析", "补丁评价结果用于确定受影响功能、风险控制和回归测试范围。"),
    ("cybersecurity_requirement", "implemented_by", "authentication", "DOC002", "认证安全需求", "身份认证机制用于实现网络安全访问需求。"),
    ("cybersecurity_requirement", "implemented_by", "authorization", "DOC002", "授权安全需求", "授权和访问控制机制用于实现最小权限要求。"),
    ("cybersecurity_requirement", "implemented_by", "encryption", "DOC002", "加密安全需求", "加密机制用于保护医疗数据存储和传输。"),
    ("cybersecurity_requirement", "implemented_by", "backup_restore", "DOC002", "恢复安全需求", "备份恢复机制用于支持数据可得性和业务连续性。"),
    ("authentication", "verified_by", "security_test", "DOC002", "认证安全测试", "认证失败、锁定和恢复机制需要通过网络安全测试验证。"),
    ("authorization", "verified_by", "security_test", "DOC002", "授权安全测试", "访问控制需要通过允许、拒绝和越权场景测试验证。"),
    ("encryption", "verified_by", "security_test", "DOC002", "加密安全测试", "数据加密和密钥管理需要通过适宜的安全测试验证。"),
    ("backup_restore", "verified_by", "security_test", "DOC002", "备份恢复测试", "备份完整性和恢复能力需要通过测试形成证据。"),
    ("security_test", "triggers", "incident_response", "DOC002", "安全测试与事件响应", "安全测试发现的重大问题应进入漏洞处置和事件响应流程。"),
    ("incident_response", "updates", "risk_analysis", "DOC002", "事件响应更新风险", "网络安全事件调查结果应反馈更新风险分析和控制措施。"),
    ("use_scenario", "identifies", "critical_task", "DOC006", "场景识别关键任务", "使用场景分析应识别与安全有关的关键用户任务。"),
    ("critical_task", "assessed_by", "formative_evaluation", "DOC006", "关键任务形成性评价", "形成性评价用于发现关键任务中的使用困难并改进设计。"),
    ("formative_evaluation", "feeds", "summative_evaluation", "DOC006", "形成性到总结性评价", "形成性评价改进完成后开展总结性评价验证使用安全性。"),
    ("summative_evaluation", "supports", "user_test", "DOC006", "总结性评价与用户测试", "总结性评价结果支持用户测试和预期用途确认。"),
    ("ai_model", "evaluated_on", "validation_dataset", "FDAAI", "AI模型独立验证", "AI模型应在与开发数据独立的验证数据集上评价性能。"),
    ("validation_dataset", "measures", "clinical_performance", "FDAAI", "验证数据与临床性能", "验证数据用于计算灵敏度、特异度或其他临床性能指标。"),
    ("clinical_performance", "supports", "test_evidence", "FDAAI", "临床性能测试证据", "临床性能评价结果构成AI医疗器械性能测试和验证证据。"),
    ("user_need", "compared_with", "predicate_device", "FDAAI", "预期用途与对比器械", "510(k)等同性比较应核对拟申报器械与对比器械的预期用途。"),
    ("predicate_device", "compared_by", "clinical_performance", "FDAAI", "对比器械性能比较", "与对比器械的性能比较用于支持实质等同性结论。"),
    ("ai_model", "implements", "software_requirement", "FDAAI", "AI算法实现需求", "AI算法实现产品预期用途相关的软件性能需求。"),
]


HOLDOUT_CASES = [
    ("GV301", "从用户需求到最终用户测试证据，需要经过哪些软件工程环节？", ["user_need", "software_requirement", "architecture_design", "design_code", "unit_test", "integration_test", "system_test", "user_test", "test_evidence"]),
    ("GV302", "软件需求如何经架构和代码逐级落实为单元测试证据？", ["software_requirement", "architecture_design", "design_code", "unit_test"]),
    ("GV303", "单元测试完成后，证据怎样继续流向用户测试？", ["unit_test", "integration_test", "system_test", "user_test"]),
    ("GV304", "软件需求怎样通过可追溯性矩阵连接到验证证据？", ["software_requirement", "traceability_matrix", "test_evidence"]),
    ("GV305", "架构评审记录如何支持最终测试证据？", ["architecture_design", "review_record", "test_evidence"]),
    ("GV306", "软件配置项如何形成可发布且可核查的证据链？", ["configuration_item", "version_baseline", "release_record", "test_evidence"]),
    ("GV307", "变更请求如何经过分析批准并最终决定回归测试范围？", ["change_request", "impact_analysis", "change_approval", "software_update", "regression_scope"]),
    ("GV308", "补丁信息出现后，怎样经过评价和影响分析形成回归范围？", ["vulnerability_monitoring", "patch_evaluation", "impact_analysis", "regression_scope"]),
    ("GV309", "供应商评价怎样沿现成软件清单追踪到补丁处置？", ["supplier_evaluation", "ots_inventory", "vulnerability_monitoring", "patch_evaluation"]),
    ("GV310", "网络安全需求中的认证机制如何形成安全测试证据？", ["cybersecurity_requirement", "authentication", "security_test"]),
    ("GV311", "网络安全需求如何通过授权控制落实到安全测试？", ["cybersecurity_requirement", "authorization", "security_test"]),
    ("GV312", "网络安全需求中的加密措施怎样验证并发现剩余漏洞？", ["cybersecurity_requirement", "encryption", "security_test", "residual_vulnerability"]),
    ("GV313", "备份恢复要求如何通过安全测试进入事件响应？", ["backup_restore", "security_test", "incident_response"]),
    ("GV314", "安全测试发现重大问题后，事件响应如何反馈风险分析？", ["security_test", "incident_response", "risk_analysis"]),
    ("GV315", "使用场景怎样经过关键任务评价最终连接到用户测试？", ["use_scenario", "critical_task", "formative_evaluation", "summative_evaluation", "user_test"]),
    ("GV316", "关键任务如何经过形成性和总结性评价形成测试证据？", ["critical_task", "formative_evaluation", "summative_evaluation", "user_test", "test_evidence"]),
    ("GV317", "AI模型如何通过独立验证数据集形成临床性能测试证据？", ["ai_model", "validation_dataset", "clinical_performance", "test_evidence"]),
    ("GV318", "AI算法如何由软件需求连接到独立验证数据？", ["software_requirement", "ai_model", "validation_dataset"]),
    ("GV319", "预期用途如何通过对比器械比较连接到临床性能？", ["user_need", "predicate_device", "clinical_performance"]),
    ("GV320", "对比器械的等同性比较如何最终形成验证证据？", ["predicate_device", "clinical_performance", "test_evidence"]),
    ("GV321", "软件危险如何沿风险控制、需求、实现追溯到测试证据？", ["hazard", "risk_control", "safety_requirement", "design_code", "test_evidence"]),
    ("GV322", "版本更新回归失败后，怎样形成缺陷记录并重新确定范围？", ["software_update", "regression_scope", "regression_result", "defect_record", "risk_analysis"]),
    ("GV323", "威胁建模结果怎样经安全控制和测试进入事件响应？", ["threat_model", "security_control", "security_test", "incident_response"]),
    ("GV324", "现成软件变化如何经影响分析转化为回归测试结果？", ["ots_change", "impact_analysis", "regression_scope", "regression_result"]),
    ("GV325", "权限设计如何通过审计日志连接到网络安全测试？", ["access_role", "audit_log", "security_test"]),
    ("GV326", "缺陷记录引起的风险变化如何决定新的回归范围？", ["defect_record", "risk_analysis", "regression_scope"]),
    ("GV327", "软件安全性级别如何影响验证证据，并进一步支持发布记录？", ["safety_level", "test_evidence", "release_record"]),
    ("GV328", "访问控制怎样经安全测试识别需要继续处置的漏洞？", ["authorization", "security_test", "residual_vulnerability"]),
    ("GV329", "软件更新怎样经回归执行、失败记录和风险分析形成闭环？", ["software_update", "regression_scope", "regression_result", "defect_record", "risk_analysis"]),
    ("GV330", "用户需求如何通过软件需求和追溯矩阵形成验证证据？", ["user_need", "software_requirement", "traceability_matrix", "test_evidence"]),
    ("GV331", "软件架构如何经过评审并最终支撑验证测试？", ["architecture_design", "review_record", "test_evidence"]),
    ("GV332", "配置基线批准后怎样连接发布记录和验证证据？", ["version_baseline", "release_record", "test_evidence"]),
    ("GV333", "现成软件清单中的漏洞如何经补丁评价影响测试范围？", ["ots_inventory", "vulnerability_monitoring", "patch_evaluation", "impact_analysis", "regression_scope"]),
    ("GV334", "身份认证测试发现漏洞后怎样进入事件响应和风险分析？", ["authentication", "security_test", "incident_response", "risk_analysis"]),
    ("GV335", "使用环境中的关键任务如何经过两阶段可用性评价？", ["use_scenario", "critical_task", "formative_evaluation", "summative_evaluation"]),
    ("GV336", "临床性能结果怎样与测试证据和发布记录形成核查链？", ["clinical_performance", "test_evidence", "release_record"]),
    ("GV337", "AI算法实现的软件需求如何通过临床性能得到验证？", ["software_requirement", "ai_model", "validation_dataset", "clinical_performance"]),
    ("GV338", "风险控制措施如何通过安全需求落实为授权测试证据？", ["risk_control", "safety_requirement", "design_code", "test_evidence"]),
    ("GV339", "审计日志发现越权行为后怎样沿安全测试进入剩余漏洞处置？", ["audit_log", "security_test", "residual_vulnerability"]),
    ("GV340", "变更影响分析怎样连接批准、软件更新和缺陷闭环？", ["impact_analysis", "change_approval", "software_update", "regression_scope", "regression_result", "defect_record"]),
]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )
    )


def main() -> int:
    base = json.loads(BASE_SCHEMA.read_text(encoding="utf-8-sig"))
    nodes = [*base["nodes"], *ADDITIONAL_NODES]
    chunks = list(base["chunks"])
    relations = list(base["relations"])
    next_chunk = len(chunks) + 1
    for source, predicate, target, document, title, text in ADDITIONAL_RELATIONS:
        chunk_id = f"C{next_chunk:03d}"
        next_chunk += 1
        chunks.append(
            {
                "id": chunk_id,
                "document_code": document,
                "title": title,
                "entities": [source, target],
                "text": text,
            }
        )
        relations.append(
            {
                "source": source,
                "predicate": predicate,
                "target": target,
                "evidence_chunk": chunk_id,
            }
        )

    schema = {
        "schema_version": 2,
        "name": "medical-device-software-graphrag-schema-v2",
        "description": (
            "覆盖医疗器械软件生命周期、风险、网络安全、可用性和AI验证的"
            "可审计领域图模式；示例片段为结构化改写，不替代法规原文。"
        ),
        "nodes": nodes,
        "chunks": chunks,
        "relations": relations,
    }
    assert len({item["id"] for item in nodes}) == len(nodes)
    assert len({item["id"] for item in chunks}) == len(chunks)
    write_json(SCHEMA_OUTPUT, schema)

    holdout = {
        "schema_version": 2,
        "name": "online-graphrag-frozen-holdout-v3",
        "version": "3.0.0",
        "frozen_at": "2026-08-27",
        "frozen_before_first_run": True,
        "description": (
            "40道未用于图谱调优的多跳问题，覆盖生命周期、变更、风险、"
            "网络安全、可用性与AI验证证据链。首次运行后不得修改。"
        ),
        "cases": [
            {
                "case_id": case_id,
                "type": "multi_hop",
                "question": question,
                "expected_nodes": nodes,
            }
            for case_id, question, nodes in HOLDOUT_CASES
        ],
    }
    assert len(holdout["cases"]) == 40
    assert len({item["question"] for item in holdout["cases"]}) == 40
    write_json(HOLDOUT_OUTPUT, holdout)
    digest = hashlib.sha256(HOLDOUT_OUTPUT.read_bytes()).hexdigest()
    HOLDOUT_CHECKSUM.write_bytes(
        f"{digest}  {HOLDOUT_OUTPUT.name}\n".encode("utf-8")
    )
    print(f"实体类型：{len(schema['nodes'])}")
    print(f"受控关系：{len(schema['relations'])}")
    print(f"冻结多跳题：{len(holdout['cases'])}")
    print(f"SHA-256：{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
