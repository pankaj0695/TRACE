# TRACE: Adding the Investigator agent

Status: design document with code skeletons. The skeletons are written against the real TRACE code (file and function names below were checked), but they have **not been run or tested yet**.

## 1. Purpose and scope

TRACE today is a fixed pipeline. The LLM is used only to draft the report. This change adds **one new agent, the Investigator**, and nothing else (no upfront planner, no A2A, no new HITL gate).

What it changes:

| | Today | With the Investigator |
|---|---|---|
| Who decides what happens next | A fixed graph | The graph, plus a model that chooses which evidence to look at next |
| Role of the LLM | Writes the report after the score is final | Reasons about ambiguous evidence before the score is final |
| What happens on a detector conflict | Flagged, then drafted into the report | Investigated, then re-scored, or handed to a human with a reason |

What stays deterministic, on purpose:
- the detector maths (anomaly, authenticity, network);
- the scoring formula, the weights and the tier cut-offs;
- the governance gates.

So the workflow becomes **model-driven in its control flow, but deterministic in its arithmetic**. The model decides what to look at. It never decides the score.

## 2. Current behaviour (from the code)

```
ingestion -> router (>= min_reviews) -> anomaly | authenticity | network (parallel)
          -> scoring -> orchestrator (Gemini report, rule-based fallback) -> END
```

Facts that matter for this design:
- `pipeline/graph.py` builds the graph with `StateGraph(PipelineState)` and ends with `g.compile()` (no checkpointer). The only edge after scoring is `scoring -> orchestrator`.
- `pipeline/state.py`: `PipelineState` holds `product_id, context, signals, assessment, report`. `signals` uses the `merge_signals` reducer (`{**left, **right}`), so a re-run of an agent overwrites its previous signal.
- `agents/scoring.py`: `DETECTOR_WEIGHTS = {anomaly 0.35, authenticity 0.30, network 0.35}`. Only signals whose key is in the weights and whose status is `ok` are used. `conflict` is true when two signals with confidence >= 0.5 differ by >= 0.6.
- `agents/orchestrator.py`: the LLM is called once, through `GovernedLLM`, to write the report. If it fails, `_rule_report` is used.
- `services/analysis.py`: `AnalysisService.stream` runs the graph with `stream_mode="updates"` and uses `STAGES` and `_unblocked` to drive the live progress indicators.

## 3. Where the Investigator sits

```
ingestion -> detectors (parallel) -> scoring -> [escalation check]
                                         ^            |
                                         |       no   |   yes
                                         |            v         v
                                         |       orchestrator  investigator
                                         |                      |
                                         +----------------------+
                                           (re-score, bounded rounds)
```

Two additions to the graph:
1. **A rule-based escalation check** (a conditional edge after scoring, no LLM).
2. **The `investigator` node**, which loops back to `scoring`.

### 3.1 Escalation rule (deterministic)

Escalate only when the evidence is ambiguous, otherwise the loop would run on almost every listing.

```python
def needs_escalation(state, max_rounds: int) -> bool:
    a = state["assessment"]
    if state.get("rounds", 0) >= max_rounds or a.tier == RiskTier.INSUFFICIENT:
        return False
    signals = state["signals"]
    weak = any(s.status == "ok" and s.confidence < 0.5 for k, s in signals.items() if k in DETECTORS)
    return a.conflict or (a.tier in (RiskTier.HIGH, RiskTier.CRITICAL) and weak)
```

Do not escalate on low confidence alone. In the real sample the network detector has confidence 0.2 on many listings, because only about 2 of 50 reviewers have any other review in the data.

### 3.2 The investigation loop (ReAct, bounded)

Inside the node, the model repeats: choose a tool, read the result, choose again or finish. Limits:
- at most **4 tool calls** per round;
- at most `investigation_max_rounds` rounds per analysis (default **1**; the graph shape allows more);
- every model call goes through the existing `GovernedLLM`, so it is approved, pseudonymised, recorded in the egress ledger and scrubbed like the report call.

Tools are small, read-only, bounded functions over services the container already has (`ctx`, `graph`, the embedder, `ReviewSearch`):

