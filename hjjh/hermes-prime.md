# Hermes Prime — Vision & Architecture

## What This Is

An autonomous bug bounty hunting system built on the Nous Research Hermes Agent framework. Two AI agents work in hierarchy: a **Master** that builds, deploys, monitors, and continuously improves a **Hunter** that finds real software vulnerabilities and produces bounty-ready reports.

The Master treats the Hunter's entire codebase as mutable. When it spots inefficiencies, missed patterns, or repeated failures, it doesn't just steer — it rewrites code, adds skills, changes tools, and redeploys a better version. Over time, the Hunter gets measurably better at finding vulnerabilities, and the Master gets measurably better at improving the Hunter.

Human review and approval is required before any report is submitted to a bounty platform.

---

## The Thesis

### Can an AI agent find bounty-worthy vulnerabilities?

**Yes — with caveats.**

LLMs are already strong at static code analysis, systematic thoroughness, cross-file reasoning, dependency auditing, and report writing. They are weaker (but improving) at novel vulnerability classes, dynamic testing, and deep business logic understanding.

Evidence: Google's Big Sleep found a real zero-day in SQLite (2024). DARPA AIxCC teams demonstrated autonomous vulnerability discovery. Semgrep, Snyk, and Socket ship LLM-augmented vuln detection that finds real production bugs.

### Where the money is

| Tier | Range | AI Feasibility |
|------|-------|----------------|
| Low-hanging fruit | $100–$500 | High — but competitive, often already found |
| **Mid-tier** | **$500–$5,000** | **Medium-High — the sweet spot** |
| High-tier | $5,000–$50,000 | Medium — possible with good tooling |
| Critical | $50,000+ | Low-Medium — requires creativity agents are still developing |

**The mid-tier ($500–$5,000) is the primary target.** These bugs require systematic analysis — the Hunter's strength — not genius-level creativity. Volume and thoroughness beat individual brilliance here.

### Why self-improvement is the key

A static agent plateaus. It finds some bugs on its first pass but hits a ceiling. The Master architecture changes the equation:

1. Hunter v1 analyses a target — finds 2 vulns, misses 5
2. Master reviews the logs — identifies gaps in skills, wrong analysis order, incomplete attack surface mapping
3. Master rewrites skills and tools, redeploys
4. Hunter v2 analyses the next target — finds 4 vulns, misses 3
5. Repeat. Compound improvement over time.

The self-improvement loop is the competitive edge against thousands of human researchers and automated scanners hitting the same targets.

---

## The Hierarchy

```
Creator (You — the human)
  └→ Browser terminal / Telegram
       └→ Master (Fly Machine A — persistent, strategic)
            └→ tools / injection / code evolution
                 └→ Hunter (Fly Machine B — ephemeral, tactical, replaceable)
                      └→ subagents (parallel analysis workers)
```

Each level has full autonomy within constraints set by the level above:
- **Creator** sets budget, reviews reports, gives strategic direction
- **Master** controls everything about the Hunter — code, skills, model, targets, lifecycle
- **Hunter** controls its own analysis workflow and can spawn subagents freely

---

## Two-Agent Architecture

### The Master

A Hermes agent with a specialised mission: make the Hunter better at finding vulnerabilities. It does NOT hunt for vulnerabilities itself.

**What it does:**
- Monitors the Hunter's activity via logs and Elephantasm event streams
- Evaluates whether the Hunter is producing quality work
- Intervenes when it sees problems — soft (runtime injection) or hard (code changes + redeploy)
- Manages LLM model selection and budget allocation
- Learns from its own intervention history via Elephantasm memory

**Three intervention modes:**
1. **SOFT** — inject a runtime instruction. Tactical steering. Low risk, immediate effect.
2. **HARD** — modify Hunter source code, commit, push, redeploy. Systemic improvements. Medium risk.
3. **MODEL** — change the Hunter's LLM tier. Cost/quality optimization.

Always prefer the least invasive intervention. Soft before hard. Small changes before large rewrites.

### The Hunter

A Hermes agent with security analysis skills and (optionally) custom tools. Runs on a separate machine, analyses software for vulnerabilities, and produces structured reports.

**Per-target workflow:**
1. **Recon** — clone, read docs, map attack surface, identify tech stack, check dependencies
2. **Analysis** — static analysis (semgrep), manual code review of high-risk areas (auth, input validation, SQL, file handling, crypto, race conditions, business logic), dynamic testing where possible
3. **Verification** — build PoCs, test in sandbox, confirm exploitability, dedup check
4. **Reporting** — structured report with title, severity (CVSS), CWE, reproduction steps, PoC, impact, remediation

**Subagent strategy:**
The Hunter has full discretion to spawn subagents via `delegate_task`. Patterns include parallel recon per component, specialist analysis per vuln class, and parallel PoC building. The Master refines this strategy over time.

