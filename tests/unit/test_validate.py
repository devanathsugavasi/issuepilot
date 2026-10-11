import os
from pathlib import Path

import pytest

from issuepilot.config import PatchPolicy
from issuepilot.errors import PatchRejected
from issuepilot.patching.validate import check_path, flag_test_changes, plan_edits
from issuepilot.schemas import ChangedFile, FileEdit, PatchProposal

POLICY = PatchPolicy()


def proposal(*edits: tuple[str, str, str]) -> PatchProposal:
    return PatchProposal(summary="s", edits=[FileEdit(path=p, search=s, replace=r) for p, s, r in edits])


@pytest.mark.parametrize(
    "path",
    [
        "../x",
        "a/../../x",
        "/etc/passwd",
        "./a.py",
        "a//b",
        "a\\b",
        "",
        ".git/config",
        ".github/workflows/ci.yml",
        "issuepilot.yaml",
        ".issuepilot/runs/x",
        ".env",
        "config/.env.production",
        "deploy/server.pem",
        "home/id_rsa",
    ],
)
def test_rejected_paths(tmp_path: Path, path: str):
    assert check_path(path, tmp_path, POLICY)


def test_symlink_escape_rejected(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(outside, root / "link")
    assert any("outside the workspace" in e for e in check_path("link/x.py", root, POLICY))


def test_valid_edit_and_create(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    out = plan_edits(proposal(("a.py", "x = 1\n", "x = 3\n"), ("b.py", "", "new\n")), tmp_path, POLICY)
    assert out == {"a.py": "x = 3\ny = 2\n", "b.py": "new\n"}
    assert (tmp_path / "a.py").read_text() == "x = 1\ny = 2\n", "validation must not write"


def test_sequential_edits_to_same_file(tmp_path: Path):
    (tmp_path / "a.py").write_text("a\nb\n")
    out = plan_edits(proposal(("a.py", "a\n", "A\n"), ("a.py", "b\n", "B\n")), tmp_path, POLICY)
    assert out["a.py"] == "A\nB\n"


@pytest.mark.parametrize(
    "edit,msg",
    [
        (("a.py", "zzz", "q"), "found 0 times"),
        (("a.py", "x", "q"), "found 2 times"),
        (("a.py", "", "q"), "already exists"),
        (("missing.py", "x", "q"), "does not exist"),
        (("bin.dat", "a", "b"), "binary"),
    ],
)
def test_invalid_edits(tmp_path: Path, edit, msg):
    (tmp_path / "a.py").write_text("x x\n")
    (tmp_path / "bin.dat").write_bytes(b"a\0b")
    with pytest.raises(PatchRejected) as e:
        plan_edits(proposal(edit), tmp_path, POLICY)
    assert msg in str(e.value)


def test_limits(tmp_path: Path):
    edits = [(f"f{i}.py", "", "x") for i in range(3)]
    with pytest.raises(PatchRejected, match="touches 3 files"):
        plan_edits(proposal(*edits), tmp_path, PatchPolicy(max_files=2))
    with pytest.raises(PatchRejected, match="exceeds"):
        plan_edits(proposal(("big.py", "", "x" * 2000)), tmp_path, PatchPolicy(max_file_bytes=1000))


def test_one_bad_edit_rejects_whole_proposal(tmp_path: Path):
    with pytest.raises(PatchRejected):
        plan_edits(proposal(("ok.py", "", "x"), ("../bad", "", "x")), tmp_path, POLICY)


def test_flag_test_changes():
    patch = (
        "--- a/tests/test_x.py\n+++ b/tests/test_x.py\n@@ -1,3 +1,3 @@\n"
        "-    self.assertEqual(f(), 1)\n+    pass\n+@unittest.skip('later')\n"
        "--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-assert old\n+new\n"
    )
    manifest = [
        ChangedFile(path="tests/test_x.py", change="modified", is_test=True),
        ChangedFile(path="src/x.py", change="modified", is_test=False),
        ChangedFile(path="tests/test_old.py", change="deleted", is_test=True),
    ]
    blocking, info = flag_test_changes(patch, manifest)
    assert "tests/test_old.py: test file deleted" in blocking
    assert "tests/test_x.py: removes 1 assertion line(s)" in blocking
    assert "tests/test_x.py: adds 1 skip marker(s)" in blocking
    assert not any("src/x.py" in b for b in blocking)
    assert info == ["tests/test_x.py: existing test file modified"]
