# Hermes Prime — Introduction

## What This Is

Hermes Prime is an autonomous bug bounty hunting system built as a two-agent hierarchy on top of the Nous Research Hermes Agent framework. A persistent **Master/Overseer** agent manages an ephemeral **Hunter** agent — the Master doesn't hunt for vulnerabilities itself, but instead continuously monitors, evaluates, and improves the Hunter's code, skills, and configuration. The Hunter analyses open-source targets for security vulnerabilities (focusing on the mid-tier $500–$5K bounty sweet spot), produces structured reports, and queues them for human approval before submission. The key thesis is that **self-improvement is the competitive edge** — a static scanner plateaus, but a Master that learns which interventions work (via Elephantasm long-term memory) compounds improvements over time.

The infrastructure runs on **two Fly.io machines** — the Overseer on an always-on machine with a persistent volume and browser terminal, the Hunter on ephemeral machines that clone the latest code at boot and self-destruct on exit. The Hunter's entire repo starts empty and is built by the Master, making "bootstrapping" and "improving" the same operation at different starting states.

## Key Architectural Elements

- **Three intervention modes**: soft (runtime injection), hard (code edit + redeploy), model (LLM tier switch) — always preferring least-invasive
- **Elephantasm** for long-term memory and observability, replacing custom metrics/logging infrastructure
- **Budget system** with daily/total limits, append-only JSONL ledger, and tiered open-source model selection (7B/32B/72B)
- **A/B experiment** — Hermes Prime (engineered infrastructure, 337+ tests, custom tools) vs Hermes Alpha (stock Hermes agent given only a blueprint document) to test whether pre-built infrastructure or agent improvisation wins
- **Phase 1 is complete** (v5.1.0) — the full Overseer tool suite, backend abstraction (local + Fly.io), bootstrap mode, deployment artifacts, and 113+ tests are all in place. The system is ready for first deployment.
