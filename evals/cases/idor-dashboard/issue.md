# Users can view another account's dashboard by changing the account ID

## Actual behavior
`get_dashboard("alice", "acct-2")` returns Bob's balance. Any signed-in user can read any
account's dashboard by changing the account ID in the URL (insecure direct object reference).

## Expected behavior
Users may only view dashboards for accounts they own.

## Acceptance criteria
- Requesting another user's account raises `Forbidden`.
- Owners can still view their own dashboard.
- Unknown accounts still raise `KeyError`.
