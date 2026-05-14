# HR Agent Eval Harness

Scores `backend.agents.hr_agent` (chat v2) against 30 canonical HR queries.
Each golden specifies expected tool calls + a rubric; a LITE-model judge
scores the actual run on three 0-5 dimensions.

## Files

- `golden.jsonl` - 30 canonical Q -> expected-tool-trace + rubric (one JSON per line)
- `run_eval.py` - runner: invokes agent, captures trace, calls judge, writes report
- `report.json` - written by the runner (per-run scores + aggregate)

## Running

In Docker (recommended):

```bash
docker exec pulse-api python -m backend.agents.eval.run_eval
```

Locally:

```bash
python -m backend.agents.eval.run_eval
```

Smoke test (first 5 goldens):

```bash
python -m backend.agents.eval.run_eval --limit 5 --out /tmp/eval-smoke.json
```

## CI Gate

The runner exits **0** if overall avg score >= **4.0**, else **1**.
Wire into CI as a required check before merging changes to `hr_agent.py`,
the tool layer, or any prompt/system-message file.

## Scoring (judge prompt)

Each interaction is scored 0-5 on:

| Dimension     | Meaning |
|---------------|---------|
| correctness   | Does the answer satisfy the rubric? |
| tool_choice   | Did it pick reasonable tools? Bonus if all expected tools fired |
| conciseness   | No rambling / padding |

Judge model: `LITE_MODEL` (Gemini 3.1 Flash Lite), temperature `0.1` for
determinism. Output parsed as JSON; malformed responses score 0 with note
`judge_parse_failed`.

## Categories

3-5 goldens each:

- **search** (5)    - find candidates by skill/exp/location
- **profile** (4)   - get candidate detail / qualifications
- **scoring** (4)   - score candidate vs. position
- **pipeline** (4)  - stage counts / who is stuck
- **analytics** (4) - funnel, conversion, time-to-hire
- **email** (3)     - draft rejection / offer
- **brain** (3)     - query / update past learnings
- **multi-step** (3)- find -> score -> draft chains

## Adding a Golden

Append one JSON line to `golden.jsonl`:

```json
{"id": "g031", "category": "search", "q": "Find Rust engineers in Berlin", "expected_tools": ["query_cvs"], "rubric": "Returns Rust devs filtered to Berlin; honest if no matches."}
```

Required fields:

- `id`        - unique, format `g###`
- `category`  - one of the 8 above (add new only with team review)
- `q`         - user message (single string)
- `expected_tools` - list of tool names; order does not matter, partial match still scores
- `rubric`    - 1-2 sentences for the judge

Validate before committing:

```bash
python -c "import json; [json.loads(l) for l in open('backend/agents/eval/golden.jsonl')]"
```

## Threshold rationale

`avg >= 4.0` chosen so all three dims must average "good" (4) or higher.
A single dim dipping to 3 across the suite is recoverable; two dims at 3
will fail and force investigation.

## Cost / runtime

- 30 goldens x (1 agent run + 1 judge call) per execution
- Judge: LITE_MODEL, ~300 out tokens, ~$0.0002/call -> **~$0.006/eval run**
- Agent cost depends on tool fan-out; budget ~$0.10-0.30/eval run
- Wall time: ~2-5 min depending on agent latency and tool I/O