### Communication

**Runtime injection** — the Master pushes instructions into the Hunter's context via Elephantasm (preferred) or a shared injection file. The Hunter reads these each iteration and incorporates them as ephemeral guidance.

**Interrupt & redeploy** — the Master stops the Hunter, applies code changes, pushes to the Hunter's repo, and starts a fresh machine with updated code. Session state can be preserved across redeploys.

**Human approval** — when the Master has a report ready, it presents it to the Creator via browser terminal or Telegram. The Creator approves, requests revision, or rejects. This is a hard legal requirement.

---

## Infrastructure

### Two Fly.io Machines

```
┌──────────────────────────────────────────────┐
│  FLY MACHINE A — MASTER                      │
│                                              │
│  ttyd (browser terminal) + Hermes CLI        │
│  fly CLI, gh CLI, git, Python 3.11+          │
│  Persistent volume: /data                    │
│                                              │
│  State: budget config, spend ledger,         │
│  local clone of Hunter repo, Elephantasm     │
│  Anima cache, session DB                     │
│                                              │
│  Network: unrestricted outbound              │
└──────────────┬───────────────────────────────┘
               │  Fly Machines API + git push
┌──────────────┴───────────────────────────────┐
│  FLY MACHINE B — HUNTER                      │
│                                              │
│  Ephemeral — destroyed and recreated on      │
│  each redeploy. Boots by cloning the         │
│  Hunter repo and running the agent.          │
│                                              │
│  Tools: git, semgrep, node, Python           │
│  Network: restricted during PoC testing      │
│  No human access. Master is sole operator.   │
└──────────────────────────────────────────────┘
```

