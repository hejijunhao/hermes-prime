"""Overseer tools for managing the Hunter agent.

Tool modules in this package register themselves with the Hermes tool registry
at import time, following the standard pattern used by tools/*.py.

Modules:
    process_tools  – hunter_spawn, hunter_kill, hunter_status
    inject_tools   – hunter_inject, hunter_interrupt, hunter_logs
    code_tools     – hunter_code_edit, hunter_code_read, hunter_diff, hunter_rollback, hunter_redeploy
    budget_tools   – budget_status, hunter_model_set
"""
