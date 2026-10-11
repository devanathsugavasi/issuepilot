"""Account dashboard service."""

ACCOUNTS = {
    "acct-1": {"owner": "alice", "balance": 100},
    "acct-2": {"owner": "bob", "balance": 250},
}


class Forbidden(Exception):
    """Raised when a user requests data they do not own."""


def get_dashboard(current_user: str, account_id: str) -> dict:
    account = ACCOUNTS.get(account_id)
    if account is None:
        raise KeyError(account_id)
    return {"account_id": account_id, "balance": account["balance"]}
