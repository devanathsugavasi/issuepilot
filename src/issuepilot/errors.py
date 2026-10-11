"""Explicit domain and execution errors."""


class IssuePilotError(Exception):
    """Base class for all IssuePilot errors."""


class ConfigError(IssuePilotError):
    """Configuration is missing, malformed or requests an unsupported setting."""


class RepositoryError(IssuePilotError):
    """Target is not a usable Git repository, or Git failed."""


class IssueParseError(IssuePilotError):
    """Issue file could not be read or is empty."""


class ProviderUnavailable(IssuePilotError):
    """Model provider is not configured (missing SDK, credentials or model name)."""


class ProviderError(IssuePilotError):
    """Model request failed, timed out, was refused or returned invalid output."""


class PatchRejected(IssuePilotError):
    """A proposed patch violated validation or safety policy."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class InvalidTransition(IssuePilotError):
    """The orchestrator attempted a state transition that is not allowed."""
