# Users can access another account's dashboard by changing the account ID

## Actual behavior
Changing `account_id` in `/dashboard/<account_id>` shows another user's balance.

## Expected behavior
Users can only view dashboards for accounts they own; others get HTTP 403.

## Steps to reproduce
1. Sign in as alice (owns acct-1).
2. Open `/dashboard/acct-2`.

## Acceptance criteria
- Requesting another user's account returns 403.
- Owners can still view their own dashboard.
- A regression test covers the non-owner case.
