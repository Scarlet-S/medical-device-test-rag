from app.usage import build_usage_estimate, estimate_tokens


def test_token_estimate_counts_cjk_and_compacts_latin():
    assert estimate_tokens("医疗AItest") == 4
    assert estimate_tokens("") == 0


def test_usage_estimate_is_explicitly_heuristic(monkeypatch):
    monkeypatch.setenv("LLM_INPUT_COST_PER_1M_TOKENS", "2")
    monkeypatch.setenv("LLM_OUTPUT_COST_PER_1M_TOKENS", "4")

    usage = build_usage_estimate("医疗", "测试")

    assert usage.source == "heuristic"
    assert usage.pricing_configured is True
    assert usage.estimated_cost_usd == 0.000012
    assert "不是provider" not in usage.note
