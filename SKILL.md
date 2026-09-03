---
name: ga4-data-analysis
description: GA4 Data API weekly growth diagnosis, Shopify purchase-integrity reconciliation, guarded Measurement Protocol recovery, and executive reporting for ecommerce or DTC sites. Use when Codex needs to compare complete weeks, diagnose attribution/channel/landing-page/device/item/SEO issues, check GA4 BigQuery Export, reconcile Shopify order truth, safely investigate or recover missing GA4 purchase events, or produce a Chinese boss-ready HTML report with static PNG charts and auditable backups.
---

# GA4 数据分析

## Overview

Use this skill to turn GA4 Data API access into an action-oriented weekly growth diagnosis. The default output is a Chinese executive report for ecommerce/DTC operators: answer first, charts in the body, and concrete next actions.

Prefer this skill when the user asks for GA4 周报、GA4 增长诊断、独立站数据分析、老板版报告、渠道归因诊断、mobile 漏斗、商品漏斗、广告落地页排查、SEO/Referral/AI 来源机会分析, or asks to automate recurring GA4 reports.

## Workflow

1. Confirm or infer inputs:
   - GA4 property ID.
   - Service account JSON key path.
   - Workspace/output directory.
   - Report language, default Chinese.
   - Time window, default latest complete 7 days in the GA4 property timezone vs the previous 7 days.
2. Read automation or project memory if the request is recurring or references a previous report. Preserve the last accepted report format unless the user asks to change it.
3. When a Google Cloud project ID is available, probe GA4 BigQuery Export with `scripts/probe_bigquery_export.js` before building the report.
   - Ignore underscore-prefixed temporary query-result datasets.
   - Distinguish a missing dataset, missing dataset-level Data Viewer permission, an empty dataset waiting for event tables, and a ready export.
   - Keep `BigQuery Job User` at project scope and grant `BigQuery Data Viewer` only on the GA4 export dataset when required.
4. Fetch GA4 data with `scripts/fetch_ga4_weekly.js`.
   - Keep Sessions/channel queries separate from ecommerce event queries.
   - Query `keyEvents`, not `conversions`. GA4 treats them as duplicate metric aliases and rejects a request containing both. Keep a derived `conversions` field only for backward compatibility with older renderers.
   - Fetch `view_item`, `add_to_cart`, `begin_checkout`, and `purchase` with `date`, `deviceCategory`, and `eventName`, then aggregate the dated rows only when rendering the weekly device funnel.
   - Fetch key-event contribution by `eventName` and `isKeyEvent` with `eventCount`, `keyEvents`, `eventValue`, `purchaseRevenue`, `totalRevenue`, `ecommercePurchases`, and `transactions` for both periods.
   - Fetch purchase detail by `date`, `transactionId`, `deviceCategory`, `sessionDefaultChannelGroup`, and `sessionSourceMedium`. Also list configured key events through the GA4 Admin API when access permits.
5. For every weekly or monthly purchase-integrity claim, run `scripts/reconcile_shopify_ga4.js` against the exact report window.
   - Require every GA4 BigQuery daily table in the window. If any date is missing, keep the result non-publishable and suppress purchase/refund coverage rates.
   - Match unique BigQuery `ecommerce.transaction_id` values to Shopify order IDs. Keep current paid Online Store business totals separate from the web purchase cohort, which also includes orders later marked `PARTIALLY_REFUNDED` or `REFUNDED`.
   - Report missing purchases, GA4-only IDs, duplicate/blank IDs, expected refund events, missing refunds, and the revenue bridge separately. Never call the aggregate GA4-purchases/Shopify-orders ratio a tracking rate.
   - Keep Shop/POS/draft/app/offsite orders outside the web capture denominator while retaining them in Shopify business reporting.
6. When Shopify has a paid order that GA4 may have missed, read [purchase-recovery.md](references/purchase-recovery.md) before acting.
   - Keep diagnosis read-only by default. Require readable BigQuery events and a current minimal, non-PII Shopify order file.
   - Run `scripts/recover_missing_purchases.js` without `--send` first. Submit only after an exact `transaction_id` dedupe check, one unique checkout-session match, strict debug validation, and explicit user authorization.
   - Treat 24–70-hour recovery as degraded attribution requiring a separate opt-in. Never backfill an event older than 70 hours.
   - Keep both BigQuery `transaction_id` and a private local ledger as dedupe gates. A production HTTP response means submitted; verify later through BigQuery before calling it restored.
7. Build the executive report with `scripts/build_boss_report.py`. Pass the optional BigQuery probe and Shopify reconciliation paths only when those artifacts exist for the current run.
8. Validate:
   - No failed GA4 queries unless explicitly documented.
   - HTML exists and every `<img>` path resolves.
   - PNG charts are non-empty and have readable dimensions.
   - Report names the date ranges and source caveats.
   - Key-event totals are explained by event name; purchase count and revenue are reconciled against transaction and item datasets.
   - Never reuse a Shopify reconciliation file whose current date range differs from the GA4 report window.
