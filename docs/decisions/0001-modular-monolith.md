# ADR 0001: Modular monolith CLI

**Status:** accepted · 2026-10-11

## Context
The MVP must work locally, be easy to install and audit, and keep issue parsing, orchestration,
patching, execution, verification and reporting separate.

## Decision
One Python package with single-responsibility modules, a Typer CLI, Pydantic schemas and no
server, database or message queue. The orchestrator is the only component that sequences work.

## Consequences
Simple install (`pipx`), whole workflow testable in-process with a fake provider. Concurrency and
persistent job history are deferred; GitHub automation (v0.3) will reuse the orchestrator.
