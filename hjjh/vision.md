# Hermes Hunter — Vision

## The Idea

Turn the Hermes agent into an autonomous bug bounty hunter that finds legitimate, legal vulnerabilities in software and prepares detailed reports ready for submission to bounty platforms.

Rather than a single agent doing everything, the system is split into two:

1. **The Overseer (Master)** — the original agent, running on the main branch. It monitors, evaluates, and continuously improves the Hunter. It can intervene at runtime (prompt injection, steering, interrupts) or at the source-code level (rewriting tools, skills, and logic, then redeploying). It has full discretion to modify and redeploy the Hunter at any time.

2. **The Hunter (Worker)** — a clone of the repo running on a separate branch/worktree. It does the actual hunting: discovering targets, analysing code, identifying vulnerabilities, building PoCs, and drafting reports.

The Overseer treats the Hunter's entire codebase as mutable. When it spots inefficiencies, missed patterns, or repeated failures, it doesn't just tell the Hunter to try harder — it rewrites the code and deploys a better version.

Human review and approval is required before any report is submitted to a bounty platform.

---

## Feasibility Assessment

### Can an AI agent actually find bounty-worthy vulnerabilities?

**Yes — with caveats.**

### What agents are already good at

- **Static code analysis.** LLMs read code and spot patterns (missing input validation, broken auth, SQLi, path traversal, IDOR) better than most static analysis tools because they understand intent, not just syntax.
- **Systematic thoroughness.** An agent can review every endpoint, every parameter, every auth flow. Humans get bored and skip things. Agents don't.
- **Cross-file reasoning.** Understanding complex control flow across multiple files, inferring what *should* happen from documentation, then finding where the code doesn't do that.
- **Report writing.** LLMs produce clear, structured, well-evidenced vulnerability reports with reproduction steps. Report quality is a real differentiator on bounty platforms.
- **Dependency auditing.** Cross-referencing dependencies against known CVE databases at scale.

### What's hard but not impossible

- **Novel vulnerability classes.** High-value bounties ($10K+) often require creative reasoning: chaining multiple low-severity issues, finding business logic flaws unique to an application, or discovering attack vectors no one has considered. Current LLMs can do some of this but aren't consistently creative in the way top researchers are.
- **Dynamic testing.** Running applications, fuzzing inputs, observing runtime behaviour, timing side channels. Doable with terminal/browser tools, but requires complex per-target environment setup.
- **Application-specific business logic.** "Users shouldn't access other users' invoices" is obvious. "The discount code validation allows negative quantities, resulting in the merchant paying the customer" requires deep domain understanding.

### Real-world evidence

- **Google's Big Sleep (2024)** — An LLM agent found a real, previously unknown exploitable buffer overflow in SQLite. A zero-day in production software, found autonomously.
- **DARPA AIxCC (2024)** — AI systems competed to find and patch real vulnerabilities in critical infrastructure software. Multiple teams demonstrated autonomous vuln discovery.
- **Academic research** — Multiple papers show GPT-4/Claude-class models identify OWASP Top 10 vulnerabilities in realistic codebases with reasonable accuracy.
- **Industry adoption** — Semgrep, Snyk, and Socket are shipping LLM-augmented vulnerability detection that finds real bugs in production.

### The bounty market tiers

| Tier | Bounty Range | What It Takes | AI Feasibility |
|------|-------------|---------------|----------------|
| Low-hanging fruit | $100–$500 | Pattern matching (XSS, SQLi, open redirect) | **High** — but competitive, often already found |
| **Mid-tier** | **$500–$5,000** | **Auth bypasses, IDOR, privilege escalation, info disclosure** | **Medium-High — the sweet spot** |
| High-tier | $5,000–$50,000 | Logic flaws, chained exploits, novel attack vectors | Medium — possible with good tooling and iteration |
| Critical | $50,000+ | RCE, full account takeover, infrastructure compromise | Low-Medium — requires creativity agents are still developing |

**The mid-tier ($500–$5,000) is the realistic primary target.** These bugs require systematic analysis, not genius-level creativity. They're valuable enough to pursue but not so competitive that only elite researchers find them. This is exactly where **volume and thoroughness** (an agent's strengths) beat **individual brilliance**.

### Why the self-improving architecture is the key

A static agent will plateau. It will find some bugs on its first pass but quickly hit a ceiling. The Overseer architecture changes the equation:

1. Hunter v1 analyses a target — finds 2 vulns, misses 5
2. Overseer reviews the logs — identifies gaps in skill coverage, wrong analysis order, incomplete attack surface mapping
3. Overseer rewrites the Hunter's skills and tools, redeploys
4. Hunter v2 analyses the next target — finds 4 vulns, misses 3
5. Repeat. Compound improvement over time.

This learning loop is the difference between "maybe" and "yes." The real risk isn't whether AI can find bugs — it's whether it can find bugs **that haven't already been found** by the thousands of human researchers and scanners hitting the same targets. The self-improvement loop and the ability to develop novel analysis strategies is the competitive edge.

---

## Architecture

See [architecture.md](./architecture.md) for the full technical proposal.
