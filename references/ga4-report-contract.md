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

## Key-event and purchase reconciliation contract

- Request `keyEvents` in new Data API reports. Do not request `keyEvents` and the legacy `conversions` alias together; GA4 rejects them as duplicate metrics.
- Preserve a derived `conversions = keyEvents` value in normalized rows only when an older report renderer still depends on that field.
- Add `key_events_current` and `key_events_previous` with dimensions `eventName`, `isKeyEvent` and metrics `eventCount`, `keyEvents`, `eventValue`, `totalRevenue`, `purchaseRevenue`, `ecommercePurchases`, `transactions`.
- Add `purchase_transactions_current` and `purchase_transactions_previous` filtered to `eventName = purchase`, with dimensions `date`, `transactionId`, `deviceCategory`, `sessionDefaultChannelGroup`, `sessionSourceMedium`.
- List the property's configured key events through the GA4 Admin API when the service account has access. A configured non-purchase key event must be labelled as a micro-conversion, not an order.
- Interpret `eventValue` as event parameter value, not revenue. Add-to-cart and checkout events can have event value while revenue remains zero.
- Check that purchase `eventCount`, `keyEvents`, `ecommercePurchases`, `transactions`, and unique non-empty `transactionId` counts agree.
- Check that purchase `purchaseRevenue`, purchase `totalRevenue`, and the sum of transaction-detail `purchaseRevenue` agree within currency rounding tolerance.
- Compare aggregate `itemRevenue` separately. Explain legitimate differences from purchase revenue through tax, shipping, and refunds before declaring a tracking fault.
- Do not promise an exact `transactionId x itemName` join from the Core Data API. Require GA4 BigQuery Export when order-to-SKU mapping is needed.

## Executive report rules

- Open with `Executive Summary`.
- Put the conclusion before implementation details.
- Every chart needs adjacent interpretation in Chinese.
- Include exact date ranges and comparison baseline.
- Preserve caveats that change interpretation.
- Replace generic "needs eventName follow-up" caveats with the actual key-event and transaction reconciliation result whenever those datasets are available.
- End with 3-5 prioritized actions.
