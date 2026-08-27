"""Create the balanced 90-case Agent evaluation dataset used by v1.7.

The cases are kept in code so reviewers can audit the coverage matrix and
recreate the checked-in JSON byte-for-byte before the first frozen run.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "evaluation" / "agent" / "agent_evaluation_v2.json"
CHECKSUM = OUTPUT.with_suffix(".sha256")


REGULATORY_QUESTIONS = [
    ("NMPA对医疗器械软件安全性级别的划分和判定依据有哪些规定？", False, ["regulation", "classification"]),
    ("独立软件现场检查中，黑盒测试人员独立性对应哪些条款要求？", False, ["regulation", "inspection"]),
    ("医疗器械软件缺陷管理规范要求形成哪些文件、记录和评审证据？", False, ["regulation", "defect_management"]),
    ("YY/T 0664对医疗器械软件生存周期过程提出了哪些核心要求？", False, ["standard", "lifecycle"]),
    ("GB/T 42062规定风险控制措施实施后还应完成哪些活动？", False, ["standard", "risk_management"]),
    ("注册质量管理体系现场核查可能形成哪四种结论？", False, ["regulation", "qms_inspection"]),
    ("医疗器械召回法规对调查评估报告和召回计划有什么要求？", False, ["regulation", "recall"]),
    ("法规如何要求控制医疗器械软件设计开发变更？", False, ["regulation", "change_control"]),
    ("指导原则对现成软件的识别、风险评价和更新控制有哪些要求？", False, ["guidance", "ots"]),
    ("医疗器械网络安全注册资料通常需要说明哪些内容？", False, ["regulation", "cybersecurity"]),
    ("NMPA对软件需求规范的形成、评审和批准有什么要求？", False, ["regulation", "requirements"]),
    ("标准对软件配置项、版本基线和配置状态记录有哪些规定？", False, ["standard", "configuration"]),
    ("现场检查如何核查软件发布记录与批准活动？", False, ["inspection", "release"]),
    ("法规对医疗器械软件供应商评价和外包质量协议有哪些要求？", False, ["regulation", "supplier"]),
    ("指导原则如何区分重大软件更新和轻微软件更新？", False, ["guidance", "software_update"]),
    ("NMPA对用户测试的环境、记录和可追溯性有什么要求？", False, ["regulation", "user_test"]),
    ("标准对风险管理计划、风险可接受准则和剩余风险评价有什么规定？", False, ["standard", "risk_management"]),
    ("注册检验产品真实性核查应重点核对哪些信息？", False, ["regulation", "registration_test"]),
    ("医疗器械软件停运时需要考虑哪些法规和质量体系要求？", False, ["regulation", "retirement"]),
    ("FDA软件验证通用原则如何解释验证、确认和风险之间的关系？", False, ["fda", "validation"]),
    ("软件更新后怎样确定验证确认的工作范围？", True, ["low_confidence", "software_update"]),
    ("可追溯性分析分别需要建立哪些关系？", True, ["low_confidence", "traceability"]),
    ("软件发布前通常需要准备什么？", True, ["low_confidence", "release"]),
    ("变更完成以后还要留下哪些证据？", True, ["low_confidence", "change_control"]),
    ("出现剩余风险时下一步如何处理？", True, ["low_confidence", "risk_management"]),
    ("第三方组件发生变化后企业要做什么？", True, ["low_confidence", "ots"]),
    ("用户权限发生调整后需要保留什么记录？", True, ["low_confidence", "access_control"]),
    ("执行结果不符合预期以后应该怎样闭环？", True, ["low_confidence", "defect_management"]),
    ("上线前谁需要确认哪些内容？", True, ["low_confidence", "release"]),
    ("产品退出使用后相关资料怎么处理？", True, ["low_confidence", "retirement"]),
]


TEST_DESIGN_QUESTIONS = [
    ("请为医疗器械软件登录失败锁定功能设计测试用例和预期结果。", ["functional", "security"]),
    ("如何测试不同角色对患者数据的访问权限？请给出测试步骤。", ["security", "access_control"]),
    ("为软件升级中断和回滚场景设计异常测试方案。", ["reliability", "software_update"]),
    ("医疗器械软件日期时间输入字段应如何设计边界值测试？", ["boundary", "input_validation"]),
    ("请根据风险控制要求设计报警功能的验证方法和测试点。", ["risk_based", "alarm"]),
    ("为审计日志的完整性、时间戳和防篡改能力设计测试方案。", ["security", "audit_log"]),
    ("软件更新后回归测试范围应如何转化为测试用例？", ["regression", "software_update"]),
    ("请给出网络断开、恢复和数据重传的测试前置条件与预期结果。", ["reliability", "network"]),
    ("如何测试第三方现成软件组件升级后的兼容性和风险？", ["compatibility", "ots"]),
    ("请为用户会话超时设计正向、异常和边界测试用例。", ["security", "session"]),
    ("依据风险管理标准，为高风险报警延迟设计可执行测试用例。", ["cross_intent", "alarm"]),
    ("根据网络安全指导原则设计身份认证失败与账户恢复测试。", ["cross_intent", "authentication"]),
    ("请设计数据备份、恢复完整性和恢复时间目标的验证方案。", ["reliability", "backup_restore"]),
    ("如何验证加密数据在存储、传输和密钥轮换过程中的安全性？", ["security", "encryption"]),
    ("为并发用户修改同一患者记录设计冲突和一致性测试。", ["concurrency", "data_integrity"]),
    ("请为低电量、意外断电和重启后的状态恢复设计异常测试。", ["reliability", "power_failure"]),
    ("如何针对软件安装、卸载、升级和降级设计兼容性测试矩阵？", ["compatibility", "deployment"]),
    ("为医疗器械软件接口超时、重复报文和乱序报文设计测试点。", ["interface", "fault_injection"]),
    ("请设计临床关键任务的可用性测试场景、观察指标和通过准则。", ["usability", "critical_task"]),
    ("如何将威胁建模中的攻击路径转化为渗透测试和安全测试用例？", ["security", "threat_model"]),
    ("请为算法输入超出训练分布的情况设计检测和降级测试。", ["ai_validation", "robustness"]),
    ("如何验证AI医疗器械模型更新前后的性能一致性和临床风险？", ["ai_validation", "software_update"]),
    ("为设备时钟漂移导致的日志顺序异常设计边界和恢复测试。", ["boundary", "audit_log"]),
    ("请设计数据库连接池耗尽时的告警、降级和数据完整性测试。", ["reliability", "resource_exhaustion"]),
    ("如何验证权限撤销后已有会话、缓存和令牌立即失效？", ["security", "access_control"]),
    ("为批量导入患者数据设计格式错误、部分失败和回滚测试。", ["data_integrity", "batch_processing"]),
    ("请设计软件缺陷修复后的定向复测与影响范围回归方案。", ["regression", "defect_management"]),
    ("如何测试多语言界面切换不会改变剂量、单位和关键提示含义？", ["localization", "safety"]),
    ("为云服务不可用、区域切换和服务终止设计业务连续性测试。", ["cloud", "business_continuity"]),
    ("请设计无网络条件下数据缓存、重连同步和重复提交测试。", ["offline", "data_integrity"]),
]


EVALUATION_QUESTIONS = [
    ("请复核这个回答的引用正确性：软件安全性级别只有严重一级。", ["citation", "factual_error"]),
    ("评估回答是否完整：缺陷管理只需要修复缺陷，不需要回归测试。", ["completeness", "omission"]),
    ("请检查该结论是否存在幻觉：所有医疗器械软件都必须采用云部署。", ["hallucination", "unsupported_claim"]),
    ("请对回答质量评分并说明证据是否支持：黑盒测试人员可以兼任开发人员。", ["citation", "quality"]),
    ("复核这段回答是否遗漏软件更新中的风险管理和用户告知要求。", ["completeness", "software_update"]),
    ("请核查回答中的[ID:9]是否属于有效引用，并判断引用正确性。", ["citation", "invalid_id"]),
    ("评测这份答案对标准答案要点的覆盖程度，并指出重要遗漏。", ["completeness", "coverage"]),
    ("请判断回答引用的DOC003条款能否直接支持其主要结论。", ["citation", "source_alignment"]),
    ("复核回答是否把用户需求与产品需求错误地视为同一概念。", ["hallucination", "concept_confusion"]),
    ("请评分：回答声称所有软件缺陷都必须在24小时内关闭。", ["hallucination", "unsupported_deadline"]),
    ("评估回答是否把合理概括误判成无依据扩展。", ["judge_boundary", "paraphrase"]),
    ("复核回答引用多个文件时，主要结论是否至少有一条直接证据支持。", ["citation", "multi_source"]),
    ("请评测拒绝回答是否合理：检索证据已经明确给出四种核查结论。", ["answerability", "refusal"]),
    ("判断回答只遗漏次要示例时，准确度应评为1还是2，并说明理由。", ["judge_boundary", "minor_omission"]),
    ("请检查回答是否将推荐性指导原则表述成强制性法规要求。", ["hallucination", "modality"]),
    ("评估回答中的适用范围是否被证据直接支持，还是无依据扩大。", ["hallucination", "scope"]),
    ("请核对回答中的条款编号、文件名称与所给证据是否一致。", ["citation", "metadata"]),
    ("复核回答是否覆盖问题要求的活动、输出和可追溯关系三个部分。", ["completeness", "multi_part"]),
    ("请判断答案虽然结论正确但没有内联引用时，引用正确性应如何评分。", ["citation", "missing_inline"]),
    ("评测回答是否把测试方法和测试阶段混为一谈。", ["accuracy", "concept_confusion"]),
    ("请复核回答中的数字阈值是否在引用证据中真实出现。", ["hallucination", "numeric_claim"]),
    ("判断回答增加的处理流程是否属于合理建议还是无依据强制要求。", ["hallucination", "prescriptive_claim"]),
    ("请评估回答是否只引用了背景段落而没有引用直接要求条款。", ["citation", "indirect_evidence"]),
    ("复核答案对重大更新与轻微更新的处理差异是否完整。", ["completeness", "classification"]),
    ("请判断回答将DOC003与DOC004的相同要求互相引用是否仍可接受。", ["citation", "acceptable_source"]),
    ("评测答案是否在证据不足时错误断言整份文档没有相关内容。", ["hallucination", "retrieval_failure"]),
    ("请检查回答中的FDA要求是否被误写为NMPA要求。", ["citation", "authority_mismatch"]),
    ("复核答案是否完整说明风险控制实施、验证和剩余风险评价。", ["completeness", "risk_management"]),
    ("评估引用证据相互冲突时，回答是否明确说明适用条件和不确定性。", ["quality", "conflicting_evidence"]),
    ("请对一份含正确结论、重要遗漏和无依据期限的回答分别判定引用、准确度与幻觉。", ["composite", "adversarial"]),
]


def make_case(
    case_id: str,
    question: str,
    agent: str,
    tags: list[str],
    expect_rewrite: bool = False,
) -> dict:
    tools = ["intent_router", "ragflow_knowledge_qa"]
    if expect_rewrite:
        tools.append("low_confidence_query_rewrite")
    if agent == "evaluation":
        tools.append("citation_reference_audit")
    return {
        "case_id": case_id,
        "question": question,
        "expected_agent": agent,
        "required_tools": tools,
        "min_references": 1,
        "expect_rewrite": expect_rewrite,
        "scenario_tags": tags,
    }


def build_cases() -> list[dict]:
    cases = []
    for index, (question, rewrite, tags) in enumerate(REGULATORY_QUESTIONS, 1):
        cases.append(make_case(f"AV2{index:03d}", question, "regulatory", tags, rewrite))
    for index, (question, tags) in enumerate(TEST_DESIGN_QUESTIONS, 31):
        cases.append(make_case(f"AV2{index:03d}", question, "test_design", tags))
    for index, (question, tags) in enumerate(EVALUATION_QUESTIONS, 61):
        cases.append(make_case(f"AV2{index:03d}", question, "evaluation", tags))
    assert len(cases) == 90
    assert len({item["question"] for item in cases}) == 90
    return cases


def main() -> int:
    payload = {
        "title": "医疗器械软件测试知识库 Agent 路由与工具调用评测集 v2",
        "version": "2.0.0",
        "frozen_at": "2026-08-27",
        "frozen_before_first_run": True,
        "description": (
            "90道平衡题，法规、测试设计、评测三类各30道；覆盖常规路由、"
            "跨意图边界、低置信度查询改写、引用异常、概念混合和复合失败场景。"
        ),
        "cases": build_cases(),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    CHECKSUM.write_text(f"{digest}  {OUTPUT.name}\n", encoding="utf-8")
    print(f"题数：{len(payload['cases'])}")
    print(f"评测集：{OUTPUT}")
    print(f"SHA-256：{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