9. Hand off the HTML report path first, then the Markdown backup, JSON snapshot, chart map, and chart asset folder.

## Required Diagnostic Coverage

Cover these sections unless the data is unavailable:

- Most important new or changed signal this week.
- Data health and attribution issues: `Unassigned`, `(not set)`, abnormal `Direct`, conversions with zero revenue, UTM gaps or naming inconsistency, self-referrals such as Shopify admin.
- Key-event and purchase integrity: configured key events, `eventName` contribution, unique `transactionId`, `ecommercePurchases`, `transactions`, `purchaseRevenue`, `totalRevenue`, and aggregate `itemRevenue` reconciliation.
- BigQuery Export and order truth: probe the expected `analytics_<property-id>` dataset, report its permission/table status, and use current-window Shopify reconciliation only when supplied. Never present stale order data as current truth.
- Transaction-level purchase/refund integrity: use the canonical `purchase_reconciliation.json`; show the web purchase cohort, matched/missing/GA4-only IDs, separate current-paid coverage, refund coverage, duplicates, blank IDs, complete-table coverage, and the explained revenue bridge.
- Channel efficiency by channel, source/medium, and campaign: sessions, engagement rate, conversions, revenue, revenue per session.
- Paid landing pages: high-traffic or low-conversion paid pages with zero revenue.
- Mobile vs desktop funnel: `view_item`, `add_to_cart`, `begin_checkout`, `purchase`; call out mobile CRO issues.
- Preserve the date dimension for every mobile/desktop funnel event row so daily add-to-cart and checkout changes remain auditable in the raw JSON snapshot.
- Item funnel and tracking health: `itemName`, `itemsViewed`, `itemsAddedToCart`, `itemsPurchased`, `itemRevenue`; call out dirty item names and high-view low-ATC products.
- SEO, content-page, referral, and AI-source opportunities, especially `google / organic`, `bing / organic`, `chatgpt`, `perplexity`, `reddit`, `youtube`, and `pinterest`.
- Three to five priority actions ranked by impact and feasibility.

## Report Format

Default to the boss-ready format:

- One static HTML report.
- Static PNG charts embedded in the HTML, not remote images.
- Markdown backup with the same executive story.
- Chart map JSON describing each visual, chart type, supported claim, and source fields.
- Raw GA4 JSON snapshot for audit.

The HTML reading path should be:

1. Short title and metadata.
2. Visible `Executive Summary`.
3. KPI cards after the summary.
4. Visual evidence sections, each with one adjacent interpretation paragraph.
5. Recommended actions.
6. Further questions and caveats.

Do not deliver only a KPI dashboard unless the user explicitly asks for a dashboard. The default is a diagnostic memo with evidence.

## Scripts

### Fetch GA4 data

Use:

```bash
node scripts/fetch_ga4_weekly.js \
  --property-id 123456789 \
  --key-file /path/to/service-account.json \
  --out work/ga4_weekly_diagnosis_latest.json
```

Optional flags:

- `--timezone America/New_York` to override the timezone returned by the GA4 Admin API.
- `--current-start YYYY-MM-DD --current-end YYYY-MM-DD` to force a date range.
- `--previous-start YYYY-MM-DD --previous-end YYYY-MM-DD` to force the comparison range.

The fetch script intentionally keeps each GA4 `runReport` request to 10 metrics or fewer and runs requests sequentially with retry to reduce socket/TLS failures.

The JSON output includes `key_events_current/previous`, `purchase_transactions_current/previous`, and `configured_key_events`. Exact `transactionId x itemName` joins are not a reliable Core Data API contract; use GA4 BigQuery Export when order-to-SKU reconciliation is required.

### Build boss report

Use:

```bash
python3 scripts/build_boss_report.py \
  --input work/ga4_weekly_diagnosis_latest.json \
  --out-dir work \
  --report-date 2026-06-30 \
  --bigquery-probe work/ga4_bigquery_probe_latest.json \
  --shopify-reconciliation work/ga4_shopify_order_reconciliation_latest.json \
  --site-domain example.com
```

The last three flags are optional. Omit `--report-date` to derive it from the GA4 snapshot generation time. Omit either reconciliation flag when that source was not read in the current run.

### Probe BigQuery Export

Use:

```bash
node scripts/probe_bigquery_export.js \
  --property-id 123456789 \
  --project-id example-project \
  --key-file /path/to/service-account.json \
  --out work/ga4_bigquery_probe_latest.json
```

