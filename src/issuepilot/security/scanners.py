"""Scanner adapters and finding normalization.

Scanners read files; they do not execute repository code, so they run on the host against
the isolated workspace. A scanner finding is only ever `scanner_reported` — it is never
upgraded or suppressed based on model opinion.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path

from issuepilot.config import SecurityConfig
from issuepilot.schemas import Finding, FindingStatus, ScannerRun
from issuepilot.security.redact import SECRET_PATTERNS, redact, truncate

SCANNER_TIMEOUT_S = 600
_SEVERITY_MAP = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}


def _fid(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def scan_text_for_secrets(
    text: str, file: str | None, line_offset: int = 1, source: str = "builtin-secrets"
) -> list[Finding]:
    findings = []
    for lineno, line in enumerate(text.splitlines(), start=line_offset):
        for name, pattern in SECRET_PATTERNS:
            if name == "private-key":
                hit = "PRIVATE KEY-----" in line and "BEGIN" in line
            else:
                hit = bool(pattern.search(line))
            if hit:
                findings.append(
                    Finding(
                        id=_fid(source, name, file, line.strip()),
                        source=source,
                        rule_id=name,
                        severity="high",
                        file=file,
                        line_start=lineno,
                        line_end=lineno,
                        evidence=truncate(redact(line.strip()), 200),
                        confidence="medium",
                        status=FindingStatus.SCANNER_REPORTED,
                        remediation="Remove the credential, rotate it, and load it from the environment.",
                    )
                )
                break
    return findings


def normalize_gitleaks(data: list[dict], root: Path) -> list[Finding]:
    out = []
    for item in data:
        file = _rel(item.get("File"), root)
        rule = str(item.get("RuleID", "gitleaks"))
        line = item.get("StartLine")
        # Never keep the raw secret: gitleaks' `Secret`/`Match` fields are discarded.
        out.append(
            Finding(
                id=_fid("gitleaks", rule, file, item.get("Fingerprint", line)),
                source="gitleaks",
                rule_id=rule,
                severity="high",
                file=file,
                line_start=line,
                line_end=item.get("EndLine"),
                evidence=f"{item.get('Description', rule)} (value redacted)",
                confidence="medium",
                status=FindingStatus.SCANNER_REPORTED,
                remediation="Remove and rotate the credential.",
            )
        )
    return out


def normalize_semgrep(data: dict, root: Path) -> list[Finding]:
    out = []
    for r in data.get("results", []):
        extra = r.get("extra", {})
        file = _rel(r.get("path"), root)
        rule = str(r.get("check_id", "semgrep"))
        lines = str(extra.get("lines", "")).strip()
        out.append(
            Finding(
                id=_fid("semgrep", rule, file, lines),
                source="semgrep",
                rule_id=rule,
                severity=_SEVERITY_MAP.get(str(extra.get("severity", "")).upper(), "unknown"),
                file=file,
                line_start=r.get("start", {}).get("line"),
                line_end=r.get("end", {}).get("line"),
                evidence=truncate(redact(extra.get("message", "") + (f"\n{lines}" if lines else "")), 400),
                confidence=str(extra.get("metadata", {}).get("confidence", "medium")).lower(),
                status=FindingStatus.SCANNER_REPORTED,
                remediation=extra.get("fix") or None,
            )
        )
    return out


def _rel(path: object, root: Path) -> str | None:
    if not path:
        return None
    p = Path(str(path))
    try:
        return p.resolve().relative_to(root.resolve()).as_posix() if p.is_absolute() else p.as_posix()
    except ValueError:
        return p.name


def run_gitleaks(root: Path) -> tuple[ScannerRun, list[Finding]]:
    if shutil.which("gitleaks") is None:
        return ScannerRun(scanner="gitleaks", phase="", ran=False, detail="gitleaks not installed"), []
    with tempfile.TemporaryDirectory(prefix="issuepilot-gl-") as tmp:
        report = Path(tmp) / "r.json"
        proc = subprocess.run(
            [
                "gitleaks",
                "detect",
                "--no-git",
                "--source",
                str(root),
                "--report-format",
                "json",
                "--report-path",
                str(report),
                "--exit-code",
                "0",
                "--no-banner",
                "--redact",
            ],
            capture_output=True,
            text=True,
            timeout=SCANNER_TIMEOUT_S,
            check=False,
        )
        if proc.returncode != 0 or not report.exists():
            return ScannerRun(
                scanner="gitleaks", phase="", ran=False, detail=f"gitleaks error: {redact(proc.stderr.strip())[:300]}"
            ), []
        data = json.loads(report.read_text() or "[]")
    return ScannerRun(scanner="gitleaks", phase="", ran=True, detail=f"{len(data)} result(s)"), normalize_gitleaks(
        data, root
    )


def run_semgrep(root: Path, config: str) -> tuple[ScannerRun, list[Finding]]:
    if shutil.which("semgrep") is None:
        return ScannerRun(scanner="semgrep", phase="", ran=False, detail="semgrep not installed"), []
    proc = subprocess.run(
        ["semgrep", "scan", "--config", config, "--json", "--quiet", "--metrics", "off", str(root)],
        capture_output=True,
        text=True,
        timeout=SCANNER_TIMEOUT_S,
        check=False,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return ScannerRun(
            scanner="semgrep",
            phase="",
            ran=False,
            detail=f"semgrep error (exit {proc.returncode}): {redact(proc.stderr.strip())[:300]}",
        ), []
    return ScannerRun(
        scanner="semgrep", phase="", ran=True, detail=f"{len(data.get('results', []))} result(s)"
    ), normalize_semgrep(data, root)


def scan_tree(root: Path, cfg: SecurityConfig, files: Iterable[str]) -> tuple[list[ScannerRun], list[Finding]]:
    runs: list[ScannerRun] = []
    findings: list[Finding] = []
    if cfg.builtin_secrets:
        count = 0
        for rel in files:
            p = root / rel
            if not p.is_file() or p.is_symlink() or p.stat().st_size > 2_000_000:
                continue
            raw = p.read_bytes()
            if b"\0" in raw:
                continue
            count += 1
            findings.extend(scan_text_for_secrets(raw.decode("utf-8", "replace"), rel))
        runs.append(ScannerRun(scanner="builtin-secrets", phase="", ran=True, detail=f"{count} file(s) scanned"))
    for enabled, runner in (
        (cfg.gitleaks, lambda: run_gitleaks(root)),
        (cfg.semgrep, lambda: run_semgrep(root, cfg.semgrep_config)),
    ):
        if enabled:
            run, found = runner()
            runs.append(run)
            findings.extend(found)
    return runs, findings


def missing_required(runs: list[ScannerRun], cfg: SecurityConfig) -> list[str]:
    if not cfg.require_scanners:
        return []
    return [r.scanner for r in runs if not r.ran]


def compare(baseline: list[Finding], candidate: list[Finding]) -> list[Finding]:
    """Mark candidate findings that are new, and baseline findings no longer reported."""
    base_ids = {f.id for f in baseline}
    cand_ids = {f.id for f in candidate}
    merged: list[Finding] = []
    for f in candidate:
        merged.append(f.model_copy(update={"introduced_by_patch": f.id not in base_ids}))
    for f in baseline:
        if f.id not in cand_ids:
            merged.append(f.model_copy(update={"introduced_by_patch": False, "resolved_in_candidate": True}))
    return merged
