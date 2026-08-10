# GA4 数据分析 / GA4 Data Analysis

[![CI](https://github.com/owensky-dev/ga4-data-analysis-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/owensky-dev/ga4-data-analysis-skill/actions/workflows/ci.yml)

面向独立站、DTC 品牌和电商增长复盘的 Codex skill。它会读取 Google Analytics Data API 数据，默认使用「最近完整 7 天 vs 再往前 7 天」的周期，生成中文 GA4 周增长诊断，并输出适合老板汇报的 HTML 报告、静态 PNG 图表、Markdown 备份和可审计 JSON 快照。

This Codex skill turns Google Analytics 4 Data API access into a weekly ecommerce growth diagnosis. It compares the latest complete 7 days with the previous 7 days and produces a Chinese executive HTML report with static PNG charts, a Markdown backup, and auditable JSON outputs.

## 适用场景 / Use Cases

- 独立站 GA4 周报和增长诊断。
- 渠道归因异常排查，例如 `Direct` 异常、`Unassigned`、`(not set)`、UTM 命名混乱。
- Google Ads / Shopping / Search 落地页表现复盘。
- Mobile vs desktop 漏斗诊断，覆盖 `view_item`、`add_to_cart`、`begin_checkout`、`purchase`。
- 漏斗事件保留 `date × deviceCategory × eventName` 粒度，周报展示周汇总，JSON 可继续审计每日加购和结账变化。
- Key event 贡献拆解：使用 `eventName × keyEvents × purchaseRevenue` 区分订单与非收入微转化，并读取当前配置的 key events。
- Purchase 完整性核验：按 `transactionId`、设备、渠道、source/medium 对账 `ecommercePurchases`、`transactions`、`purchaseRevenue`、`totalRevenue` 和聚合 `itemRevenue`。
- BigQuery Export 就绪探测：区分数据集未生成、缺少数据集级 Data Viewer、等待事件表和可读取状态，并忽略以下划线开头的临时数据集。
- 可选 Shopify 订单真值核验：仅接受与本期 GA4 日期窗口完全一致的对账文件，避免旧订单数据冒充本期结果。
- 商品漏斗分析，覆盖 `itemName`、`itemsViewed`、`itemsAddedToCart`、`itemsPurchased`、`itemRevenue`。
- SEO、内容页、Referral、AI 来源机会分析。

## What It Produces

- `ga4_weekly_diagnosis_latest.json`: GA4 raw snapshot for audit.
- `ga4_weekly_boss_report_<date>.html`: boss-ready executive report.
- `ga4_weekly_boss_report_<date>.md`: editable Markdown backup.
- `ga4_boss_report_chart_map_<date>.json`: chart map and evidence notes.
- `ga4_boss_report_assets_<date>/`: static PNG chart assets.
- `ga4_bigquery_probe_latest.json`: optional BigQuery Export readiness snapshot.

## Usage

Install or copy this folder into your Codex skills directory, then invoke:

```text
Use $ga4-data-analysis to generate a Chinese GA4 weekly boss report with charts.
```

The skill expects a GA4 property ID and a Google Analytics Data API service-account JSON key path. Do not commit private service-account keys or GA4 customer exports to this repository.

The fetcher requests `keyEvents` and exposes `conversions` only as a backward-compatible normalized field. It never requests both aliases in one GA4 Data API report. Exact transaction-to-item joins require GA4 BigQuery Export because the Core Data API does not provide a stable `transactionId × itemName` contract.

## Scripts

Fetch weekly GA4 data:

```bash
node scripts/fetch_ga4_weekly.js \
  --property-id 123456789 \
  --key-file /path/to/service-account.json \
  --out work/ga4_weekly_diagnosis_latest.json
```

Build the executive report:

```bash
python3 scripts/build_boss_report.py \
  --input work/ga4_weekly_diagnosis_latest.json \
  --out-dir work \
  --report-date 2026-06-30 \
  --bigquery-probe work/ga4_bigquery_probe_latest.json \
  --shopify-reconciliation work/ga4_shopify_order_reconciliation_latest.json \
  --site-domain example.com
```

Probe BigQuery Export before report generation when a Google Cloud project is available:

```bash
node scripts/probe_bigquery_export.js \
  --property-id 123456789 \
  --project-id example-project \
  --key-file /path/to/service-account.json \
  --out work/ga4_bigquery_probe_latest.json
```

The report reconciliation flags are optional. Do not pass a Shopify file from a different GA4 date window.

If your default Python does not include `PIL/Pillow`, use the Codex bundled Python runtime when available.

## 关注公众号

如果这个 Skill 对你有帮助，欢迎关注微信公众号 **虎皮叔叔聊跨境独立站**，获取更多独立站增长、数据分析与 AI 营销实操内容。

<p align="center">
  <img src="assets/wechat-qr.png" alt="虎皮叔叔聊跨境独立站公众号二维码" width="900">
</p>

<p align="center">微信扫码关注「虎皮叔叔聊跨境独立站」</p>
