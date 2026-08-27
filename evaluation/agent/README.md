# Agent evaluation

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

## Frozen 90-case v2 set

`agent_evaluation_v2.json` expands the specialized evaluation to 90 unique
cases while keeping the three routes balanced:

- 30 regulatory cases;
- 30 test-design cases;
- 30 answer-evaluation cases.

The set includes ordinary routing, ambiguous and cross-intent wording,
low-confidence query rewriting, citation failures, unsupported facts,
concept confusion, and composite failure cases. It was frozen before its
first online run. Verify the checked-in file before running it:

```powershell
Get-FileHash evaluation\agent\agent_evaluation_v2.json -Algorithm SHA256
Get-Content evaluation\agent\agent_evaluation_v2.sha256
```

Recreate the asset deterministically and run the complete set:

```powershell
python scripts/create_agent_evaluation_v2.py
python scripts/run_agent_eval.py `
  --limit 90 `
  --dataset evaluation\agent\agent_evaluation_v2.json `
  --label agent_v2_90_frozen_once
```

Do not edit the v2 cases after using their results for analysis. A future
changed set must use a new filename and checksum.

The first frozen run completed 79/90 requests (87.8%). Conditional routing
accuracy, Macro-F1, required-tool recall, and reference coverage were all
100%; successful-case task completion was 96.2% and p95 latency was 52.7 s.
The 11 infrastructure failures were preserved, retried separately, and merged
without overwriting the first result. The recovery view completed 90/90
requests with 100% end-to-end routing and tool recall, 95.6% task completion,
and 51.4 s p95 latency.