**Why two machines:** isolation (Hunter runs exploit code), independent lifecycle (Master kills/recreates Hunter freely), security boundary (restricted Hunter network), resource isolation (Hunter analysis doesn't affect Master responsiveness).

### Two Repositories

```
REPO 1: hermes-prime (Master's repo — read-only to the Master)
  The Hermes framework, Master infrastructure, this document.
  Only the Creator modifies this repo.

REPO 2: hermes-prime-hunter (Hunter's repo — starts EMPTY)
  Everything in here is written by the Master.
  Skills, tools, prompts, configs, Dockerfile.
  Git history = complete record of the Master's engineering decisions.
```

**Why two repos:** the Master cannot modify its own code (safety constraint). The Hunter repo IS the deliverable — a fully autonomous security agent built entirely by another agent. Independent deployment and CI.

### Elephantasm

Long-term memory and observability for both agents. Replaces the need for custom metrics/logging infrastructure.

Each agent gets its own **Anima** (isolated identity container):
- **hermes-prime** — the Master's memory: intervention history, strategy knowledge, what works and what doesn't
- **hermes-prime-hunter** — the Hunter's memory: vulnerability patterns, cross-target learning, analysis techniques

The **Dreamer** (Elephantasm background process) automatically synthesises raw events into memories and knowledge. The Master queries the Hunter's Anima to evaluate performance. Both agents call `inject()` to retrieve relevant context at the start of each session.

### Budget System

The Creator sets budget constraints (daily or total limits). The Master enforces them absolutely — hard stop means hard stop.

Budget-aware model selection:
- **Heavy tier** (72B) — novel vuln hunting, report writing, complex analysis
- **Medium tier** (32B) — standard code review, tool orchestration, PoC building
- **Light tier** (7B) — recon, dependency checks, subagent bulk work

The Master tracks spend in an append-only JSONL ledger, adjusts model tiers based on remaining budget, and alerts the Creator at configurable thresholds.

---

## Code Evolution — What the Master Can Modify

The Master has write access to the Hunter's entire repo. Ordered by frequency and safety:

| Tier | Target | Risk | Frequency |
|------|--------|------|-----------|
| 1 | **Skills** (Markdown in `skills/security/`) | None — just text | Most frequent |
| 2 | **Prompts & tool descriptions** | Low — affects LLM behaviour, not execution | Frequent |
| 3 | **Tool logic** (Python handlers) | Medium — code changes can introduce bugs | Moderate |
| 4 | **Agent core** (runner, context, state) | High — can break the entire Hunter | Rare |

**Guardrails:**
1. Always commit before modifying — clean worktree before changes
2. One logical change per commit — atomic, easy to evaluate and rollback
3. Monitor for 3–5 iterations after deploying — don't stack changes
4. Automatic rollback on regression — revert, don't fix forward
5. Never modify the Master's own code — read-only to itself

---

## The Self-Build Bootstrap

### The Core Insight

The Master's existing tools — file operations, terminal, git — are sufficient to build the Hunter from an empty repo. **Building** the Hunter and **improving** the Hunter are the same operation at different starting states.

### Bootstrap Sequence

```
Phase 0: EMPTY REPO
  │
  │  Master reads this document, understands the mission
  │
  ├─ Step 1: Write security skills (Markdown — zero risk, immediate value)
  ├─ Step 2: Write the Hunter system prompt (identity + methodology)
  ├─ Step 3: Write the Dockerfile and boot script
  ├─ Step 4: Deploy and test against a known-vulnerable target
  │          (Juice Shop, DVWA, WebGoat, crAPI)
  ├─ Step 5: Iterate — fix, improve, redeploy based on results
  │
  │  ── TRANSITION: Hunter can autonomously produce a finding ──
  │
  └─ Normal mode: continuous monitoring + improvement loop
```

**Transition criteria** — exit bootstrap when:
- Hunter has at least 5 security skills
- Hunter can clone a target, analyse it, and produce a structured finding
- At least one complete clone → analyse → report cycle verified

---

## The A/B Experiment — Prime vs Alpha

This system is being developed via two parallel paths to test a fundamental question: **is pre-built infrastructure worth the investment, or can a stock agent bootstrap everything it needs?**

### Path A: Hermes Prime (This Repo)

- **Master: Hermes Prime** — Hermes agent with purpose-built Phase 1 infrastructure: custom Overseer tools (`hunter_spawn`, `hunter_kill`, `hunter_inject`, `hunter_code_edit`, etc.), structured `BudgetTracker`, `WorktreeManager`, `HunterController`, `OverseerLoop`, Elephantasm integration layer, and CLI commands (`hermes hunter {status, spawn, kill, budget, logs}`)
- **Hunter: Hermes Hunter** — built and managed by Hermes Prime using its custom tooling
- **Development approach:** human-guided, with a backend abstraction layer being added for cloud deployment (local → Fly.io transition)
- **Advantages:** reliable budget enforcement, tested infrastructure (337 tests), structured tool APIs, deterministic process management, CLI for human monitoring
- **Disadvantages:** rigid tool API may constrain creative solutions, significant upfront engineering investment

### Path B: Hermes Alpha (Separate Instance)

- **Master: Hermes Alpha** — stock Hermes agent with zero custom code, given only `hjjh/overseer-blueprint.md` as its instruction manual
- **Hunter: Hermes Alpha Hunter** — built and managed by Hermes Alpha using stock Hermes tools (`terminal`, `read_file`, `write_file`, `execute_code`, `process`, `delegate_task`)
- **Development approach:** fully autonomous from first boot. The Master reads the blueprint, bootstraps the Hunter repo, deploys, and iterates without human engineering guidance.
- **Advantages:** maximum flexibility, tests the self-recursive thesis directly, zero engineering overhead
- **Disadvantages:** no safety net — budget tracking is ad-hoc, process management relies on LLM remembering the right shell commands, no rollback infrastructure

### What We're Measuring

| Signal | Path A (Prime) | Path B (Alpha) |
|--------|----------------|----------------|
| Time to first functional Hunter | ? | ? |
| Time to first real vulnerability finding | ? | ? |
| Hunter reliability (crashes, stuck loops) | ? | ? |
| Budget adherence (overspend incidents) | ? | ? |
| Quality of Hunter code (maintainability, correctness) | ? | ? |
| Master intervention effectiveness | ? | ? |
| Adaptability to novel problems | ? | ? |

The winner informs the long-term architecture: do we invest in more infrastructure (Phase 1 approach) or strip it back and let the agent improvise (blueprint approach)?

---

## Feedback Loops

The system operates four nested feedback loops at different timescales:

```
Loop 1: TACTICAL (seconds–minutes)
  Hunter analyses code → finds/misses vulnerability
  → Elephantasm captures event → Master reads on next iteration
  → Master injects guidance → Hunter adjusts

Loop 2: STRUCTURAL (minutes–hours)
  Master notices Hunter repeatedly misses a vuln class
  → Writes a new skill or tool → Commits, pushes, redeploys
  → Hunter gains new capability → Master monitors impact

Loop 3: STRATEGIC (hours–days)
  Master's Elephantasm memory accumulates intervention outcomes
  → Dreamer synthesises: "skill additions help 40%, model switches
    during analysis cause context loss, recon doesn't need heavy models"
  → Master's inject() retrieves this knowledge → strategy evolves

Loop 4: META-STRATEGIC (days–weeks)
  Creator reviews dashboards, reports, bounty outcomes
  → Talks to Master: "Pivot to Go projects. Write a race condition skill."
  → Master acts on strategic direction
  → A/B experiment results inform which path to invest in
```

---

## Safety & Legal Guardrails

### Hard Constraints (Never Violate)

1. **No attacking live systems.** Source code analysis and sandboxed PoC only. Never probe, scan, or exploit production.
2. **Scope enforcement.** Verify every target is in-scope for its bounty program before analysis.
3. **Human approval for submission.** No report goes to any platform without Creator approval.
4. **No credential harvesting.** Never extract, store, or transmit credentials found in targets.
5. **Budget enforcement.** Hard stop is absolute. No exceptions.
6. **Master cannot modify its own code.** Only the Creator changes the Master's codebase.
7. **Audit trail.** Every significant action captured in Elephantasm.

### Soft Constraints

1. Responsible disclosure principles.
2. Never exploit beyond PoC necessity.
3. Report findings even if unsure about severity.
4. Respect program rules and disclosure timelines.
5. No social engineering, phishing, or physical security testing.

---

## Success Criteria

### Short Term (First Week)
- Hunter can clone, analyse, and produce a structured finding against a test target
- At least 5 security skills deployed
- Budget tracking functional
- Master can reliably deploy, monitor, and redeploy the Hunter

### Medium Term (First Month)
- Findings produced against real bounty targets
- At least one report submitted (with Creator approval)
- Elephantasm memory contains useful strategy knowledge
- Skills and tools iterated based on real-world performance

### Long Term (3+ Months)
- At least one bounty payout earned
- Hunter measurably better than at bootstrap
- Cross-target learning operational
- Master mostly monitoring, rarely intervening
- Hunter repo git log tells a coherent story of systematic improvement

### Break-Even Target
At ~$500–600/month operating cost ($15/day LLM budget + Fly.io compute), the system needs roughly one $500–$1,000 bounty per month to break even, or one $5,000 bounty every 6–12 months to be highly profitable.

---

## Human Setup Checklist

Everything below must be done by the Creator before the system can operate.

### Accounts and API Keys

- [ ] **Fly.io** — account with billing enabled, API token via `fly tokens create`
- [ ] **GitHub** — account with Personal Access Token (`repo` scope)
- [ ] **Elephantasm** — account with API key
- [ ] **LLM provider** — OpenRouter recommended (API key from openrouter.ai)
- [ ] **Telegram bot** (optional) — via @BotFather, get bot token and chat ID

### Fly.io Infrastructure

- [ ] Install fly CLI: `curl -L https://fly.io/install.sh | sh`
- [ ] Authenticate: `fly auth login`
- [ ] Create Master app: `fly apps create hermes-prime`
- [ ] Create Hunter app: `fly apps create hermes-prime-hunter`
- [ ] Create persistent volume: `fly volumes create prime_data --app hermes-prime --size 10 --region <region>`
- [ ] Set Master secrets:
  ```bash
  fly secrets set -a hermes-prime \
    AUTH_PASSWORD="<browser-terminal-password>" \
    FLY_API_TOKEN="<fly-token>" \
    GITHUB_PAT="<github-pat>" \
    GITHUB_USER="<github-username>" \
    ELEPHANTASM_API_KEY="<elephantasm-key>" \
    OPENROUTER_API_KEY="<openrouter-key>" \
    TELEGRAM_BOT_TOKEN="<bot-token>" \
    TELEGRAM_CHAT_ID="<chat-id>"
  ```
- [ ] Set Hunter secrets:
  ```bash
  fly secrets set -a hermes-prime-hunter \
    ELEPHANTASM_API_KEY="<elephantasm-key>" \
    OPENROUTER_API_KEY="<openrouter-key>" \
    GITHUB_PAT="<github-pat>"
  ```

### Build and Deploy the Master

- [ ] Write and build `Dockerfile.prime` (Hermes + ttyd + fly CLI + gh CLI + this document)
- [ ] Write `fly.toml` (HTTP on 8080, persistent volume at `/data`, shared-cpu-2x, 1GB RAM)
- [ ] Deploy: `fly deploy --app hermes-prime`
- [ ] Verify: open `https://hermes-prime.fly.dev`, log in

### For the Alpha Path (Path B)

- [ ] Create Alpha Master app: `fly apps create hermes-alpha`
- [ ] Create Alpha Hunter app: `fly apps create hermes-alpha-hunter`
- [ ] Create persistent volume: `fly volumes create alpha_data --app hermes-alpha --size 10 --region <region>`
- [ ] Set Alpha secrets (same pattern as above, different app names)
- [ ] Deploy stock Hermes with `hjjh/overseer-blueprint.md` baked in
- [ ] First instruction: *"Read /app/hjjh/overseer-blueprint.md. This is your mission. Begin the bootstrap sequence."*

### First Interaction (Both Paths)

- [ ] Open browser terminal
- [ ] Set initial budget: `hermes hunter budget set 15/day` (Prime) or tell Alpha to configure budget
- [ ] Give the first strategic directive or let bootstrap proceed autonomously
- [ ] Monitor, compare, learn
