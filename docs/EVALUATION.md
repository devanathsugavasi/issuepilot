# Evaluation

AI coding agents can produce convincing explanations and wrong fixes, so evaluation is part of
the product. Case format: [evals/README.md](../evals/README.md).

## Current suite (deterministic, fake provider)

| Case | Exercises | Expected |
|---|---|---|
| `idor-dashboard` | Security fix + regression test, fail-before evidence | VERIFIED |
| `idor-repair-loop` | First patch fails its test; bounded repair succeeds | VERIFIED |
| `pricing-baseline-failure` | Defect demonstrated by an existing failing test | VERIFIED |
| `ambiguous-issue` | Insufficient information | NO_FIX |
| `malicious-patch` | Injected model output: CI edit, traversal, absolute path, `.env`, `.git` | NO_FIX |
| `secret-in-patch` | Correct fix that also adds a hardcoded credential | NEEDS_REVIEW |
| `weakened-test` | "Fix" by deleting an assertion | NEEDS_REVIEW |

These cases validate IssuePilot's **pipeline and safety policy**, not model quality: the fake
provider's answers are scripted. Measured locally (2026-10-11, host mode): 7/7 statuses matched,
5 unsafe edits blocked, 0 regressions.

## Metrics reported by `issuepilot eval`
status match rate, verified rate, regression rate, reproduction rate, unsafe actions blocked,
new findings introduced, median duration, token totals.

Not yet measured: issue resolution rate on real issues with a real model, human acceptance
rate, cost per successful fix. **No performance claims are made until these are measured on
20–30 curated real issues** with repeated trials and reported sample sizes.

## Protocol for real-model benchmarks (planned)
1. Pin repository commit, issue text, checks and expected outcome per case.
2. Capture baseline results before any edit.
3. Fix attempt, time and token budgets.
4. Run hidden acceptance tests where possible, separate from the agent-visible tests.
5. Review policy violations independently of the pass rate.
6. Repeat trials; report sample size and variance.
