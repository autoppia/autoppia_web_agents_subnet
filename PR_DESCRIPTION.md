# Payment-per-eval gating (alpha to wallet, sn36)

## Summary

Adds optional **payment-per-eval gating**: miners pay α (e.g. 10 α per evaluation) to a designated wallet; the validator only allows evaluations for miners whose coldkey has paid at least that amount. This reduces evaluation spam. When disabled (default), behaviour is unchanged.

## What changed

- **Config** (`validator/config.py`)
  - `ENABLE_PAYMENT_GATING` (default `False`)
  - `PAYMENT_WALLET_SS58` – payments wallet coldkey
  - `ALPHA_PER_EVAL` (default `10.0`)
  - `PAYMENT_SUBNET_ID` (default `36`), `PAYMENT_SCAN_CHUNK`, `PAYMENT_SCAN_LOOKBACK_BLOCKS`

- **Payment module** (`validator/payment/`)
  - `allowed_evaluations_from_paid_rao(paid_rao, alpha_per_eval)` – integer evals from rao
  - `get_paid_alpha_per_coldkey_async(...)` – scans chain via **metahash** `AlphaTransfersScanner` (when installed), returns `coldkey_ss58 -> total amount_rao` for transfers to the payments wallet on sn36

- **Handshake integration** (`validator/round_start/mixin.py`)
  - After stake/coldkey caps: if gating enabled and wallet set, fetches paid α per coldkey over `[current_block - lookback, current_block]`, keeps only miners with `allowed_evaluations_from_paid_rao(...) > 0`
  - Logs `payment_skip` in the handshake summary; on scanner/network errors, logs warning and proceeds without gating

- **Tests** (`tests/validator/unit/test_payment.py`)
  - Unit tests for `allowed_evaluations_from_paid_rao` (edge cases, rao math)
  - Unit tests for `get_paid_alpha_per_coldkey_async` (invalid args, mock-scanner aggregation)

## Why

Miners must pay α to a wallet to receive evaluations (e.g. 10 α per eval), so the subnet can limit evaluation spam without changing the rest of the flow. The scanner (from metahash sn73) was extended with `target_subnet_id` to track sn36 transfers; this PR consumes that in the validator.

## How to verify

- **Unit tests:** `VALIDATOR_NAME=test VALIDATOR_IMAGE=test pytest tests/validator/unit/test_payment.py -v`
- **Gating off (default):** No env changes; handshake unchanged, no `payment_skip` logic.
- **Gating on, no metahash:** Set `ENABLE_PAYMENT_GATING=true`, `PAYMENT_WALLET_SS58=<addr>`. Without metahash, scanner is unavailable → empty paid → all candidates filtered; logs `[payment] AlphaTransfersScanner not available`.
- **Gating on, with metahash:** Install metahash, set wallet and optional `ALPHA_PER_EVAL`; only miners whose coldkey has paid ≥ that amount get into the handshake.

## Checklist

- [x] Config added with safe defaults (gating off, 10 α, sn36).
- [x] Payment logic in dedicated module; handshake integration behind feature flag.
- [x] Errors in payment path do not break handshake (try/except, proceed without gating).
- [x] Unit tests for rao math and scanner aggregation (with mocked metahash).
- [x] `PAYMENT_SCAN_CHUNK` reads env var `PAYMENT_SCAN_CHUNK` (fixed in follow-up commit).

## Dependencies

- **Optional:** [metahash](https://github.com/autoppia/metahash) (or equivalent) for `AlphaTransfersScanner`. If not installed, gating returns no paid data and all miners are filtered when gating is enabled.
