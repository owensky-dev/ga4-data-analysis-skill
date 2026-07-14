# GA4 数据分析 / GA4 Data Analysis

面向独立站、DTC 品牌和电商增长复盘的 Codex skill。它会读取 Google Analytics Data API 数据，默认使用「最近完整 7 天 vs 再往前 7 天」的周期，生成中文 GA4 周增长诊断，并输出适合老板汇报的 HTML 报告、静态 PNG 图表、Markdown 备份和可审计 JSON 快照。

This Codex skill turns Google Analytics 4 Data API access into a weekly ecommerce growth diagnosis. It compares the latest complete 7 days with the previous 7 days and produces a Chinese executive HTML report with static PNG charts, a Markdown backup, and auditable JSON outputs.

## 适用场景 / Use Cases

- 独立站 GA4 周报和增长诊断。
- 渠道归因异常排查，例如 `Direct` 异常、`Unassigned`、`(not set)`、UTM 命名混乱。
- Google Ads / Shopping / Search 落地页表现复盘。
- Mobile vs desktop 漏斗诊断，覆盖 `view_item`、`add_to_cart`、`begin_checkout`、`purchase`。
- 漏斗事件保留 `date × deviceCategory × eventName` 粒度，周报展示周汇总，JSON 可继续审计每日加购和结账变化。
- 商品漏斗分析，覆盖 `itemName`、`itemsViewed`、`itemsAddedToCart`、`itemsPurchased`、`itemRevenue`。
- SEO、内容页、Referral、AI 来源机会分析。

## What It Produces

- `ga4_weekly_diagnosis_latest.json`: GA4 raw snapshot for audit.
- `ga4_weekly_boss_report_<date>.html`: boss-ready executive report.
- `ga4_weekly_boss_report_<date>.md`: editable Markdown backup.
- `ga4_boss_report_chart_map_<date>.json`: chart map and evidence notes.
- `ga4_boss_report_assets_<date>/`: static PNG chart assets.

## Usage

Install or copy this folder into your Codex skills directory, then invoke:

```text
Use $ga4-data-analysis to generate a Chinese GA4 weekly boss report with charts.
```

The skill expects a GA4 property ID and a Google Analytics Data API service-account JSON key path. Do not commit private service-account keys or GA4 customer exports to this repository.

## Scripts

Fetch weekly GA4 data:

```bash
node scripts/fetch_ga4_weekly.js \
  --property-id 525007868 \
  --key-file /path/to/service-account.json \
  --out work/ga4_weekly_diagnosis_latest.json
```

Build the executive report:

```bash
python3 scripts/build_boss_report.py \
  --input work/ga4_weekly_diagnosis_latest.json \
  --out-dir work \
  --report-date 2026-06-30
```

If your default Python does not include `PIL/Pillow`, use the Codex bundled Python runtime when available.
