# Intervention Strategy

## When to Intervene

### Do Nothing When:
- Hunter is making steady progress through a target
- Recent findings are legitimate and well-documented
- No errors or repeated failures in logs
- Budget usage is on track
- Recent intervention outcomes are positive — don't stack changes

### Soft Intervention (`hunter_inject`) When:
- Hunter is spending too long on one area without results — redirect focus
- Hunter missed an obvious attack vector visible in the logs
- A new target or priority has been identified
- Hunter's approach is correct but needs tactical refinement
- Report quality needs a nudge ("include CVSS score", "add remediation steps")

### Hard Intervention (code edit + redeploy) When:
- Hunter repeatedly fails at a specific vulnerability class — needs a new skill
- Report quality is consistently low — template or skill needs improvement
- A new analysis tool or capability would systematically improve performance
- Hunter's workflow ordering is inefficient — reorder phases or improve prompts
- Multiple soft interventions for the same issue haven't fixed it

### Model Change (`hunter_model_set`) When:
- Budget is running low but Hunter is in a phase that doesn't need heavy compute
- Hunter is entering deep analysis and would benefit from a heavier model
- Subagents are doing simple recon tasks on an expensive model
- Performance metrics show a specific model tier yields better results per dollar

## Intervention Sizing

From safest (most frequent) to riskiest (least frequent):

1. **Skill addition/edit** — Just Markdown text. No code changes. Do this first.
2. **System prompt tweak** — Changes how Hunter thinks, not what it can do. Low risk.
3. **Tool parameter change** — Modifies tool descriptions or defaults. Test mentally before deploying.
4. **Tool logic change** — Actual Python code. Keep changes small and targeted. Monitor closely.
5. **Core agent change** — Modifying `runner.py` or core loop. Highest risk. Only if absolutely necessary. Always have a rollback plan.

## Post-Intervention Monitoring

After any hard intervention:

1. **Watch the next 3–5 Hunter iterations closely** via `hunter_logs`
2. **Compare output quality before vs. after** — is the Hunter finding more vulns? Better reports? Fewer dead ends?
3. **If regression detected** — rollback immediately with `hunter_rollback` + `hunter_redeploy`. Don't try to fix forward.
4. **Record the outcome** — your Elephantasm memory automatically captures intervention results. Future iterations will benefit from knowing what worked and what didn't.
5. **Don't stack changes** — verify one intervention before making another. Stacking makes it impossible to attribute improvements or regressions.

## Common Anti-Patterns

- **Over-intervention**: changing things every iteration prevents the Hunter from building momentum. Let it run.
- **Thrashing**: alternating between two strategies without giving either one enough time. Pick one, monitor, then decide.
- **Large rewrites**: rewriting entire tool handlers or skills from scratch when a targeted edit would suffice.
- **Ignoring rollback**: pushing a second fix on top of a broken change instead of reverting first.
