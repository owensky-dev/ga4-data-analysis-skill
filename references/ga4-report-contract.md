# GA4 Report Contract

Use this reference when the report must match the boss-ready weekly format.

## Required artifacts

- `ga4_weekly_diagnosis_latest.json`: raw GA4 snapshot.
- `ga4_weekly_boss_report_<date>.html`: primary report.
- `ga4_weekly_boss_report_<date>.md`: editable backup.
- `ga4_boss_report_chart_map_<date>.json`: chart map.
- `ga4_boss_report_assets_<date>/`: PNG chart assets.

## Required visuals

- Daily sessions and revenue trend.
- Core metric week-over-week movement.
- Channel sessions and revenue distribution.
- Paid landing pages with traffic and zero revenue.
- Mobile vs desktop ecommerce funnel.
- Item view/add-to-cart/purchase performance.
- SEO/content/referral/AI opportunity view.

## GA4 funnel data contract

- Fetch ecommerce funnel events in an independent GA4 request with `date`, `deviceCategory`, and `eventName` dimensions plus the `eventCount` metric.
- Limit the event filter to `view_item`, `add_to_cart`, `begin_checkout`, and `purchase`.
- Do not add `eventName` to Sessions, channel, campaign, or landing-page queries because it changes their aggregation grain.
- Keep dated event rows in the audit JSON. Sum them by device and event only when rendering the weekly funnel.

## Executive report rules

- Open with `Executive Summary`.
- Put the conclusion before implementation details.
- Every chart needs adjacent interpretation in Chinese.
- Include exact date ranges and comparison baseline.
- Preserve caveats that change interpretation.
- End with 3-5 prioritized actions.
