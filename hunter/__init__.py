"""Hermes Hunter — autonomous bug bounty hunting system.

A two-agent system where an Overseer (Master) continuously improves a Hunter
(Worker) that finds legitimate software vulnerabilities for bug bounty submission.

Modules:
    config      – Paths, constants, and defaults for the Hunter subsystem
    budget      – Budget config loading, watching, and enforcement
    worktree    – Git worktree management for the Hunter's codebase
    control     – Hunter process lifecycle (spawn, kill, poll, redeploy)
    memory      – Elephantasm integration for long-term agentic memory
    overseer    – The Overseer's main control loop
    tools/      – Overseer tools registered with the Hermes tool registry
"""

__version__ = "0.1.0"
