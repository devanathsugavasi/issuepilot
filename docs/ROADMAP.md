# Roadmap

## v0.1 — local issue solving (current, pre-release)
- [x] CLI: init, doctor, plan, run, report, diff, security, eval
- [x] State machine, retry budget, evidence-derived status
- [x] Isolated clone workspace, patch policy, integrity check
- [x] Docker sandbox; opt-in unisolated host mode
- [x] Anthropic adapter (structured outputs); deterministic fake provider
- [x] Built-in secret scan; Gitleaks/Semgrep adapters; test-weakening detection
- [x] JSON/Markdown reports; 7 deterministic eval cases
- [ ] Solve one real, reproducible issue with a real model and publish the report
- [ ] First tagged release

## v0.2 — reliability and evidence
- Dependency vulnerability checks (e.g. pip-audit, npm audit) with an explicit network policy
- Better context retrieval (symbol index, test-to-source mapping)
- Structured run logs; cost accounting per run
- 20–30 curated real-issue benchmark cases

## v0.3 — GitHub
- Narrowly scoped GitHub App or token integration
- Label-triggered runs, branch + draft PR with the report attached
- Human approval required; never auto-merge; tokens never exposed to sandboxed code

## v0.4+
- Additional providers, language adapters, CI integrations, optional dashboard

## Good first issues
- Add a Node.js/TypeScript fixture case to `evals/cases`
- Add `pip-audit` scanner adapter with normalization tests
- `issuepilot runs` command to list previous runs
