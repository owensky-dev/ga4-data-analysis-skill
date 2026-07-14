---
name: ga4-data-analysis
description: GA4 Data API weekly growth diagnosis and executive reporting for ecommerce or DTC sites. Use when Codex needs to read a GA4 property with a service-account key, compare the most recent complete 7 days against the prior 7 days, diagnose attribution/channel/landing-page/device/item/SEO issues, and produce a Chinese boss-ready HTML report with static PNG charts, Markdown backup, and auditable JSON outputs.
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
3. Fetch GA4 data with `scripts/fetch_ga4_weekly.js`.
   - Keep Sessions/channel queries separate from ecommerce event queries.
   - Fetch `view_item`, `add_to_cart`, `begin_checkout`, and `purchase` with `date`, `deviceCategory`, and `eventName`, then aggregate the dated rows only when rendering the weekly device funnel.
4. Build the executive report with `scripts/build_boss_report.py`.
5. Validate:
   - No failed GA4 queries unless explicitly documented.
   - HTML exists and every `<img>` path resolves.
   - PNG charts are non-empty and have readable dimensions.
   - Report names the date ranges and source caveats.
6. Hand off the HTML report path first, then the Markdown backup, JSON snapshot, chart map, and chart asset folder.

## Required Diagnostic Coverage

Cover these sections unless the data is unavailable:

- Most important new or changed signal this week.
- Data health and attribution issues: `Unassigned`, `(not set)`, abnormal `Direct`, conversions with zero revenue, UTM gaps or naming inconsistency, self-referrals such as Shopify admin.
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
  --property-id 525007868 \
  --key-file /path/to/service-account.json \
  --out work/ga4_weekly_diagnosis_latest.json
```

Optional flags:

- `--timezone America/Juneau` to override the property timezone assumption.
- `--current-start YYYY-MM-DD --current-end YYYY-MM-DD` to force a date range.
- `--previous-start YYYY-MM-DD --previous-end YYYY-MM-DD` to force the comparison range.

The fetch script intentionally keeps each GA4 `runReport` request to 10 metrics or fewer and runs requests sequentially with retry to reduce socket/TLS failures.

### Build boss report

Use:

```bash
python3 scripts/build_boss_report.py \
  --input work/ga4_weekly_diagnosis_latest.json \
  --out-dir work \
  --report-date 2026-06-30
```

Prefer a Python runtime with `PIL/Pillow`. If `PIL` is unavailable, use the Codex bundled Python when present:

```bash
/Users/linheping/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/build_boss_report.py ...
```

## Validation Commands

After building, run:

```bash
python3 scripts/build_boss_report.py --input work/ga4_weekly_diagnosis_latest.json --out-dir work --report-date YYYY-MM-DD
```

Then inspect the script output. It prints generated file paths and validates HTML image references. If browser or HTTP server launch is blocked by sandboxing, say so, but static file delivery is still valid if all local image paths exist.

## Common Interpretation Rules

- Treat `conversions` carefully. If conversions exist with `$0` revenue, state that key events likely include non-purchase actions and recommend an `eventName x conversions` follow-up.
- Do not call paid media healthy just because sessions increased. If `google / cpc` or paid channels gain sessions while revenue is zero, prioritize attribution and landing-page/checkout diagnosis.
- If all revenue lands in `Direct`, flag possible attribution loss before making budget recommendations.
- If mobile has `begin_checkout` but no `purchase`, prioritize mobile checkout QA over broad page redesign.
- If AI or community sources have no visible sample, state that GA4 did not observe usable sessions rather than claiming the channel has no opportunity.

## Publishing Notes

When packaging this skill for GitHub, do not include service-account JSON keys, raw customer exports, or private GA4 output files. The scripts are generic and should accept property IDs and key paths as runtime inputs.