Treat `needs_data_viewer` as a dataset-level permission gap. Do not solve it by granting project-wide Data Viewer. A `ready` result means event tables are readable; it does not prove that every date required by the report has already arrived.

### Reconcile Shopify purchases and refunds

Use the same start/end dates and Shopify snapshot as the report:

```bash
node scripts/reconcile_shopify_ga4.js \
  --property-id 123456789 \
  --project-id example-project \
  --key-file /path/to/service-account.json \
  --shopify-orders data/raw/shopify_orders_90d.csv \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --timezone America/New_York \
  --out data/processed/purchase_reconciliation.json
```

The script is read-only. It verifies daily BigQuery table coverage, compares unique purchase/refund `transaction_id` values with Shopify web orders, excludes offsite orders from the web denominator, and emits a non-PII JSON contract for weekly/monthly reports. `purchase.capture_rate` and `refund.capture_rate` are `null` unless the date window has complete daily-table coverage, one consistent Shopify currency, and no missing or duplicate Shopify transaction IDs.

### Recover a missing purchase

Use `scripts/recover_missing_purchases.js` only after reading [purchase-recovery.md](references/purchase-recovery.md). Dry-run is the default; `--send` is an external write and requires explicit authorization. Load the Measurement Protocol API secret from `GA4_MP_API_SECRET` or macOS Keychain, never from a command-line value or committed file.

The debug endpoint validates payload structure with `ENFORCE_RECOMMENDATIONS`, but it does not validate the API secret. Keep status language precise: `validated_dry_run`, `submitted`, then later `verified` only after GA4/BigQuery read-back.

Prefer a Python runtime with `PIL/Pillow`. If `PIL` is unavailable, use another available Python runtime that includes Pillow.

## Validation Commands

After building, run:

```bash
python3 scripts/build_boss_report.py --input work/ga4_weekly_diagnosis_latest.json --out-dir work --report-date YYYY-MM-DD
```

Then inspect the script output. It prints generated file paths and validates HTML image references. If browser or HTTP server launch is blocked by sandboxing, say so, but static file delivery is still valid if all local image paths exist.

## Common Interpretation Rules

- Treat legacy `conversions` fields as key-event totals, not order totals. Use the event-level and transaction datasets to explain every zero-revenue key event in the same run.
- Prefer `keyEvents` in new API requests. Never request `keyEvents` and `conversions` together; expose `conversions = keyEvents` only as a compatibility field in processed JSON.
- Do not leave zero-revenue key events unresolved when event-level data is available. Name the contributing events and classify non-purchase events as micro-conversions rather than orders.
- Treat `eventValue` as the sum of the event parameter `value`, not as revenue. Use `purchaseRevenue` and transaction rows for order revenue.
- Reconcile purchase `eventCount`, `keyEvents`, `ecommercePurchases`, `transactions`, and unique non-empty `transactionId` values. Reconcile `purchaseRevenue` with transaction detail and `totalRevenue`; compare aggregate `itemRevenue` separately because tax, shipping, and refunds can create legitimate differences.
- Do not call paid media healthy just because sessions increased. If `google / cpc` or paid channels gain sessions while revenue is zero, prioritize attribution and landing-page/checkout diagnosis.
- If all revenue lands in `Direct`, flag possible attribution loss before making budget recommendations.
- If mobile has `begin_checkout` but no `purchase`, prioritize mobile checkout QA over broad page redesign.
- If AI or community sources have no visible sample, state that GA4 did not observe usable sessions rather than claiming the channel has no opportunity.
- If BigQuery is ready but a required daily table is missing, state the actual table coverage and defer full transaction-to-item reconciliation.
- Treat Shopify-current-paid count minus GA4 purchase count as an aggregate alert only. It can hide offsetting exceptions such as three missing purchases and one stale refunded purchase; publish capture rates only from the canonical transaction reconciliation.
- Define web purchase capture as matched unique GA4 purchase IDs divided by eligible non-test, non-cancelled Online Store orders with `PAID`, `PARTIALLY_REFUNDED`, or `REFUNDED` status. Report current-paid coverage separately, and define refund coverage against Shopify orders that expect a refund event.
- Exclude Shopify reconciliation from the report when its `dateRange.current` does not exactly match the GA4 current window.
- Do not infer a missing purchase from aggregate counts alone. Require a Shopify paid non-test order, no matching GA4 `transaction_id`, and one uniquely matched BigQuery checkout session.
- Never enable degraded 24–70-hour attribution or `--send` implicitly. Stop on ambiguous sessions, failed strict validation, an existing transaction, or a private-ledger hit.

## Publishing Notes

When packaging this skill for GitHub, do not include service-account JSON keys, Measurement Protocol secrets, raw customer exports, private ledgers, or private GA4 output files. The scripts are generic and accept property IDs and local key paths as runtime inputs.
