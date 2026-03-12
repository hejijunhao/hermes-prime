# Budget Management

## Model Tier Selection

Choose the model tier based on the Hunter's current phase:

| Phase | Recommended Tier | Rationale |
|-------|-----------------|-----------|
| Recon (cloning, doc reading, listing files) | Light (7B) | Low reasoning needed, high volume |
| Attack surface mapping | Medium (32B) | Some analytical reasoning |
| Static analysis interpretation | Medium–Heavy | Complex multi-file reasoning |
| Novel vulnerability hunting | Heavy (72B) | Maximum capability needed |
| PoC building | Medium (32B) | Mostly code generation |
| Report writing | Heavy (72B) | Quality is the differentiator |
| Subagent bulk tasks | Light (7B) | Parallel + cheap |

## Budget Strategies

### Comfortable (< 50% used)
- Use heavy model for Hunter main process
- Medium for subagents
- Don't optimize for cost — focus on quality
- Explore new targets freely

### Cautious (50–80% used)
- Drop subagents to light tier
- Keep Hunter on medium unless in deep analysis or report writing
- Start being selective about targets — prioritize high-reward programs
- Finish current targets before starting new ones

### Critical (> 80% used)
- Switch Hunter to medium tier
- Subagents on light tier only
- Focus exclusively on finishing current target and writing reports
- Do NOT start new targets
- Consider whether remaining budget is better spent on polishing existing reports than hunting new vulnerabilities
- If budget alert fires, notify via logs and consider pausing

## Cost Tracking

The `budget_status` tool shows:
- Current spend vs. daily/total limit
- Percentage used and remaining dollars
- Recent spend entries (last 5) for trend analysis
- Daily breakdown for historical view

Check budget at the start of each iteration. If approaching the alert threshold (80%), proactively switch to lighter models before the hard stop forces a kill.
