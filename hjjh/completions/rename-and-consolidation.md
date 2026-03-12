# Rename & Vision Consolidation — Completion Report

## Context

During a design review, we identified that:

1. The stock Hermes agent already has every primitive needed to operate as an Overseer (terminal, file ops, process management, delegate_task, ephemeral_system_prompt, interrupt handling, skills). The Phase 1 infrastructure we built is an optimization — reliable, tested, deterministic — but not a prerequisite.

2. This insight led to an **A/B experiment**: run two parallel paths to the same goal and see which produces a better Hunter.

3. The project needed distinct names for four agents across two paths, and the vision was spread across three separate documents.

---

## What Changed

### 1. Project Rename: Hermes Hunter → Hermes Prime

The repo identity is now **Hermes Prime** — the engineered, human-guided path (Path A) with purpose-built Phase 1 infrastructure.

**Files modified:**

| File | Change |
|------|--------|
| `hunter/config.py:90` | Comment: `"hermes-hunter"` → `"hermes-prime"` |
| `hunter/config.py:106-107` | `OVERSEER_ANIMA_NAME = "hermes-prime"`, `HUNTER_ANIMA_NAME = "hermes-prime-hunter"` |
| `tests/test_hunter_memory.py` | All `"hermes-overseer"` → `"hermes-prime"`, all `"hermes-hunter"` → `"hermes-prime-hunter"` (lines 75, 82, 89-90, 94-95, 101, 112-113) |

### 2. A/B Experiment Naming Convention

| Role | Path A (Guided/Structured) | Path B (Autonomous/Stock) |
|------|---------------------------|--------------------------|
| Master | **Hermes Prime** | **Hermes Alpha** |
| Hunter | **Hermes Hunter** | **Hermes Alpha Hunter** |
| Fly app (Master) | `hermes-prime` | `hermes-alpha` |
| Fly app (Hunter) | `hermes-prime-hunter` | `hermes-alpha-hunter` |
| Elephantasm anima (Master) | `hermes-prime` | `hermes-alpha` |
| Elephantasm anima (Hunter) | `hermes-prime-hunter` | `hermes-alpha-hunter` |
| GitHub repo (Hunter) | `hermes-prime-hunter` | `hermes-alpha-hunter` |

### 3. Consolidated Vision Document

**Created: `hjjh/hermes-prime.md`**

Single source of truth for the project vision and architecture, consolidating content from `vision.md`, `architecture.md`, and `self-recursive-deployment.md` into one document. Sections:

| Section | Content |
|---------|---------|
| The Thesis | Why AI bug bounty works, market tiers, self-improvement as competitive edge |
| The Hierarchy | Creator → Master → Hunter → subagents |
| Two-Agent Architecture | Master role (meta-agent), Hunter role (security analyst), communication (injection, interrupt, redeploy), human approval |
| Infrastructure | Two Fly machines, two repos, Elephantasm integration, budget system |
| Code Evolution | Four-tier modification strategy (skills → prompts → tool logic → agent core), guardrails |
| The Self-Build Bootstrap | Core insight (building = improving at different starting states), step-by-step sequence, transition criteria |
| The A/B Experiment | Prime vs Alpha, what each path provides, what we're measuring |
| Feedback Loops | Four nested loops (tactical → structural → strategic → meta-strategic) |
| Safety & Legal | Hard constraints + soft constraints |
| Success Criteria | Short/medium/long term milestones, break-even target |
| Human Setup Checklist | Accounts, Fly infrastructure, Docker, deployment steps for both paths |

### 4. Alpha Blueprint

**Renamed: `hjjh/overseer-blueprint.md` → `hjjh/alpha-blueprint.md`**

Updated all internal references to use Alpha naming:
- Fly apps: `hermes-alpha`, `hermes-alpha-hunter`
- Elephantasm animas: `hermes-alpha`, `hermes-alpha-hunter`
- GitHub repos: `hermes-alpha-hunter`
- Persistent volume: `alpha_data`
- Title: "Hermes Alpha — Overseer Blueprint"
- Self-references: `alpha-blueprint.md`

This is the instruction manual given to a stock Hermes agent for Path B. It contains everything the Alpha Master needs to bootstrap and operate the system with zero custom code.

---

## File Inventory After Changes

### `hjjh/` Directory

| File | Purpose | Status |
|------|---------|--------|
| `hermes-prime.md` | Consolidated vision & architecture | **NEW** |
| `alpha-blueprint.md` | Instruction manual for Hermes Alpha (Path B) | **NEW** (renamed from overseer-blueprint.md) |
| `vision.md` | Original vision document | Legacy (superseded by hermes-prime.md) |
| `architecture.md` | Original detailed architecture | Legacy (still useful for deep reference) |
| `self-recursive-deployment.md` | Cloud deployment plan with implementation phases | Active (Path A continues from here) |
| `plans/phase1-implementation.md` | Phase 1 task breakdown | Complete |
| `completions/phase-a-backend-abstraction.md` | Phase A completion report | Complete |
| `completions/rename-and-consolidation.md` | This file | Complete |

### Code Changes

| File | Lines Changed | Nature |
|------|---------------|--------|
| `hunter/config.py` | 3 | Anima name constants + comment |
| `tests/test_hunter_memory.py` | ~10 | Test fixture data (string replacements) |

---

## Test Results

- **42/42 memory tests pass** (verified anima name renames)
- **3174 passed, 2 failed, 5 skipped** (full suite — 2 failures are pre-existing: `test_timezone.py`, `test_vision_tools.py`)
- Zero regressions from rename

---

## Design Decisions Made

### Why "Prime" and "Alpha"?
- **Prime** = the primary, engineered path. Purpose-built infrastructure, human-guided development.
- **Alpha** = the experimental, autonomous path. Stock tools, LLM improvisation, tests whether pre-built infrastructure is necessary.

### Why consolidate the docs?
The vision was spread across three files (vision.md, architecture.md, self-recursive-deployment.md) totalling ~900 lines. The consolidated `hermes-prime.md` provides a single entry point that covers the full picture without requiring cross-referencing. The original docs are preserved for deep reference.

### Why rename the blueprint?
The blueprint is specifically for the Alpha path (Path B). Naming it `alpha-blueprint.md` makes it immediately clear which agent reads it and prevents confusion between the two paths.

---

## What's Next

- **Path A (this repo):** Continue with `self-recursive-deployment.md` Phase B (Fly.io remote backend) or Phase C (browser terminal + deployment)
- **Path B (separate):** Deploy a stock Hermes agent with `alpha-blueprint.md` and let it bootstrap autonomously
- **Both paths:** Compare results to determine whether purpose-built infrastructure (Prime) or stock-tool improvisation (Alpha) produces a better Hunter
