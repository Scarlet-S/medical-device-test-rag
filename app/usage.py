import math
import os
import re

from app.models import UsageEstimate


CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def estimate_tokens(text: str) -> int:
    """Return a transparent heuristic, not provider-reported token usage."""
    if not text:
        return 0
    cjk_count = len(CJK_PATTERN.findall(text))
    non_cjk_count = sum(
        1 for char in text if not char.isspace() and not CJK_PATTERN.match(char)
    )
    return cjk_count + math.ceil(non_cjk_count / 4)


def build_usage_estimate(input_text: str, output_text: str) -> UsageEstimate:
    input_tokens = estimate_tokens(input_text)
    output_tokens = estimate_tokens(output_text)
    input_price = float(os.getenv("LLM_INPUT_COST_PER_1M_TOKENS", "0") or 0)
    output_price = float(os.getenv("LLM_OUTPUT_COST_PER_1M_TOKENS", "0") or 0)
    pricing_configured = input_price > 0 or output_price > 0
    estimated_cost = None
    if pricing_configured:
        estimated_cost = round(
            (input_tokens * input_price + output_tokens * output_price) / 1_000_000,
            8,
        )

    return UsageEstimate(
        source="heuristic",
        input_characters=len(input_text),
        output_characters=len(output_text),
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        estimated_cost_usd=estimated_cost,
        pricing_configured=pricing_configured,
        note=(
            "RAGFlow当前响应未提供provider usage；token与费用为启发式估算。"
            if pricing_configured
            else "RAGFlow当前响应未提供provider usage；仅记录启发式token估算，未配置单价。"
        ),
    )
