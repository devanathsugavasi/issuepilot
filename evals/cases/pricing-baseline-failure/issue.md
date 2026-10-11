# 10% discount charges $0.00

## Actual behavior
`apply_discount(1000, 10)` returns 0. The existing test `test_ten_percent` fails.

## Expected behavior
A 10% discount on 1000 cents returns 900.

## Acceptance criteria
- `tests/test_pricing.py` passes.
