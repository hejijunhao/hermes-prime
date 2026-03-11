# Hermes Hunter: Meta-Agent Architecture

## Overview

A two-agent system where an **Overseer** (the Master) autonomously improves a **Hunter** (the Worker) that finds legitimate software vulnerabilities for bug bounty submission. The Overseer operates at two levels: runtime steering (prompt injection, interrupts, instruction modification) and source-code evolution (rewriting the Hunter's tools, skills, prompts, and core logic, then redeploying).

Both agents use **Elephantasm** for long-term agentic memory and observability, replacing the need for custom metrics infrastructure.

---

## 1. System Topology

```
                    ┌─────────────────────────────────┐
                    │          OVERSEER AGENT          │
                    │  (runs on main branch)           │
                    │  Anima: overseer                 │
                    │                                  │
                    │  Responsibilities:               │
                    │  - Monitor Hunter via Elephantasm │
                    │  - Evaluate Hunter performance   │
                    │  - Select models within budget   │
                    │  - Inject runtime instructions   │
                    │  - Rewrite Hunter source code    │
                    │  - Redeploy Hunter process       │
                    │  - Self-regulate intervention    │
                    │    frequency and learn from it   │
                    └──────────┬───────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │   CONTROL CHANNEL   │
                    │  (IPC + Elephantasm) │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────────────────┐
                    │          HUNTER AGENT            │
                    │  (runs on hunter/live worktree)  │
                    │  Anima: hunter                   │
                    │                                  │
                    │  Responsibilities:               │
                    │  - Discover bounty targets       │
                    │  - Clone & analyse repos         │
                    │  - Spawn subagents for parallel  │
                    │    analysis (full discretion)    │
                    │  - Identify vulnerabilities      │
                    │  - Build PoC exploits (dynamic)  │
                    │  - Draft submission reports      │
                    └──────────┬──────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
         ┌────┴────┐     ┌────┴────┐     ┌────┴────┐
         │Subagent │     │Subagent │     │Subagent │
         │ (recon) │     │(analyze)│     │ (PoC)   │
         └─────────┘     └─────────┘     └─────────┘
         Hunter spawns as many subagents as it wants.
         Overseer refines this strategy over time.
```

### Why Git Worktrees?

The Hunter runs from a **git worktree** of the Hermes repo on the `hunter/live` branch. This is critical because:

1. **The Overseer can modify the Hunter's code without destabilising itself.** If the Overseer rewrites `run_agent.py` in the Hunter's worktree, its own `run_agent.py` is untouched.
2. **Rollback is trivial.** Each improvement is a git commit in the Hunter's branch. If a change degrades performance, the Overseer reverts the commit and redeploys.
3. **The two agents can run different versions of the codebase simultaneously.** The Overseer stays on a stable branch; the Hunter is on the evolving `hunter/live` branch.
4. **Deployment isolation.** The Hunter can run in a Docker container or Modal sandbox while the Overseer runs locally, or both can run in separate containers.

### Process Architecture

- **Separate OS processes.** The Hunter runs as a fully separate process from the Overseer. This is required for code evolution — the Overseer must be able to kill, modify, and restart the Hunter without affecting itself.
- **One Hunter, unlimited subagents.** A single Hunter instance manages its own parallelism by spawning subagents (via `delegate_task`). The Overseer optimises how the Hunter delegates over time.
- **Independent budgets.** The Overseer and Hunter have separate iteration/cost budgets. The human sets budget constraints (see §4.3); the Overseer allocates within them.

---

## 2. Overseer Architecture

The Overseer is itself a Hermes agent, but with a specialised toolset and system prompt focused on agent improvement rather than task execution.

### 2.1 Overseer Toolset

| Tool | Purpose |
|------|---------|
| `hunter_spawn` | Deploy a new Hunter instance (from current Hunter branch) |
| `hunter_kill` | Terminate the running Hunter process |
| `hunter_status` | Get Hunter health: running/stopped, iteration count, last tool call, error state |
| `hunter_logs` | Stream or tail the Hunter's full I/O log (conversation history) |
| `hunter_inject` | Push a runtime instruction into the Hunter's next iteration (ephemeral system prompt) |
| `hunter_interrupt` | Gracefully interrupt the Hunter mid-task with a message |
| `hunter_code_edit` | Edit a file in the Hunter's worktree (wrapper around file write + git commit) |
| `hunter_code_read` | Read a file from the Hunter's worktree |
| `hunter_redeploy` | Kill current Hunter, rebuild from worktree, spawn new instance |
| `hunter_diff` | Show uncommitted or recent changes in the Hunter's worktree |
| `hunter_rollback` | Revert the Hunter's worktree to a previous commit and redeploy |
| `hunter_model_set` | Change the LLM model the Hunter (or its subagents) uses |
| `budget_status` | Check remaining budget, current spend rate, projected runway |
| `bounty_search` | Search bug bounty platforms for active programs |
| `bounty_submit` | Submit a completed vulnerability report (with human approval gate) |
| `human_review` | Send a report to the human for review/approval (terminal + Telegram) |

### 2.2 Model Selection & Routing

The Overseer controls which LLM the Hunter uses and can change it at any time. Models are **open-source** (Qwen 3.5, Kimi K2.5, etc.) with tiered sophistication levels analogous to Opus/Sonnet/Haiku:

| Tier | Use Case | Example Models |
|------|----------|----------------|
| Heavy (Opus-class) | Complex analysis, novel vuln classes, report writing | Qwen 3.5 72B, Kimi K2.5 |
| Medium (Sonnet-class) | Standard code review, known patterns, tool orchestration | Qwen 3.5 32B |
| Light (Haiku-class) | Recon, dependency checks, boilerplate tasks, subagent work | Qwen 3.5 7B |

The Overseer decides model allocation based on:
- **Remaining budget** — switch to lighter models as budget runs low
- **Task complexity** — recon doesn't need Opus-class; novel vuln hunting does
- **Historical performance** — which model found the most real vulns per dollar?

This is a key area for self-improvement. The Overseer tracks which model selections led to good outcomes and adjusts its strategy over time.

### 2.3 Overseer Control Loop

The Overseer runs its own `AIAgent.run_conversation()` loop, but its "task" is not a user request — it's the continuous improvement of the Hunter. The loop looks like this:

```
┌─────────────────────────────────────────────────────┐
│                  OVERSEER MAIN LOOP                  │
│                                                      │
│  1. CHECK Hunter status (running? stuck? errored?)   │
│     └─ If stopped/crashed → diagnose, fix, redeploy │
│                                                      │
│  2. INJECT memory context from Elephantasm           │
│     └─ inject(anima="overseer",                      │
│              query="recent hunter performance")      │
│     └─ Retrieve: what interventions worked, what     │
│        failed, current strategy effectiveness        │
│                                                      │
│  3. REVIEW Hunter's event stream (via Elephantasm)   │
│     └─ Query Hunter's Anima for recent events        │
│     └─ Look for: inefficiencies, repeated failures,  │
│        missed opportunities, tool misuse, dead ends  │
│                                                      │
│  4. EVALUATE against the only metric that matters:   │
│     └─ Are we producing high-quality reports that    │
│        are likely to earn $$$?                       │
│     └─ Supporting signals: vuln severity, report     │
│        completeness, PoC reliability, time/cost      │
│                                                      │
│  5. CHECK budget constraints                         │
│     └─ Current spend rate vs. budget limits          │
│     └─ Adjust model tier if needed                   │
│                                                      │
│  6. DECIDE intervention type:                        │
│     ├─ No action needed → continue monitoring        │
│     ├─ Soft intervention → inject runtime guidance   │
│     ├─ Hard intervention → modify code + redeploy   │
│     └─ Model change → switch Hunter's LLM tier      │
│                                                      │
│  7. If HARD intervention:                            │
│     a. Identify the code to change                   │
│     b. Write the change in Hunter's worktree         │
│     c. Commit with descriptive message               │
│     d. Kill Hunter, redeploy from new commit         │
│     e. Monitor first N turns of new deployment       │
│     f. If regression → rollback + redeploy           │
│                                                      │
│  8. EXTRACT events to Elephantasm (own Anima)        │
│     └─ Record: what was observed, decided, changed   │
│     └─ The Dreamer synthesises this into long-term   │
│        knowledge about what improvements work        │
│                                                      │
│  9. SLEEP / WAIT for next monitoring interval        │
│     └─ Or trigger immediately on Hunter error/stall  │
│     └─ Intervention frequency is self-regulated —    │
│        the Overseer learns its own optimal cadence   │
└─────────────────────────────────────────────────────┘
```

### 2.4 Self-Regulating Intervention Strategy

The Overseer does **not** have a fixed intervention frequency. It decides for itself how aggressive to be, and evaluates whether its decisions were correct:

- After each intervention, it tracks the outcome (improvement, regression, neutral)
- Over time, Elephantasm memory builds up a knowledge base: "frequent skill changes help", "model switches during active analysis cause context loss", "recon phases don't need heavy models", etc.
- The Overseer's `inject()` call at the start of each loop brings back this learned strategy
- If it's been too aggressive recently (thrashing, regressions), the memory will reflect that and it will back off
- If it's been too passive (stagnating metrics), the memory will reflect that too

### 2.5 Overseer System Prompt (Sketch)

```
You are the Overseer — a meta-agent responsible for continuously
improving a bug-bounty Hunter agent. Your Hunter is a separate
Hermes agent instance running from a git worktree you control.

Your job is NOT to find vulnerabilities yourself. Your job is to
make the Hunter better at finding them. You do this by:

1. Monitoring the Hunter's events and decisions via Elephantasm
2. Identifying inefficiencies, failures, and missed opportunities
3. Making targeted improvements — runtime guidance, code changes,
   or model selection adjustments
4. Measuring whether improvements actually helped
5. Managing the LLM budget — selecting the right model tier for
   each task, staying within the human-set budget constraints

You have three intervention modes:
- SOFT: Inject a runtime instruction via hunter_inject. Use this for
  tactical steering ("try SQL injection on the /api/users endpoint")
- HARD: Modify the Hunter's source code via hunter_code_edit, then
  redeploy. Use this for systemic improvements ("the Hunter doesn't
  check for IDOR patterns — add a new skill for it")
- MODEL: Change the Hunter's LLM via hunter_model_set. Use this for
  cost/performance optimization ("recon phase doesn't need 72B")

Always prefer the least invasive intervention. Soft before hard.
Small targeted changes before large rewrites. Always commit changes
with clear messages. Always monitor the impact of your changes.

If a hard intervention causes regression, rollback immediately.

You decide your own intervention cadence. Track whether your recent
decisions helped or hurt, and adjust. Your Elephantasm memory will
help you remember what strategies work.

The ultimate metric is: high-quality vulnerability reports that earn
bounty payouts. Everything else is a supporting signal.
```

---

## 3. Hunter Architecture

The Hunter is a standard Hermes agent with a specialised toolset and skills focused on security research and bug bounty hunting. It has **full discretion** over its own workflow, including spawning subagents for parallel analysis.

### 3.1 Hunter Toolset

Inherits from `hermes-cli` base toolset, plus:

| Tool | Purpose |
|------|---------|
| `target_clone` | Clone a target repository into an isolated workspace |
| `target_scan` | Run static analysis tools (semgrep, CodeQL, bandit, etc.) on cloned code |
| `target_dast` | Spin up a target application and run dynamic analysis (fuzzing, endpoint testing) |
| `vuln_assess` | Structured vulnerability assessment — severity, exploitability, impact |
| `poc_build` | Create a proof-of-concept exploit (sandboxed execution) |
| `poc_verify` | Run the PoC against a local/sandboxed instance of the target |
| `report_draft` | Generate a structured vulnerability report (follows HackerOne/Bugcrowd templates) |
| `report_review` | Self-review a draft report for completeness, accuracy, and clarity |
| `attack_surface_map` | Map endpoints, inputs, auth flows, data flows of a target |
| `dependency_audit` | Check target's dependencies for known CVEs |
| `dedup_check` | Query Elephantasm memory to check if a finding has been seen before |

Plus the existing Hermes tools: `terminal`, `browser`, `web_search`, `file` ops, `execute_code`, `delegate_task`.

### 3.2 Hunter Workflow (Per Target)

```
Phase 1: RECONNAISSANCE
  ├─ Clone target repo
  ├─ Read documentation, README, CHANGELOG
  ├─ Map attack surface (endpoints, auth, data flows)
  ├─ Identify technology stack and frameworks
  ├─ Check dependencies for known CVEs
  └─ Can spawn subagents for parallel recon tasks

Phase 2: ANALYSIS (Static + Dynamic)
  ├─ Run static analysis (semgrep rules, CodeQL queries)
  ├─ Spin up target application in sandbox (if possible)
  ├─ Dynamic testing: fuzz inputs, test auth flows, probe endpoints
  ├─ Manual code review of high-risk areas:
  │   ├─ Authentication / authorization
  │   ├─ Input validation / sanitization
  │   ├─ SQL / NoSQL query construction
  │   ├─ File upload / path traversal
  │   ├─ SSRF / open redirect
  │   ├─ Cryptographic implementations
  │   ├─ Race conditions / TOCTOU
  │   └─ Business logic flaws
  ├─ Cross-reference with known vulnerability patterns
  ├─ Check Elephantasm memory for similar findings in other targets
  ├─ Can spawn subagents for parallel analysis of different areas
  └─ Prioritise findings by severity and exploitability

Phase 3: VERIFICATION
  ├─ Build minimal PoC for each finding
  ├─ Test PoC in sandboxed environment (dynamic execution)
  ├─ Confirm exploitability and impact
  ├─ Rule out false positives
  └─ Dedup check: query memory to avoid reporting known issues

Phase 4: REPORTING
  ├─ Draft structured report per finding:
  │   ├─ Title, severity (CVSS), CWE classification
  │   ├─ Description of the vulnerability
  │   ├─ Steps to reproduce
  │   ├─ Proof of concept (code + output)
  │   ├─ Impact assessment
  │   └─ Suggested remediation
  ├─ Self-review for completeness and accuracy
  └─ Queue for Overseer review → human approval → submission
```

### 3.3 Subagent Strategy

The Hunter has full discretion to spawn subagents via `delegate_task`. Initial strategy is up to the Hunter, but the Overseer refines it over time. Possible patterns:

- **Parallel recon**: one subagent per major component (frontend, API, auth, database layer)
- **Specialist analysis**: spawn a subagent focused on a specific vuln class (IDOR, injection, auth bypass)
- **PoC parallelism**: build and verify multiple PoCs simultaneously
- **Multi-language**: subagent per language when target has mixed codebases

The Overseer can steer subagent strategy by:
- Modifying the Hunter's `delegate_task` prompts/skills
- Injecting runtime guidance about when to parallelize
- Changing the model tier used for subagents (lighter models for bulk work)

### 3.4 Hunter Skills (Initial Set)

These are Markdown skill files in `skills/security/` that the Hunter loads into its system prompt:

| Skill | Content |
|-------|---------|
| `owasp-top-10` | Patterns and detection strategies for OWASP Top 10 |
| `code-review-checklist` | Systematic code review methodology for security |
| `semgrep-rules` | How to write and run custom semgrep rules |
| `cve-research` | How to check NVD, GitHub advisories, OSV for known vulns |
| `report-writing` | Bug bounty report templates and best practices |
| `scope-assessment` | How to read bounty program scope and avoid out-of-scope work |
| `idor-hunting` | Insecure Direct Object Reference detection patterns |
| `auth-bypass` | Authentication and authorization bypass techniques |
| `injection-patterns` | SQL, NoSQL, command, template injection detection |
| `ssrf-detection` | Server-Side Request Forgery identification methods |
| `dynamic-testing` | How to spin up targets, fuzz inputs, test runtime behaviour |

These skills are **the primary target for Overseer improvement**. When the Overseer notices the Hunter is weak at something, the first move is to create or improve a skill.

---

## 4. Elephantasm Integration

Elephantasm (`pip install elephantasm`) replaces the proposed custom SQLite metrics/logging infrastructure. It serves as both the **long-term memory system** and the **observability platform**.

### 4.1 Anima Architecture

Each agent gets its own Anima (isolated identity container):

```
┌─────────────────────────────────────────────────┐
│              ELEPHANTASM                         │
│                                                  │
│  Anima: "overseer"                               │
│    ├─ Events: interventions, decisions, evals    │
│    ├─ Memories: what improvements work/fail      │
│    ├─ Knowledge: learned strategies, patterns    │
│    └─ Identity: Overseer's evolved approach      │
│                                                  │
│  Anima: "hunter"                                 │
│    ├─ Events: tool calls, findings, analysis     │
│    ├─ Memories: vuln patterns across targets     │
│    ├─ Knowledge: which techniques yield results  │
│    └─ Identity: Hunter's evolved methodology     │
│                                                  │
│  The Dreamer (background process) automatically  │
│  synthesises events → memories → knowledge       │
└─────────────────────────────────────────────────┘
```

### 4.2 Event Capture (Extract)

Both agents call `extract()` for every significant event:

```python
from elephantasm import extract, EventType

# Hunter — after finding a vulnerability
extract(
    EventType.SYSTEM,
    content="Found IDOR in /api/v2/users/{id} — user_id parameter "
            "not validated against session. Severity: High. Target: acme-api.",
    anima_id="hunter",
    session_id="hunt-2026-03-10-001",
    meta={"target": "acme-api", "cwe": "CWE-639", "severity": "high"},
    importance_score=0.9,
)

# Overseer — after an intervention
extract(
    EventType.SYSTEM,
    content="Hard intervention: added IDOR detection skill to Hunter. "
            "Commit abc123. Reason: Hunter missed 3 IDOR vulns in last 2 targets.",
    anima_id="overseer",
    session_id="overseer-loop-047",
    meta={"intervention_type": "hard", "commit": "abc123", "target_skill": "idor-hunting"},
)

# Hunter tool calls are captured automatically
extract(EventType.TOOL_CALL, "target_scan(target='acme-api', rules='owasp')", anima_id="hunter")
extract(EventType.TOOL_RESULT, '{"findings": 3, "severity": ["high", "medium", "low"]}', anima_id="hunter")
```

### 4.3 Memory Injection (Inject)

At the start of each iteration/session, agents call `inject()` to retrieve relevant context:

```python
from elephantasm import inject

# Overseer — get learned strategies before evaluating
pack = inject(anima_id="overseer", query="what intervention strategies have been effective?")
if pack:
    system_prompt += f"\n\n{pack.as_prompt()}"
    # Returns: memories of past interventions + knowledge like
    # "skill changes yield 40% improvement on average" or
    # "switching to lighter models during recon saves 30% budget without quality loss"

# Hunter — get relevant patterns before analysing a new target
pack = inject(anima_id="hunter", query="IDOR vulnerabilities in REST APIs with user endpoints")
if pack:
    system_prompt += f"\n\n{pack.as_prompt()}"
    # Returns: memories of similar vulns found before, techniques that worked,
    # knowledge like "check both /users/{id} and /users/me endpoints"

# Hunter — dedup check before reporting
pack = inject(anima_id="hunter", query="CVE-2024-XXXX acme-api auth bypass")
# If similar finding exists in knowledge, skip or note as potential duplicate
```

### 4.4 Observability

Elephantasm's dashboard provides real-time observability without custom infrastructure:

- **Event streams**: watch both agents' activity in real-time
- **Memory evolution**: see what the Dreamer is synthesising from raw events
- **Knowledge growth**: track what patterns the system is learning
- **Cross-agent visibility**: the Overseer queries the Hunter's Anima to evaluate performance; the human monitors both on the dashboard

This replaces the need for custom metrics tables, logging infrastructure, and performance dashboards.

### 4.5 What Elephantasm Replaces

| Originally Proposed | Now Handled By |
|---------------------|----------------|
| `hunter_metrics` SQLite table | Elephantasm events with structured `meta` fields |
| `interventions` SQLite table | Overseer Anima events + auto-synthesised memories |
| `findings` SQLite table | Hunter Anima events with CWE/severity metadata |
| Custom metrics collection in tool handlers | `extract()` calls in tool handlers |
| Overseer memory system (Phase 5) | Elephantasm's Dreamer + `inject()` |
| Cross-target learning | Hunter's Anima accumulates knowledge across all targets |
| Findings deduplication | `inject(query="...")` semantic search before reporting |
| Performance dashboards | Elephantasm dashboard |
| Intervention effectiveness analysis | Overseer `inject()` retrieves synthesised knowledge |

### 4.6 What SQLite Still Handles

Elephantasm handles memory and observability, but some operational state still lives in local SQLite:

- **Session persistence**: Hermes `SessionDB` for conversation history (needed for resume after redeploy)
- **Targets queue**: active targets, status (in-progress, completed, skipped)
- **Reports queue**: draft reports awaiting Overseer review / human approval
- **Budget tracking**: current spend, remaining budget, rate limits (needs to be local for real-time enforcement)

---

## 5. Communication & Control Channel

### 5.1 Runtime Injection Mechanism

The Overseer injects instructions into the Hunter via `ephemeral_system_prompt` — a prompt fragment appended at API-call time but never persisted to conversation history. This is the existing Hermes mechanism, repurposed:

```python
# Overseer writes to a shared file
Path(hunter_worktree / ".hermes" / "injections" / "current.md").write_text(
    "PRIORITY: The /api/v2/users endpoint accepts unsanitised user_id. "
    "Focus your next analysis on IDOR via this parameter."
)

# Hunter's modified prompt_builder reads this file each iteration
# and appends it as ephemeral_system_prompt
```

### 5.2 Interrupt & Redeploy Protocol

```
OVERSEER decides to redeploy:
  1. hunter_interrupt("Pausing for upgrade. Your state is saved.")
     → Sets Hunter's _interrupt_requested flag
     → Hunter finishes current tool, saves session, exits gracefully

  2. Wait for Hunter process to exit (poll process registry)

  3. Apply code changes to Hunter worktree
     → git add + commit in hunter/live branch

  4. hunter_spawn(resume_session=True)
     → Starts new Hunter process from updated code
     → Passes conversation_history from saved session
     → Hunter continues from where it left off, with new capabilities
```

### 5.3 Human Approval Flow

When the Overseer has a report ready for submission:

```
1. Overseer reviews the Hunter's report (quality, completeness, accuracy)
2. Overseer calls human_review tool:
   a. Displays report in terminal (CLI mode)
   b. Sends report summary via Telegram (using existing send_message tool)
   c. Waits for human response (using the existing approval pattern from tools/approval.py)
3. Human reviews and responds:
   - "approve" → Overseer submits via bounty_submit
   - "revise: [feedback]" → Overseer injects feedback, Hunter revises
   - "reject" → Report discarded, finding logged to Elephantasm
4. Result extracted to both Animas for learning
```

The Telegram path uses the existing gateway infrastructure — `send_message` tool for outbound, the approval pattern in `gateway/run.py` for waiting on responses.

---

## 6. Budget System

### 6.1 Budget Constraints

The human sets budget constraints that the Overseer must respect. Constraints are expressed as:

```yaml
# ~/.hermes/hunter-budget.yaml
budget:
  # Option A: daily rate
  max_per_day: 15.00       # USD
  currency: USD

  # Option B: total with minimum duration
  # max_total: 300.00
  # min_days: 5

  # Circuit breakers
  alert_at_percent: 80     # notify human when 80% spent
  hard_stop_at_percent: 100 # kill Hunter at 100%
```

### 6.2 Dynamic Adjustment

The budget file is a **watched config file**. The Overseer checks it at the start of each loop iteration. The human can modify it at any time via:

- Direct file edit (`vim ~/.hermes/hunter-budget.yaml`)
- CLI command: `hermes hunter budget set 20/day`
- Telegram message to the Overseer (future)

Changes take effect on the Overseer's next loop iteration (seconds to minutes).

### 6.3 Budget-Aware Model Selection

The Overseer manages model selection within budget constraints:

```
Budget status: $8.50 / $15.00 daily limit (57% used, 14 hours remaining)

Current allocation:
  Hunter main:    Qwen 3.5 32B (medium tier)  — $0.35/hr
  Subagents:      Qwen 3.5 7B (light tier)    — $0.08/hr each

Overseer decides:
  → "Recon phase complete, entering deep analysis. Switching Hunter to 72B."
  → "Budget running low — dropping subagents to 7B, keeping Hunter at 32B."
  → "High-value target identified — worth spending more. Staying on 72B."
```

---

## 7. Performance Metrics & Evaluation

### 7.1 The Only Metric That Matters

**High-quality vulnerability reports that are very likely to earn bounty payouts.**

Everything else is a supporting signal. The Overseer should optimise for $$$ per dollar spent.

### 7.2 Supporting Signals

These are tracked via Elephantasm events (structured `meta` fields) and help the Overseer make decisions:

**Efficiency:**
- Time per target (wall clock from clone to report)
- Cost per target (LLM spend)
- Dead-end ratio (abandoned analysis paths / total paths explored)

**Effectiveness:**
- Vulnerabilities found per target
- Severity distribution (critical/high/medium/low)
- True positive rate (confirmed vulns / reported vulns)
- Unique CWE coverage (breadth of vulnerability types found)

**Quality:**
- Report completeness (all required sections present?)
- PoC reliability (exploit works consistently?)
- Human approval rate (approved / submitted for review)
- Bounty acceptance rate (accepted by platform / submitted)

### 7.3 Metric Collection via Elephantasm

Instead of custom telemetry in tool handlers, metrics are captured as Elephantasm events:

```python
# In each Hunter tool handler
def handle_target_scan(args):
    start = time.time()
    result = run_scan(args)
    extract(
        EventType.TOOL_RESULT,
        content=f"target_scan completed: {len(result['findings'])} findings",
        anima_id="hunter",
        meta={
            "tool": "target_scan",
            "target_id": args["target_id"],
            "duration_s": time.time() - start,
            "findings_count": len(result["findings"]),
            "error": result.get("error"),
        },
    )
    return json.dumps(result)
```

The Dreamer automatically synthesises these into memories ("target_scan averages 45s per target", "semgrep finds 60% of our confirmed vulns") and knowledge the Overseer can query.

### 7.4 Intervention Tracking

The Overseer extracts its interventions as events. The Dreamer synthesises them into knowledge about what works:

```python
# After observing the impact of an intervention
extract(
    EventType.SYSTEM,
    content="Intervention int_047 result: adding IDOR skill increased "
            "vuln detection by 50% over next 3 targets. No regressions.",
    anima_id="overseer",
    meta={
        "intervention_id": "int_047",
        "type": "hard",
        "change": "Added IDOR detection skill",
        "commit": "abc123",
        "vulns_before": 1.2,
        "vulns_after": 1.8,
        "verdict": "improvement",
        "rolled_back": False,
    },
)
```

---

## 8. Code Evolution: What the Overseer Can Modify

The Overseer has write access to the Hunter's entire worktree. In practice, the most impactful modifications target these areas (ordered by frequency and safety):

### Tier 1: Skills (safest, most frequent)
- Create new `skills/security/*.md` files
- Improve existing skill content (better patterns, examples, edge cases)
- Add platform-specific guidance to skill frontmatter
- **Risk: None.** Skills are just text injected into the system prompt.

### Tier 2: Tool Parameters & Prompts
- Modify tool descriptions (what the LLM sees in the tool schema)
- Adjust tool parameter defaults or add new parameters
- Update the Hunter's system prompt in `prompt_builder.py`
- **Risk: Low.** Changes affect LLM behaviour but not execution logic.

### Tier 3: Tool Logic
- Modify tool handler implementations (e.g., improve `target_scan` to run additional semgrep rules)
- Add new tools to the Hunter's toolset
- Change tool orchestration in `model_tools.py`
- Modify subagent delegation strategy
- **Risk: Medium.** Code changes can introduce bugs. Requires testing.

### Tier 4: Agent Core
- Modify `run_agent.py` (iteration logic, context management)
- Change `context_compressor.py` (compression strategy)
- Alter `hermes_state.py` (persistence behaviour)
- **Risk: High.** Can break the entire Hunter. Overseer should be very cautious here and always have a rollback plan.

### Guardrails

The Overseer should follow these rules for code modifications:

1. **Always commit before modifying.** The Hunter's worktree must be clean before changes.
2. **One logical change per commit.** Small, atomic changes are easier to evaluate and rollback.
3. **Monitor for N iterations after deploying.** Don't stack changes — verify each one.
4. **Automatic rollback on crash.** If the Hunter crashes within 3 iterations of a redeploy, revert to the previous commit and redeploy.
5. **Never modify the Overseer's own code.** The Overseer's branch is read-only to itself.

---

## 9. Implementation Plan

### Phase 1: Foundation (Overseer ↔ Hunter IPC + Elephantasm)

**Goal:** Overseer can spawn, monitor, interrupt, and query a Hunter instance. Both agents connected to Elephantasm.

1. Create `hunter/` package in the Hermes repo
2. Implement `hunter/overseer.py` — the Overseer's main loop (subclass or wrapper of `AIAgent`)
3. Implement `hunter/control.py` — IPC layer:
   - `HunterProcess` class (wraps subprocess with I/O capture)
   - Injection file watcher
4. Implement Overseer tools: `hunter_spawn`, `hunter_kill`, `hunter_status`, `hunter_logs`, `hunter_inject`, `hunter_interrupt`
5. Integrate Elephantasm SDK:
   - Create Animas for Overseer and Hunter
   - Add `extract()` calls to both agents' tool dispatch
   - Add `inject()` to both agents' prompt builders
6. Create initial Overseer system prompt and skills
7. Set up git worktree management (create `hunter/live` branch)
8. Implement budget config file + watcher

**Deliverable:** Overseer can spawn a Hunter, watch its events via Elephantasm, inject runtime instructions, and respect budget constraints.

### Phase 2: Hunter Capabilities

**Goal:** Hunter can autonomously analyse a target and produce a vulnerability report, using both static and dynamic analysis.

1. Implement Hunter tools: `target_clone`, `target_scan`, `target_dast`, `attack_surface_map`, `vuln_assess`, `poc_build`, `poc_verify`, `report_draft`, `report_review`, `dedup_check`
2. Create initial security skills (`skills/security/`)
3. Create Hunter system prompt focused on methodical security analysis
4. Add Hunter toolset to `toolsets.py`
5. Implement subagent spawning for parallel analysis
6. Set up sandboxed execution environment for dynamic testing + PoC verification
7. Implement model routing layer (Overseer can switch Hunter's model)
8. End-to-end test: point Hunter at deliberately vulnerable repos (DVWA, Juice Shop), verify it finds known vulns

**Deliverable:** Hunter can be pointed at a target and produce a structured vulnerability report using both static and dynamic analysis.

### Phase 3: Code Evolution + Human Review

**Goal:** Overseer can modify the Hunter's code, redeploy, and present reports for human approval.

1. Implement `hunter_code_edit`, `hunter_code_read`, `hunter_diff`, `hunter_rollback`, `hunter_redeploy`
2. Implement the interrupt → modify → redeploy → monitor cycle
3. Implement automatic rollback on crash
4. Implement `human_review` tool:
   - Terminal display for CLI mode
   - Telegram notification via existing `send_message`
   - Approval flow using existing `tools/approval.py` pattern
5. Build Overseer evaluation loop (query Elephantasm for before/after comparison)

**Deliverable:** Overseer can autonomously identify a weakness, write a code fix, deploy it, and measure the impact. Reports go through human approval before submission.

### Phase 4: Bounty Integration

**Goal:** End-to-end bounty workflow from target discovery to report submission.

1. Implement `bounty_search` tool (HackerOne, Bugcrowd, Immunefi API integration — start with whichever has best API + payout potential)
2. Implement target selection logic (scope parsing, reward estimation, difficulty assessment)
3. Implement `bounty_submit` with mandatory human approval gate
4. Build report quality assessment (Overseer reviews Hunter's reports, uses Elephantasm memory of past successful reports)
5. Implement Overseer strategy for platform/target selection — optimise for highest expected $$$ value

**Deliverable:** Full pipeline from bounty discovery to submission-ready report. Platform selection driven by $$$ optimisation.

### Phase 5: Self-Improvement Loop

**Goal:** The system compounds improvements autonomously over time.

1. Overseer learns from its Elephantasm memory which intervention types, model selections, and strategies yield the best results
2. Cross-target learning: Hunter's Elephantasm memories from Target A inform analysis of Target B
3. Skill auto-generation: Overseer creates new skills from successful analysis patterns stored in Hunter's knowledge
4. Model selection optimisation: Overseer tracks $$$/dollar for each model tier and adjusts allocation
5. Subagent strategy refinement: Overseer analyses which delegation patterns are most effective

**Deliverable:** The system gets measurably better over time with minimal human intervention. Elephantasm's Dreamer handles the synthesis; the Overseer acts on it.

---

## 10. Deployment Architecture

### Development / Testing

```
Local machine:
  ├─ Overseer: hermes agent (main branch, local terminal backend)
  ├─ Hunter:   hermes agent (hunter/live worktree, Docker backend)
  │            ├─ Runs in container with: git, semgrep, python, node
  │            ├─ Can spin up target apps for dynamic testing
  │            └─ Subagents run in same or separate containers
  ├─ Local:    ~/.hermes/hunter-state.db (SQLite — sessions, targets, reports queue)
  ├─ Local:    ~/.hermes/hunter-budget.yaml (watched config)
  └─ Remote:   Elephantasm API (memory + observability)
```

### Production

```
Cloud:
  ├─ Overseer: Modal persistent container (or dedicated VM)
  │            └─ Has git access to Hunter's repo
  ├─ Hunter:   Modal sandbox (ephemeral, recreated on redeploy)
  │            ├─ Sandboxed execution for PoC testing
  │            └─ Subagents in separate Modal sandboxes
  ├─ Remote:   Elephantasm API (memory + observability)
  └─ Local:    Budget config (synced or API-managed)
```

### Why Docker/Modal for the Hunter?

1. **PoC isolation.** The Hunter builds and runs exploit code. This MUST happen in a sandbox.
2. **Dynamic testing.** Spinning up target applications requires a controlled environment with databases, configs, network isolation.
3. **Clean environment.** Each target analysis starts from a known-good state.
4. **Resource limits.** Prevent runaway processes from consuming host resources.
5. **Network control.** The Hunter should not be able to make arbitrary outbound requests during PoC testing (only to the sandboxed target).

---

## 11. Safety & Legal Guardrails

### Hard Constraints (Enforced in Code)

1. **No attacking live systems.** The Hunter only analyses source code and runs PoCs against local/sandboxed instances.
2. **Scope enforcement.** Before analysing a target, the Hunter must verify it's in-scope for the bounty program. Tool refuses to proceed if scope check fails.
3. **Human approval for submission.** The `bounty_submit` tool requires explicit human confirmation (terminal or Telegram) before sending any report to a platform.
4. **No credential harvesting.** Tools refuse to extract, store, or transmit credentials found in target code.
5. **Rate limiting.** Maximum N targets per day, M API calls per hour to bounty platforms.
6. **Budget enforcement.** Hard stop when budget is exhausted. No exceptions.
7. **Audit trail.** Every action by both agents is captured in Elephantasm with timestamps and metadata.

### Soft Constraints (Enforced via Prompt)

1. Follow responsible disclosure principles.
2. Never attempt to exploit vulnerabilities beyond what's needed for PoC.
3. Report findings even if unsure about severity — let the platform triage.
4. Respect program rules about disclosure timelines and communication channels.
5. Do not engage in social engineering, phishing, or physical security testing.

---

## 12. Leveraging Existing Hermes Infrastructure

| Existing Feature | How It's Used |
|-----------------|---------------|
| `AIAgent` class | Both Overseer and Hunter are `AIAgent` instances |
| `tool registry` | Hunter's security tools register via `registry.register()` |
| `skills/` system | Security skills loaded into Hunter's prompt automatically |
| `SessionDB` | Session persistence, targets queue, reports queue |
| `process_registry` | Hunter runs as a managed background process |
| `IterationBudget` | Independent budgets for Overseer and Hunter |
| `step_callback` | Overseer hooks into Hunter's iteration events |
| `tool_progress_callback` | Overseer monitors which tools Hunter is calling |
| `ephemeral_system_prompt` | Runtime injection mechanism for soft interventions |
| `_interrupt_requested` | Graceful Hunter shutdown for redeploy |
| `terminal` (Docker backend) | Sandboxed execution for PoC testing + dynamic analysis |
| `checkpoint_manager` | Filesystem snapshots before destructive Hunter operations |
| `context_compressor` | Handles long analysis sessions without context overflow |
| `delegate_task` | Hunter spawns subagents for parallel analysis |
| `send_message` (Telegram) | Overseer sends reports to human for review |
| `tools/approval.py` pattern | Human approval flow for report submission |
| **Elephantasm SDK** | Long-term memory + observability for both agents |

---

## 13. Resolved Design Decisions

These were the original open questions, now resolved:

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | In-process vs. separate? | **Separate process** | Code evolution requires it — must kill/restart Hunter independently |
| 2 | Single or multiple Hunters? | **One Hunter, unlimited subagents** | Hunter manages its own parallelism; Overseer refines strategy |
| 3 | Worktree vs. fork? | **Git worktree** (`hunter/live` branch) | Simpler, shared repo, easy branching |
| 4 | Budget model? | **Independent, time-based, dynamically adjustable** | Human sets constraints via watched config file |
| 5 | Static or dynamic? | **Fully dynamic** | As sophisticated as reasonably possible — spin up targets, fuzz, probe |
| 6 | Which LLM? | **Open-source models** (Qwen 3.5, Kimi K2.5) | Tiered (heavy/medium/light); Overseer selects within budget |
| 7 | Multi-language? | **Hunter/Overseer decide** | Start broad, let the system discover what it's good at |
| 8 | What's "good"? | **$$$ — reports that earn bounty payouts** | Everything else is a supporting signal |
| 9 | How aggressive? | **Self-regulating** | Overseer learns its own optimal cadence via Elephantasm memory |
| 10 | Self-modify own prompt? | **No** | Human-managed Overseer prompt, AI-managed Hunter code |
| 11 | Which platforms? | **Whatever maximises $$$** | Overseer decides; may start with one and expand |
| 12 | Open source only? | **Whatever maximises $$$** | No artificial constraints; go where the money is |
| 13 | Duplicate findings? | **Elephantasm memory** | `inject(query="...")` semantic search before reporting |
| 14 | Cost budget? | **Dynamically adjustable watched config** | `~/.hermes/hunter-budget.yaml`, editable at any time |
| 15 | Human in loop? | **Minimal — review reports only** | Overseer reviews first, then presents to human for approval |
| 16 | Observability? | **Elephantasm** | Dual-purpose: agentic memory + event stream monitoring |
