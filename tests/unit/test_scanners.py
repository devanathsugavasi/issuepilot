from pathlib import Path

from issuepilot.config import SecurityConfig
from issuepilot.schemas import FindingStatus
from issuepilot.security import scanners


def test_normalize_gitleaks_drops_secret(tmp_path: Path):
    data = [
        {
            "RuleID": "aws-access-token",
            "File": str(tmp_path / "a.py"),
            "StartLine": 3,
            "EndLine": 3,
            "Secret": "AKIAABCDEFGHIJKLMNOP",
            "Match": "key=AKIAABCDEFGHIJKLMNOP",
            "Description": "AWS key",
            "Fingerprint": "fp",
        }
    ]
    [f] = scanners.normalize_gitleaks(data, tmp_path)
    assert f.file == "a.py" and f.line_start == 3 and f.status == FindingStatus.SCANNER_REPORTED
    assert "AKIA" not in f.model_dump_json()


def test_normalize_semgrep(tmp_path: Path):
    data = {
        "results": [
            {
                "check_id": "python.sqli",
                "path": "app/db.py",
                "start": {"line": 4},
                "end": {"line": 5},
                "extra": {
                    "severity": "ERROR",
                    "message": "SQL injection",
                    "lines": "q = f'..'",
                    "metadata": {"confidence": "HIGH"},
                },
            }
        ]
    }
    [f] = scanners.normalize_semgrep(data, tmp_path)
    assert (f.severity, f.confidence, f.file, f.rule_id) == ("high", "high", "app/db.py", "python.sqli")


def test_builtin_scan_and_compare(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\n")
    base_runs, base = scanners.scan_tree(tmp_path, SecurityConfig(), ["a.py"])
    (tmp_path / "b.py").write_text('API_KEY = "abcdefghijkl1234"\n')
    _, cand = scanners.scan_tree(tmp_path, SecurityConfig(), ["a.py", "b.py"])
    merged = scanners.compare(base, cand)
    assert base_runs[0].ran and base == []
    assert [f.file for f in merged if f.introduced_by_patch] == ["b.py"]
    assert "abcdefghijkl1234" not in merged[0].evidence


def test_resolved_findings_marked(tmp_path: Path):
    (tmp_path / "b.py").write_text('API_KEY = "abcdefghijkl1234"\n')
    _, base = scanners.scan_tree(tmp_path, SecurityConfig(), ["b.py"])
    merged = scanners.compare(base, [])
    assert merged[0].resolved_in_candidate is True and merged[0].introduced_by_patch is False


def test_missing_scanner_reported(monkeypatch, tmp_path: Path):
    real_which = scanners.shutil.which
    monkeypatch.setattr(scanners.shutil, "which", lambda n: None if n in ("gitleaks", "semgrep") else real_which(n))
    cfg = SecurityConfig(gitleaks=True, semgrep=True, require_scanners=True)
    runs, _ = scanners.scan_tree(tmp_path, cfg, [])
    assert {r.scanner: r.ran for r in runs} == {"builtin-secrets": True, "gitleaks": False, "semgrep": False}
    assert scanners.missing_required(runs, cfg) == ["gitleaks", "semgrep"]
