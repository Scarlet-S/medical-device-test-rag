from app.models import RouteDecision


INTENT_KEYWORDS: dict[str, dict[str, int]] = {
    "regulatory": {
        "法规": 4,
        "条款": 4,
        "指导原则": 4,
        "标准": 3,
        "规范": 3,
        "nmpa": 3,
        "fda": 3,
        "yy/t": 3,
        "gb/t": 3,
        "注册": 2,
        "体系核查": 3,
        "现场检查": 3,
        "召回": 2,
        "应当": 2,
        "强制要求": 3,
    },
    "test_design": {
        "测试方案": 5,
        "测试用例": 5,
        "设计测试": 5,
        "设计验证": 5,
        "验证方案": 5,
        "测试点": 4,
        "如何测试": 4,
        "如何验证": 4,
        "测试步骤": 4,
        "测试矩阵": 4,
        "预期结果": 3,
        "前置条件": 3,
        "边界值": 3,
        "边界测试": 3,
        "异常测试": 3,
        "恢复测试": 3,
        "兼容性测试": 3,
        "回滚测试": 3,
        "复测": 3,
        "回归测试": 2,
        "测试": 2,
        "覆盖率": 2,
        "验证方法": 2,
    },
    "evaluation": {
        "评测": 5,
        "评分": 5,
        "幻觉": 5,
        "引用正确": 5,
        "准确度": 4,
        "命中率": 4,
        "复核": 4,
        "核对回答": 8,
        "检查回答": 8,
        "判断回答": 8,
        "判断答案": 8,
        "复核答案": 8,
        "证据核查": 5,
        "引用证据": 4,
        "证据支持": 4,
        "证据不足": 4,
        "证据冲突": 4,
        "评估回答": 5,
        "回答质量": 4,
        "无依据": 3,
        "遗漏": 3,
        "是否完整": 2,
    },
}

INTENT_PRIORITY = ("evaluation", "test_design", "regulatory")


def route_intent(question: str) -> RouteDecision:
    normalized = question.strip().lower()
    scores: dict[str, int] = {}
    matches: dict[str, list[str]] = {}

    for intent, keywords in INTENT_KEYWORDS.items():
        intent_matches = [keyword for keyword in keywords if keyword in normalized]
        matches[intent] = intent_matches
        scores[intent] = sum(keywords[keyword] for keyword in intent_matches)

    highest_score = max(scores.values(), default=0)
    if highest_score == 0:
        return RouteDecision(
            intent="regulatory",
            selected_agent="regulatory",
            confidence=0.4,
            matched_keywords=[],
            scores=scores,
            reason="未命中专用意图词，回退到覆盖范围最广的法规知识 Agent。",
        )

    selected = next(
        intent
        for intent in INTENT_PRIORITY
        if scores[intent] == highest_score
    )
    ordered_scores = sorted(scores.values(), reverse=True)
    runner_up = ordered_scores[1] if len(ordered_scores) > 1 else 0
    margin = highest_score - runner_up
    confidence = min(0.98, 0.62 + highest_score * 0.025 + margin * 0.02)

    return RouteDecision(
        intent=selected,
        selected_agent=selected,
        confidence=round(confidence, 2),
        matched_keywords=matches[selected],
        scores=scores,
        reason=(
            f"{selected} 意图得分最高（{highest_score}），"
            f"领先次高意图 {margin} 分。"
        ),
    )
