# Shopify → GA4 purchase recovery

Use this workflow only when Shopify paid orders are the sales source of truth and GA4 BigQuery Export is readable. The recovery augments the browser tag; it does not replace storefront or checkout tracking.

## Required input

Prepare a local JSON array containing paid, non-test orders only. Keep the file private and omit customer fields. Each order needs:

- `transactionId` or a Shopify order ID ending in its numeric legacy ID.
- `processedAt`, `currency`, `totalPrice`, `subtotalPrice`, tax, and shipping.
- Line-item ID or SKU, name, net price, and quantity.

Never include email, phone, customer name, postal address, order notes, or payment details.

## Safety gates

For every order:

1. Query `analytics_<property-id>.events_*` and stop if the same `transaction_id` already has a `purchase` event.
2. Match exactly one GA4 checkout session using `user_pseudo_id`, `ga_session_id`, net item subtotal, product/SKU identifiers, `begin_checkout`, and `add_payment_info` near the paid-order timestamp.
3. Stop on zero or ambiguous matches.
4. Treat events within 24 hours as session-specific recovery. Events aged 24–70 hours require the additional `--allow-degraded-attribution` opt-in because GA4 no longer guarantees session-specific device and geographic information.
5. Reject events older than 70 hours, leaving a two-hour safety margin inside GA4's 72-hour timestamp limit.
6. Validate through `/debug/mp/collect` with `validation_behavior=ENFORCE_RECOMMENDATIONS` before any production submission.
7. Require explicit `--send` for `/mp/collect`. Dry-run is the default.
8. Before submission, write `pending_submission` to a private local ledger. Change it to `submitted` only after a successful response, or `uncertain` after an error. Never retry `pending_submission`, `uncertain`, `submitted`, or `verified` automatically. Re-check BigQuery on a later run before calling the event verified.

Do not automatically retry a production `/mp/collect` request after a timeout, disconnect, 429, or 5xx because the first submission may already have been accepted. Record the outcome as uncertain and let the next read-only BigQuery check decide whether another operator-authorized attempt is safe. Safe validation and read requests may use bounded retries.

The validation endpoint checks payload structure but does not validate the API secret. Report `apiSecretLoaded`, not “API secret verified.” A successful production HTTP response means submitted, not confirmed in reporting.

## Secret handling

Read the Measurement Protocol API secret from `GA4_MP_API_SECRET` or macOS Keychain. Never accept it as a command-line argument, write it to the ledger, or print it. Keep the service-account key and order JSON outside Git.

## Commands

Dry-run one or more candidate orders:

```bash
node scripts/recover_missing_purchases.js \
  --orders-file /private/path/paid_orders.json \
  --property-id 123456789 \
  --project-id example-project \
  --key-file /private/path/service-account.json \
  --measurement-id G-XXXXXXXXXX \
  --ledger work/ga4_purchase_recovery_ledger.json
```

Submit only after reviewing a `validated_dry_run` result and receiving explicit authorization:

```bash
node scripts/recover_missing_purchases.js \
  --orders-file /private/path/paid_orders.json \
  --property-id 123456789 \
  --project-id example-project \
  --key-file /private/path/service-account.json \
  --measurement-id G-XXXXXXXXXX \
  --ledger work/ga4_purchase_recovery_ledger.json \
  --send
```

Use `--bigquery-location` when the export is not in `US`. Do not use `--allow-degraded-attribution` unless the operator accepts the reduced attribution fidelity for a 24–70-hour event.

## Acceptance

- Unit tests pass.
- Dry-run returns only `already_present`, `already_submitted_by_recovery`, `no_unique_session`, a time-policy status, `validation_failed`, or `validated_dry_run`.
- Production mode submits only rows that were validated in the same run.
- No secret or PII appears in stdout, the ledger, committed files, or report artifacts.
- A later BigQuery read verifies the transaction before the workflow describes it as restored.
