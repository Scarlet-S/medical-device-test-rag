# Agent evaluation v1

This frozen 30-case set is balanced across the regulatory, test-design, and
evaluation agents. It measures:

- routing accuracy and Macro-F1;
- required-tool recall and tool outcomes;
- reference coverage and citation-gate completion;
- low-confidence query-rewrite behavior;
- end-to-end p50/p95 latency and heuristic token/cost estimates.

Run a smoke test after the Agent API is available:

```powershell
python scripts/run_agent_eval.py --limit 3 --label agent_v1_smoke
```

Run the complete frozen set:

```powershell
python scripts/run_agent_eval.py --limit 30 --label agent_v1_frozen
```

The cost field remains null until the two per-million-token price variables
in `.env` are configured. It is an explicit estimate, not provider billing.
