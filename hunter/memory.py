"""Elephantasm integration — long-term agentic memory for both agents.

Provides OverseerMemoryBridge and HunterMemoryBridge as clean wrappers
around the Elephantasm SDK. Both agents use extract() to capture events
and inject() to retrieve relevant memory context.

All Elephantasm calls are non-fatal — if the API is down, agents continue
without memory context.

Implementation: Task 5.
"""

# Stub — implemented in Task 5