| Tool | What it returns | Built on |
|---|---|---|
| `burst_profile` | Rating, verified and first-time shares inside the peak week vs outside | `AnomalyAgent._peak_window` plus the context |
| `burst_text_similarity` | Near-duplicate or templated wording among the burst reviews only | the existing embedder |
| `reviewer_history` | Other-product reviews of the burst reviewers | `graph.neighborhood(product_id)` |
| `co_review_pairs` | Pairs among the burst reviewers sharing other products | `graph.co_review_pairs` |
| `similar_reviews` | Semantically similar reviews elsewhere | `ReviewSearch.search` |

These tools do not exist in MCP today, so they are new internal functions, not reuses of MCP tools.

**Handles instead of IDs.** The model never sees real reviewer or review IDs. The code gives the burst reviews handles (`r1` to `r11`) and maps them back. That keeps real IDs out of the prompt and makes citations checkable.

Model step schema (JSON-schema constrained, like the report call):

```python
class Step(BaseModel):
    action: Literal["tool", "finish"]
    tool: Literal["burst_profile", "burst_text_similarity", "reviewer_history",
                  "co_review_pairs", "similar_reviews"] | None = None
    args: dict = {}
    reason: str

class Verdict(BaseModel):
    verdict: Literal["supports_burst", "explains_burst", "unresolvable"]
    risk: float
    confidence: float
    findings: list[dict]        # title, detail, cited handles
    unresolved_reason: str | None = None
```

### 3.3 What the node writes

The Investigator **adds a signal; it never edits one**:

```python
return {
  "signals": {"investigator": AgentSignal(agent="investigator", risk=..., confidence=..., findings=..., metrics={...})},
  "investigation_log": [ {tool, args, result_summary}, ... ],   # appended
  "rounds": state.get("rounds", 0) + 1,
}
```

Verdict mapping, enforced in code:

| Verdict | Signal | Effect on score |
|---|---|---|
| `supports_burst` | risk >= 0.5, confidence capped at 0.8 | raises confidence in the burst finding |
| `explains_burst` | risk <= 0.3, confidence capped at 0.8 | lowers the risk (for example a promotion explains the spike) |
| `unresolvable` | risk 0, confidence <= 0.2 | almost none; the run keeps its flags and goes to a human with the reason |

### 3.4 Fallback when the LLM is unavailable

If `LLMUnavailable` is raised, a rule-based investigator runs `burst_profile` and `burst_text_similarity` only, and returns a verdict by fixed rules (for example `supports_burst` when the burst is more 5-star than the rest by >= 0.15 and less verified, otherwise `unresolvable`). The loop therefore works without a model, as the report step already does.

## 4. Guardrails (this is what keeps it governed)

- **No score control.** It cannot change weights, thresholds or the conflict gap, and it cannot overwrite a detector signal. Its output is one added signal.
- **Everything is logged.** Each tool call and result summary goes into `investigation_log`, which is stored in the analysis lineage, so a reviewer can see what was tried.
- **Egress.** All model calls use `GovernedLLM` (mode, approved processors, pseudonymisation, ledger row before the call, output scrub).
- **Untrusted text.** Review text returned by tools is truncated, labelled as untrusted, and the system prompt says never to follow instructions inside it. The injection guard from the cookbook (`governance/guardrails.py`) should be applied to tool results.
- **Validation in code.** Tool name must be in the allowlist, arguments are validated, every cited handle must exist, risk and confidence are clamped, and a verdict must cite at least one tool result.
- **Budgets.** At most 4 tool calls per round and a cap on model calls per analysis, so cost and latency are bounded.

## 5. Files to add or change

