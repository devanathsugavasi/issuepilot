from issuepilot.security.redact import REDACTED, redact, truncate


def test_known_token_formats():
    samples = [
        "AKIAABCDEFGHIJKLMNOP",
        "ghp_" + "a" * 36,
        "sk-ant-api03-" + "b" * 30,
        "Authorization: Bearer " + "c" * 30,
        "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
    ]
    for s in samples:
        assert REDACTED in redact(s), s


def test_generic_assignment_only_redacts_value():
    out = redact('DB_PASSWORD = "hunter2hunter2"')
    assert "hunter2hunter2" not in out and "DB_PASSWORD" in out
    assert redact('password = "hunter2hunter2"', generic=False) == 'password = "hunter2hunter2"'


def test_env_secret_values_redacted(monkeypatch):
    monkeypatch.setenv("MY_SERVICE_TOKEN", "supersecretvalue123")
    assert "supersecretvalue123" not in redact("token is supersecretvalue123")


def test_plain_text_untouched():
    assert redact("all tests passed (12)") == "all tests passed (12)"


def test_truncate():
    assert len(truncate("x" * 1000, 100)) < 200
    assert truncate("short", 100) == "short"