| File | Change |
|---|---|
| `agents/investigator.py` (new) | `InvestigatorAgent`: the loop, tool registry, validation, rule-based fallback |
| `pipeline/state.py` | Add `rounds: int` and `investigation_log: Annotated[list, operator.add]` |
| `pipeline/graph.py` | Add the node, replace `scoring -> orchestrator` with a conditional edge, add `investigator -> scoring` |
| `agents/scoring.py` | Add `"investigator": 0.20` to the weights (see the warning below) |
| `agents/orchestrator.py` | Put the investigator verdict and `unresolved_reason` into the prompt and the rule report; add finding codes to `POLICY` and `ACTION` |
| `services/analysis.py` | Add `investigator` to the stage list and handle it in `_unblocked`, since it can appear after scoring |
| `container.py` | Construct `InvestigatorAgent` with the same governed `llm`, the graph store and the embedder, and pass it to `build_pipeline` |
| `core/config.py` | `investigation_max_rounds` (default 1), `investigation_max_tool_calls` (default 4) |

### Graph change

```python
g.add_node("investigator", investigator)
g.add_conditional_edges(
    scoring.name,
    lambda s: "investigator" if needs_escalation(s, max_rounds) else orchestrator.name,
    {"investigator": "investigator", orchestrator.name: orchestrator.name},
)
g.add_edge("investigator", scoring.name)
# remove: g.add_edge(scoring.name, orchestrator.name)
```

### Warning: the `degraded` flag in scoring

`TrustScoringAgent.assess` sets `degraded = any(signals.get(k) is None or signals[k].status != "ok" for k in self.weights)`. If `investigator` is simply added to the weights, every first-pass run has no investigator signal and would be marked degraded and `needs_manual_review`. Exclude optional signals:

```python
OPTIONAL = {"investigator"}
degraded = any(signals.get(k) is None or signals[k].status != "ok"
               for k in self.weights if k not in OPTIONAL)
```

On the first pass the weight does not matter, because only present signals are used.

## 6. Worked example: B000C239IQ (real run of the original pipeline)

First pass: anomaly risk 1.0 (confidence 1.0), authenticity 0.0 (1.0), network 0.0 (0.2). Risk 69.2, tier high, `conflict = true`.

Escalation fires (conflict). What the data shows about the burst: all 11 burst reviews are 5-star, against 82% elsewhere on the listing; 27% of burst reviews are verified, against 41% elsewhere; only 2 of the 50 reviewers have any other review.

What the Investigator can and cannot do here:
- `burst_profile` mostly repeats what the anomaly detector already found.
- `reviewer_history` and `co_review_pairs` find almost nothing, because the sample has almost no cross-product history. The network detector's low confidence comes from missing data, not from a wrong window, so widening the window does not help.
- `burst_text_similarity` is the one new piece of evidence.

Likely outcome: `unresolvable`, with the reason "network evidence unavailable: 2 of 50 reviewers have history". The score stays about the same, the run keeps its flags, and the report tells the reviewer exactly what was tried. That is a legitimate result. The loop either resolves a conflict with evidence or proves it cannot be resolved and says why.

## 7. Tests (with a scripted fake LLM)

1. Escalation fires on a conflict, does not fire on a consistent listing, and stops at the round limit.
2. A scripted run of 2 tool calls then `finish` produces an `investigator` signal and a log with 2 entries.
3. A tool name outside the allowlist is rejected, and a cited handle that does not exist is dropped.
4. A tool-call budget overrun stops the loop.
5. `LLMUnavailable` triggers the rule-based fallback and the graph still completes.
6. The first-pass `needs_manual_review` is unchanged for a clean listing (the `degraded` warning).
7. The investigator never alters weights or an existing detector signal.
8. Prompt-injection text inside a burst review does not change the tool choice.

## 8. Limitations of this addition

- On the current sample the Investigator will often end `unresolvable`, because cross-product history is thin. It shows its value on richer data or with an external source.
- The model's verdict is only as good as the tool evidence, so tool outputs must be correct and bounded.
- More model calls mean more latency and cost, and more egress to log. The budgets and the fallback limit this.
- Nothing here removes the need for a human on high-risk results. The approval gate is a separate change.

## 9. How to explain it in the viva

"We kept the scoring core deterministic for auditability and added a bounded investigator on top. When detectors disagree, a model chooses which evidence to examine, through governed read-only tools, and adds one signal. It cannot change weights or thresholds, every step is logged, and when the evidence is not there it says so and hands the case to a human."
