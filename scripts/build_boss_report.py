#!/usr/bin/env python3
import argparse
import html
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WORK = Path("work")
SHOPIFY_RECON_PATH = None
BIGQUERY_PROBE_PATH = None
SITE_DOMAIN = None

TOKENS = {
    "surface": "#FCFCFD",
    "panel": "#FFFFFF",
    "ink": "#1F2430",
    "muted": "#677083",
    "grid": "#E6E8F0",
    "axis": "#D7DBE7",
    "blue": "#3E6FB6",
    "blue_light": "#CFE0FF",
    "green": "#4F8A57",
    "green_light": "#DCEEDB",
    "gold": "#A9851F",
    "gold_light": "#FBE39B",
    "orange": "#C9613D",
    "orange_light": "#F6C7B7",
    "red": "#AE3F48",
    "red_light": "#F5C5CB",
    "neutral": "#C9CED8",
    "neutral_dark": "#444B58",
}

FONT_CANDIDATES = [
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def pick_font_path():
    for item in FONT_CANDIDATES:
        if Path(item).exists():
            return item
    return None


FONT_PATH = pick_font_path()


def font(size):
    if FONT_PATH:
        return ImageFont.truetype(FONT_PATH, size=size)
    return ImageFont.load_default()


def text_size(draw, text, fnt):
    box = draw.textbbox((0, 0), str(text), font=fnt)
    return box[2] - box[0], box[3] - box[1]


def text_width(draw, text, fnt):
    return text_size(draw, text, fnt)[0]


def wrap_text(draw, text, fnt, max_width):
    text = str(text).replace("\n", " ")
    lines = []
    current = ""
    for ch in text:
        candidate = current + ch
        if text_width(draw, candidate, fnt) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def draw_wrapped(draw, xy, text, fnt, fill, max_width, line_gap=6, max_lines=None):
    x, y = xy
    lines = wrap_text(draw, text, fnt, max_width)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and text_width(draw, lines[-1] + "...", fnt) > max_width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "..."
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += text_size(draw, line, fnt)[1] + line_gap
    return y


def new_canvas(width=1500, height=820):
    return Image.new("RGB", (width, height), TOKENS["surface"])


def add_header(draw, title, subtitle, width):
    draw_wrapped(draw, (54, 28), title, font(34), TOKENS["ink"], width - 108, 8, max_lines=2)
    draw_wrapped(draw, (54, 88), subtitle, font(18), TOKENS["muted"], width - 108, 6, max_lines=2)
    return 142


def fmt_num(value):
    return f"{float(value):,.0f}"


def fmt_money(value):
    return f"${float(value):,.2f}"


def fmt_pct(value, digits=1):
    return f"{float(value) * 100:.{digits}f}%"


def fmt_pp(value, digits=1):
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.{digits}f} pp"


def delta_ratio(cur, prev):
    if prev == 0:
        return None
    return (cur - prev) / prev


def fmt_delta_ratio(cur, prev, digits=1):
    value = delta_ratio(cur, prev)
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.{digits}f}%"


def clean_page(path):
    value = str(path or "(not set)").split("?")[0]
    if value == "/":
        return "首页 /"
    value = value.replace("/collections/", "集合页 / ")
    value = value.replace("/products/", "商品页 / ")
    return value[:120]


def truncate(text, length=80):
    text = str(text)
    return text if len(text) <= length else text[: length - 3] + "..."


def ymd_zh(ymd):
    try:
        dt = datetime.strptime(ymd, "%Y-%m-%d")
        return f"{dt.month} 月 {dt.day} 日"
    except ValueError:
        return ymd


def rows(data, name):
    return data.get("results", {}).get(name, {}).get("rows", [])


def load_bigquery_status(existing_status=None):
    if BIGQUERY_PROBE_PATH is None or not BIGQUERY_PROBE_PATH.exists():
        return existing_status or {}
    probe = json.loads(BIGQUERY_PROBE_PATH.read_text(encoding="utf-8"))
    return bigquery_status_from_probe(probe, existing_status or {})


def same_range(left, right):
    return (
        left.get("startDate") == right.get("startDate")
        and left.get("endDate") == right.get("endDate")
    )


def load_shopify_reconciliation(data):
    current_range = data.get("dateRanges", {}).get("current", {})
    bq_status = load_bigquery_status()
    if SHOPIFY_RECON_PATH is None or not SHOPIFY_RECON_PATH.exists():
        return {"bigQueryStatus": bq_status}
    recon = json.loads(SHOPIFY_RECON_PATH.read_text(encoding="utf-8"))
    if bq_status:
        recon["bigQueryStatus"] = bq_status
    else:
        bq_status = recon.get("bigQueryStatus", {})
    recon_range = recon.get("dateRange", {}).get("current", {})
    if current_range and not same_range(current_range, recon_range):
        return {
            "staleShopifyReconciliation": True,
            "dateRange": recon.get("dateRange", {}),
            "bigQueryStatus": recon.get("bigQueryStatus", bq_status),
        }
    return recon


def bigquery_status_from_probe(probe, existing_status):
    property_id = probe.get("propertyId", "")
    project_id = probe.get("projectId", "")
    dataset_id = probe.get("expectedDatasetId", "")
    status = probe.get("status", "unknown")
    link_count = probe.get("adminLinks", {}).get("count", 0)
    query_ok = probe.get("jobQuery", {}).get("httpStatus") == 200
    table_ids = probe.get("expectedDataset", {}).get("tableIds", [])

    link_text = (
        f"GA4 Property {property_id} 已成功链接 BigQuery 项目 {project_id}。"
        if link_count
        else existing_status.get(
            "adminApiBigQueryLinks",
            f"GA4 Admin API 尚未返回 Property {property_id} 的 BigQuery Link。",
        )
    )
    query_text = (
        "service account 的 BigQuery Job User 已生效，SELECT 1 查询验证成功。"
        if query_ok
        else "service account 尚不能运行 BigQuery 查询。"
    )
    if status == "ready":
        dataset_text = f"{dataset_id} 已可读取，当前发现 {len(table_ids)} 张表。"
        next_steps = ["运行 transaction-to-item 对账查询", "将 BigQuery 明细纳入下周老板版报告"]
    elif status == "waiting_for_tables":
        dataset_text = f"{dataset_id} 已可见，但首张事件表尚未生成。"
        next_steps = ["等待首张每日导出表生成", "表可用后运行 transaction-to-item 对账查询"]
    elif status == "needs_data_viewer":
        dataset_text = f"{dataset_id} 已存在，但 service account 尚无表读取权限。"
        next_steps = [f"仅在 {dataset_id} 数据集授予 service account BigQuery Data Viewer", "授权后运行对账查询"]
    else:
        dataset_text = f"{dataset_id} 尚未对 service account 可见。"
        next_steps = [f"等待 {dataset_id} 正式数据集生成", "生成后仅在该数据集授予 BigQuery Data Viewer"]
    return {
        "status": status,
        "tableIds": table_ids,
        "adminApiBigQueryLinks": link_text,
        "datasetProbe": dataset_text,
        "permissionGap": query_text,
        "recommendedAccess": next_steps,
    }


def first_row(data, name):
    items = rows(data, name)
    return items[0] if items else {}


def key_events_value(row):
    return row.get("keyEvents", row.get("conversions", 0))


def build_key_event_reconciliation(data):
    current_rows = [row for row in rows(data, "key_events_current") if key_events_value(row) > 0]
    previous_rows = [row for row in rows(data, "key_events_previous") if key_events_value(row) > 0]
    transactions = rows(data, "purchase_transactions_current")
    purchase_rows = [row for row in current_rows if row.get("eventName") == "purchase"]
    purchase = {
        metric: sum(row.get(metric, 0) for row in purchase_rows)
        for metric in [
            "eventCount",
            "keyEvents",
            "ecommercePurchases",
            "transactions",
            "purchaseRevenue",
            "totalRevenue",
        ]
    }
    transaction_revenue = sum(row.get("purchaseRevenue", 0) for row in transactions)
    item_revenue = sum(row.get("itemRevenue", 0) for row in rows(data, "items_current"))
    transaction_ids = {
        row.get("transactionId")
        for row in transactions
        if row.get("transactionId") and row.get("transactionId") != "(not set)"
    }
    missing_transaction_ids = sum(
        1 for row in transactions if not row.get("transactionId") or row.get("transactionId") == "(not set)"
    )
    tolerance = 0.01
    purchase_counts_match = (
        purchase["eventCount"]
        == purchase["keyEvents"]
        == purchase["ecommercePurchases"]
        == purchase["transactions"]
        == len(transaction_ids)
    )
    purchase_revenue_matches = (
        abs(purchase["purchaseRevenue"] - purchase["totalRevenue"]) <= tolerance
        and abs(purchase["purchaseRevenue"] - transaction_revenue) <= tolerance
    )
    item_revenue_matches = abs(purchase["purchaseRevenue"] - item_revenue) <= tolerance
    return {
        "current_rows": current_rows,
        "previous_rows": previous_rows,
        "transactions": transactions,
        "configured": rows(data, "configured_key_events"),
        "purchase": purchase,
        "transaction_revenue": transaction_revenue,
        "item_revenue": item_revenue,
        "unique_transaction_ids": len(transaction_ids),
        "missing_transaction_ids": missing_transaction_ids,
        "purchase_counts_match": purchase_counts_match,
        "purchase_revenue_matches": purchase_revenue_matches,
        "item_revenue_matches": item_revenue_matches,
        "available": bool(rows(data, "key_events_current") or rows(data, "key_events_previous")),
    }


def index_by(items, key):
    return {r.get(key): r for r in items}


def report_date(data):
    generated = data.get("generatedAt", "")
    try:
        return datetime.fromisoformat(generated.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return datetime.now(timezone.utc).date().isoformat()


def rel(path):
    return Path(path).relative_to(WORK).as_posix()


def chart_bar(draw, x, y, width, height, ratio, fill, outline=None):
    ratio = max(0, min(1, ratio))
    bar_w = max(3, width * ratio) if ratio > 0 else 0
    if bar_w:
        draw.rounded_rectangle((x, y, x + bar_w, y + height), radius=7, fill=fill, outline=outline or fill)
    else:
        draw.line((x, y + height / 2, x + 36, y + height / 2), fill=TOKENS["neutral"], width=4)
    return bar_w


def draw_daily_chart(data, path):
    daily = rows(data, "daily_current")
    img = new_canvas(1500, 820)
    draw = ImageDraw.Draw(img)
    cur = first_row(data, "summary_current")
    prev = first_row(data, "summary_previous")
    subtitle = (
        f"Sessions {fmt_num(cur.get('sessions', 0))}（{fmt_delta_ratio(cur.get('sessions', 0), prev.get('sessions', 0))}）；"
        f"Revenue {fmt_money(cur.get('totalRevenue', 0))}（{fmt_delta_ratio(cur.get('totalRevenue', 0), prev.get('totalRevenue', 0))}）。"
    )
    add_header(draw, "每日 sessions / revenue 趋势", subtitle, img.width)
    left, top, right, bottom = 92, 180, 1380, 640
    max_sessions = max([r.get("sessions", 0) for r in daily] + [1])
    max_revenue = max([r.get("totalRevenue", 0) for r in daily] + [1])
    draw.line((left, bottom, right, bottom), fill=TOKENS["axis"], width=2)
    for i in range(5):
        y = bottom - (bottom - top) * i / 4
        draw.line((left, y, right, y), fill=TOKENS["grid"], width=1)
        draw.text((36, y - 9), fmt_num(max_sessions * i / 4), font=font(14), fill=TOKENS["muted"])
    points = []
    n = max(1, len(daily) - 1)
    for i, row in enumerate(daily):
        x = left + (right - left) * i / n
        sessions = row.get("sessions", 0)
        revenue = row.get("totalRevenue", 0)
        y = bottom - (bottom - top) * sessions / max_sessions
        points.append((x, y))
        bar_h = (bottom - top) * revenue / max_revenue if max_revenue else 0
        draw.rounded_rectangle((x - 21, bottom - bar_h, x + 21, bottom), radius=5, fill=TOKENS["gold_light"], outline=TOKENS["gold"])
    if len(points) > 1:
        draw.line(points, fill=TOKENS["blue"], width=5)
    for (x, y), row in zip(points, daily):
        date = row.get("date", "")[5:]
        sessions = row.get("sessions", 0)
        revenue = row.get("totalRevenue", 0)
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=TOKENS["panel"], outline=TOKENS["blue"], width=3)
        draw.text((x - 22, bottom + 18), date, font=font(14), fill=TOKENS["muted"])
        draw.text((x - 15, y - 30), fmt_num(sessions), font=font(14), fill=TOKENS["ink"])
        if revenue:
            draw.text((x - 38, bottom - 42), fmt_money(revenue), font=font(14), fill=TOKENS["neutral_dark"])
    draw.text((left, 705), "蓝线=sessions；金色柱=revenue。老板看法：流量峰值与成交日是否同向，是判断承接质量的第一证据。", font=font(18), fill=TOKENS["ink"])
    img.save(path)


def draw_movement_chart(data, path):
    cur = first_row(data, "summary_current")
    prev = first_row(data, "summary_previous")
    metrics = [
        ("Sessions", cur.get("sessions", 0), prev.get("sessions", 0), "ratio"),
        ("New users", cur.get("newUsers", 0), prev.get("newUsers", 0), "ratio"),
        ("Revenue", cur.get("totalRevenue", 0), prev.get("totalRevenue", 0), "ratio"),
        ("Revenue/session", cur.get("revenuePerSession", 0), prev.get("revenuePerSession", 0), "ratio"),
        ("Engagement rate", cur.get("engagementRate", 0), prev.get("engagementRate", 0), "pp"),
        ("Avg duration", cur.get("averageSessionDuration", 0), prev.get("averageSessionDuration", 0), "ratio"),
        ("Conversions", cur.get("conversions", 0), prev.get("conversions", 0), "ratio"),
    ]
    plotted = []
    for label, c, p, mode in metrics:
        value = (c - p) if mode == "pp" else delta_ratio(c, p)
        shown = fmt_pp(value) if mode == "pp" else fmt_delta_ratio(c, p)
        plotted.append((label, value if value is not None else 0, shown))
    max_abs = max([abs(v) for _, v, _ in plotted] + [0.1])
    img = new_canvas(1500, 820)
    draw = ImageDraw.Draw(img)
    add_header(draw, "核心指标周环比", "周环比同时看流量、收入、参与度和转化，避免只用单一 KPI 判断增长质量。", img.width)
    zero, top, bar_h, gap = 735, 170, 42, 34
    left_bound, right_bound = 280, 1320
    scale = min(480, (right_bound - zero - 20) / max_abs)
    draw.line((zero, 140, zero, 700), fill=TOKENS["axis"], width=2)
    for i, (label, value, shown) in enumerate(plotted):
        y = top + i * (bar_h + gap)
        draw.text((70, y + 8), label, font=font(19), fill=TOKENS["ink"])
        color = TOKENS["green"] if value >= 0 else TOKENS["red"]
        if value >= 0:
            x1, x2 = zero, zero + value * scale
            tx = x2 + 14
        else:
            x1, x2 = zero + value * scale, zero
            tx = x1 - text_width(draw, shown, font(17)) - 14
        draw.rounded_rectangle((x1, y, x2, y + bar_h), radius=7, fill=color)
        draw.text((tx, y + 9), shown, font=font(17), fill=TOKENS["neutral_dark"])
    draw.text((70, 735), "老板看法：如果 sessions 上升但 revenue/session 下降，应优先修承接和投放质量，而不是直接加预算。", font=font(18), fill=TOKENS["ink"])
    img.save(path)


def draw_channel_chart(data, path):
    channel = rows(data, "channel_current")[:9]
    img = new_canvas(1600, 900)
    draw = ImageDraw.Draw(img)
    revenue_channels = [r for r in channel if r.get("totalRevenue", 0) > 0]
    if revenue_channels:
        top_revenue = max(revenue_channels, key=lambda r: r.get("totalRevenue", 0))
        subtitle = f"收入主要来自 {top_revenue.get('sessionDefaultChannelGroup', '(not set)')}；Paid 渠道有访问但收入承接仍弱。"
    else:
        subtitle = "本周主要渠道均未记录收入；Paid 与 Direct 有访问但没有 revenue，需要优先排查承接和归因。"
    add_header(draw, "渠道 sessions / revenue 分布", subtitle, img.width)
    left, top, mid, right = 350, 170, 1010, 1450
    max_sessions = max([r.get("sessions", 0) for r in channel] + [1])
    max_revenue = max([r.get("totalRevenue", 0) for r in channel] + [1])
    draw.text((left, 130), "Sessions", font=font(18), fill=TOKENS["muted"])
    draw.text((mid, 130), "Revenue", font=font(18), fill=TOKENS["muted"])
    for i, row in enumerate(channel):
        y = top + i * 72
        name = row.get("sessionDefaultChannelGroup", "(not set)")
        draw_wrapped(draw, (62, y + 5), name, font(18), TOKENS["ink"], 250, 3, max_lines=2)
        sw = chart_bar(draw, left, y, 560, 42, row.get("sessions", 0) / max_sessions, TOKENS["blue_light"], TOKENS["blue"])
        draw.text((left + sw + 12, y + 10), fmt_num(row.get("sessions", 0)), font=font(15), fill=TOKENS["neutral_dark"])
        rw = chart_bar(draw, mid, y, right - mid - 80, 42, row.get("totalRevenue", 0) / max_revenue, TOKENS["gold_light"], TOKENS["gold"])
        draw.text((mid + rw + 12, y + 10), fmt_money(row.get("totalRevenue", 0)), font=font(15), fill=TOKENS["neutral_dark"])
    draw.text((62, 830), "老板看法：渠道预算判断必须看 revenue/session；只有流量没有收入的渠道要先查落地页和追踪。", font=font(18), fill=TOKENS["ink"])
    img.save(path)


def paid_landing_rows(data):
    candidates = []
    for row in rows(data, "landing_channel_current"):
        channel = row.get("sessionDefaultChannelGroup", "")
        paid = "Paid" in channel or "Cross-network" in channel
        if not paid:
            continue
        sessions = row.get("sessions", 0)
        revenue = row.get("totalRevenue", 0)
        cvr = row.get("conversions", 0) / sessions if sessions else 0
        if sessions >= 3 and (revenue == 0 or cvr < 0.01):
            candidates.append(row)
    return candidates[:8]


def paid_channel_diagnosis(data):
    paid_rows = [
        row
        for row in rows(data, "channel_current")
        if row.get("sessions", 0) > 0
        and (
            "Paid" in row.get("sessionDefaultChannelGroup", "")
            or row.get("sessionDefaultChannelGroup") in {"Display", "Cross-network"}
        )
    ]
    zero_revenue = [row for row in paid_rows if row.get("totalRevenue", 0) == 0]
    if zero_revenue:
        names = "、".join(row.get("sessionDefaultChannelGroup", "(not set)") for row in zero_revenue[:3])
        evidence = "；".join(
            f"{row.get('sessionDefaultChannelGroup', '(not set)')} {fmt_num(row.get('sessions', 0))} sessions / {fmt_money(row.get('totalRevenue', 0))}"
            for row in zero_revenue[:4]
        )
        return {
            "title": f"{names} 有流量但没有收入，需先区分承接问题与归因缺失。",
            "evidence": evidence,
            "action": "先暂停扩量，复查关键词、商品 feed、落地页、checkout 和 purchase revenue 回传。",
        }
    if paid_rows:
        weakest = min(
            paid_rows,
            key=lambda row: row.get("totalRevenue", 0) / max(row.get("sessions", 0), 1),
        )
        revenue_per_session = weakest.get("totalRevenue", 0) / max(weakest.get("sessions", 0), 1)
        return {
            "title": f"付费渠道已有收入，但 {weakest.get('sessionDefaultChannelGroup', '(not set)')} 的 revenue/session 最低。",
            "evidence": (
                f"{weakest.get('sessionDefaultChannelGroup', '(not set)')} "
                f"{fmt_num(weakest.get('sessions', 0))} sessions / {fmt_money(weakest.get('totalRevenue', 0))} revenue / "
                f"{fmt_money(revenue_per_session)} revenue per session"
            ),
            "action": "保留可验证的收入来源，优先优化最低 revenue/session 渠道的受众、落地页和结账路径。",
        }
    return {
        "title": "本周没有足够的付费渠道样本可判断投放效率。",
        "evidence": "GA4 未观察到可分析的 Paid、Display 或 Cross-network 会话。",
        "action": "先确认广告流量是否正确进入 GA4，再决定预算动作。",
    }


def campaign_action(row):
    if not row or row.get("sessions", 0) == 0:
        return "本周没有可分析的 google / cpc campaign；先确认 auto-tagging、UTM 和渠道归类。"
    if row.get("totalRevenue", 0) == 0:
        return "先暂停扩量，排查关键词、商品 feed、落地页、checkout 和收入回传。"
    revenue_per_session = row.get("totalRevenue", 0) / max(row.get("sessions", 0), 1)
    return f"已记录收入，按 {fmt_money(revenue_per_session)} revenue/session 与其他 campaign 比较后再调整预算。"


def draw_paid_landing_chart(data, path):
    paid = paid_landing_rows(data)
    has_risk_rows = bool(paid)
    if not paid:
        paid = rows(data, "landing_channel_current")[:5]
    img = new_canvas(1600, 940)
    draw = ImageDraw.Draw(img)
    subtitle = (
        "清单只保留有流量且 0 收入或低转化的付费页面；优先复查排名靠前的购买路径与追踪。"
        if has_risk_rows
        else "本周未形成符合阈值的付费风险页，图中回退展示流量最高页面供人工复核。"
    )
    add_header(draw, "付费落地页：高流量 0 收入 / 低转化清单", subtitle, img.width)
    left, top, right = 680, 172, 1450
    max_sessions = max([r.get("sessions", 0) for r in paid] + [1])
    for i, row in enumerate(paid):
        y = top + i * 86
        label = f"{row.get('sessionDefaultChannelGroup', '')} | {clean_page(row.get('landingPagePlusQueryString', ''))}"
        draw_wrapped(draw, (60, y - 8), label, font(16), TOKENS["ink"], 570, 4, max_lines=3)
        w = chart_bar(draw, left, y, right - left - 150, 46, row.get("sessions", 0) / max_sessions, TOKENS["orange_light"], TOKENS["orange"])
        note = f"{fmt_num(row.get('sessions', 0))} sessions | {fmt_pct(row.get('engagementRate', 0))} ER | {fmt_money(row.get('totalRevenue', 0))}"
        draw.text((left + w + 14, y + 12), note, font=font(15), fill=TOKENS["neutral_dark"])
    draw.text((60, 865), "老板看法：这张图不是装饰，它指出付费预算最先该复盘的 URL，而不是泛泛说广告效果差。", font=font(18), fill=TOKENS["ink"])
    img.save(path)


def aggregate_device_funnel(data, result_name):
    out = {}
    for row in rows(data, result_name):
        device = row.get("deviceCategory")
        event_name = row.get("eventName")
        if device and event_name:
            out.setdefault(device, {})
            out[device][event_name] = out[device].get(event_name, 0) + row.get("eventCount", 0)
    return out


def device_funnel(data):
    out = aggregate_device_funnel(data, "event_device_current")
    out.setdefault("mobile", {})
    out.setdefault("desktop", {})
    return out


def device_event(funnel, device, event_name):
    return funnel.get(device, {}).get(event_name, 0)


def draw_device_funnel_chart(data, path):
    funnel = device_funnel(data)
    stages = [("view_item", "View item"), ("add_to_cart", "Add to cart"), ("begin_checkout", "Begin checkout"), ("purchase", "Purchase")]
    img = new_canvas(1500, 820)
    draw = ImageDraw.Draw(img)
    mobile_views = device_event(funnel, "mobile", "view_item")
    desktop_views = device_event(funnel, "desktop", "view_item")
    mobile_purchase = device_event(funnel, "mobile", "purchase")
    desktop_purchase = device_event(funnel, "desktop", "purchase")
    add_header(
        draw,
        "mobile vs desktop 商品漏斗",
        f"Mobile {fmt_num(mobile_views)} 次 view_item / {fmt_num(mobile_purchase)} 次 purchase；Desktop {fmt_num(desktop_views)} 次 view_item / {fmt_num(desktop_purchase)} 次 purchase。",
        img.width,
    )
    max_value = max([funnel[d].get("view_item", 0) for d in funnel] + [1])
    for device_idx, device in enumerate(["mobile", "desktop"]):
        x0 = 125 + device_idx * 700
        draw.text((x0, 150), device.title(), font=font(26), fill=TOKENS["ink"])
        for i, (key, label) in enumerate(stages):
            value = funnel[device].get(key, 0)
            y = 210 + i * 112
            draw.text((x0, y - 28), label, font=font(16), fill=TOKENS["muted"])
            color = TOKENS["blue"] if device == "desktop" else TOKENS["orange"]
            w = chart_bar(draw, x0, y, 360, 46, value / max_value, color if value else TOKENS["neutral"], color if value else TOKENS["neutral"])
            draw.text((x0 + w + 16, y + 11), fmt_num(value), font=font(18), fill=TOKENS["neutral_dark"])
        view = funnel[device].get("view_item", 0)
        purchase = funnel[device].get("purchase", 0)
        rate = purchase / view if view else 0
        draw.text((x0, 700), f"View-to-purchase: {fmt_pct(rate, 2)}", font=font(19), fill=TOKENS["ink"])
    draw.text((125, 760), "老板看法：漏斗要同时看加购、结账和购买事件；若 paid 流量无收入，需复测真实下单和事件回传。", font=font(18), fill=TOKENS["ink"])
    img.save(path)


def draw_item_chart(data, path):
    item_rows = [r for r in rows(data, "items_current") if r.get("itemsViewed", 0) > 0][:10]
    img = new_canvas(1700, 1040)
    draw = ImageDraw.Draw(img)
    zero_atc = sum(1 for r in item_rows if r.get("itemsViewed", 0) >= 7 and r.get("itemsAddedToCart", 0) == 0)
    total_item_revenue = sum(r.get("itemRevenue", 0) for r in item_rows)
    add_header(
        draw,
        "商品浏览 / 加购 / 购买表现",
        f"前 10 个高浏览商品中 {zero_atc} 个没有加购；可见 itemRevenue {fmt_money(total_item_revenue)}，仍需核对商品级收入完整性。",
        img.width,
    )
    left, top, right = 760, 168, 1510
    max_views = max([r.get("itemsViewed", 0) for r in item_rows] + [1])
    for i, row in enumerate(item_rows):
        y = top + i * 78
        label = re.sub(r"^COZY\s+", "", row.get("itemName", ""))
        draw_wrapped(draw, (55, y - 12), label, font(15), TOKENS["ink"], 630, 3, max_lines=3)
        vw = chart_bar(draw, left, y, right - left, 34, row.get("itemsViewed", 0) / max_views, TOKENS["blue_light"], TOKENS["blue"])
        atc_w = chart_bar(draw, left, y + 43, right - left, 12, row.get("itemsAddedToCart", 0) / max_views, TOKENS["gold"], TOKENS["gold"])
        if row.get("itemsPurchased", 0):
            chart_bar(draw, left, y + 61, right - left, 10, row.get("itemsPurchased", 0) / max_views, TOKENS["green"], TOKENS["green"])
        atc_rate = row.get("itemsAddedToCart", 0) / row.get("itemsViewed", 1)
        note = f"{fmt_num(row.get('itemsViewed', 0))} views | {fmt_num(row.get('itemsAddedToCart', 0))} ATC | {fmt_pct(atc_rate)}"
        draw.text((left + max(vw, atc_w) + 12, y + 7), note, font=font(14), fill=TOKENS["neutral_dark"])
    draw.text((55, 955), "蓝色=浏览，金色=加购，绿色=购买。老板看法：先修高浏览低加购 SKU，比平均改全站更快见效。", font=font(18), fill=TOKENS["ink"])
    img.save(path)


def seo_opportunity_rows(data):
    source_rows = rows(data, "referral_ai_current")
    page_rows = rows(data, "pages_current")
    selected = []
    for row in source_rows:
        selected.append((row.get("sessionSourceMedium", ""), row.get("sessions", 0), row.get("totalRevenue", 0), "source"))
    for row in page_rows:
        path = row.get("pagePath", "")
        if any(token in path for token in ["/collections/", "/blogs/", "glass-shower", "smart-toilet", "led-mirror", "towel"]):
            selected.append((clean_page(path), row.get("sessions", 0), row.get("totalRevenue", 0), "page"))
    selected.sort(key=lambda x: x[1], reverse=True)
    return selected[:8]


def draw_seo_chart(data, path):
    opps = seo_opportunity_rows(data)
    img = new_canvas(1550, 900)
    draw = ImageDraw.Draw(img)
    source_map = index_by(rows(data, "source_medium_current"), "sessionSourceMedium")
    google = source_map.get("google / organic", {})
    chatgpt_sessions = sum(r.get("sessions", 0) for r in rows(data, "source_medium_current") if "chatgpt" in r.get("sessionSourceMedium", "").lower())
    add_header(
        draw,
        "SEO / 内容页 / Referral / AI 来源机会",
        f"Google organic {fmt_num(google.get('sessions', 0))} sessions / {fmt_money(google.get('totalRevenue', 0))}；ChatGPT 相关来源 {fmt_num(chatgpt_sessions)} sessions。",
        img.width,
    )
    left, top, right = 610, 170, 1400
    max_sessions = max([r[1] for r in opps] + [1])
    for i, (name, sessions, revenue, kind) in enumerate(opps):
        y = top + i * 78
        draw_wrapped(draw, (60, y - 5), f"{kind} | {name}", font(16), TOKENS["ink"], 500, 4, max_lines=2)
        color = TOKENS["green_light"] if kind == "source" else TOKENS["blue_light"]
        outline = TOKENS["green"] if kind == "source" else TOKENS["blue"]
        w = chart_bar(draw, left, y, right - left - 120, 42, sessions / max_sessions, color, outline)
        draw.text((left + w + 14, y + 10), f"{fmt_num(sessions)} sessions | {fmt_money(revenue)}", font=font(15), fill=TOKENS["neutral_dark"])
    draw.text((60, 820), "老板看法：自然搜索和 AI/referral 已有需求信号，但需要把高意图页面接到商品推荐和咨询/下单 CTA。", font=font(18), fill=TOKENS["ink"])
    img.save(path)


def health_findings(data):
    channel_map = index_by(rows(data, "channel_current"), "sessionDefaultChannelGroup")
    source_map = index_by(rows(data, "source_medium_current"), "sessionSourceMedium")
    direct = channel_map.get("Direct", {})
    unassigned = channel_map.get("Unassigned", {})
    not_set = source_map.get("(not set)", {})
    admin = source_map.get("admin.shopify.com / referral", {})
    self_ref_key = f"{SITE_DOMAIN} / referral" if SITE_DOMAIN else None
    self_ref = source_map.get(self_ref_key, {}) if self_ref_key else {}
    zero_revenue_conversions = [r for r in rows(data, "daily_current") if r.get("conversions", 0) > 0 and r.get("totalRevenue", 0) == 0]
    campaigns = [r.get("sessionCampaignName", "") for r in rows(data, "campaign_current") if r.get("sessionSourceMedium") == "google / cpc"]
    naming_patterns = sorted({c.split("_")[0] if "_" in c else c.split("|")[0].strip() for c in campaigns if c and c != "(not set)"})
    return {
        "direct": direct,
        "unassigned": unassigned,
        "not_set": not_set,
        "admin": admin,
        "self_ref": self_ref,
        "self_ref_label": SITE_DOMAIN or "站点域名未提供",
        "zero_revenue_conversions": zero_revenue_conversions,
        "naming_patterns": naming_patterns,
    }


def build_chart_map(charts):
    return [
        {"section": "Executive Summary 后的趋势证据", "chart": rel(charts["daily"]), "type": "line + bar", "claim": "每日 sessions 与 revenue 是否同步，判断流量承接质量。", "source_fields": ["daily_current.date", "sessions", "totalRevenue"]},
        {"section": "核心指标周环比", "chart": rel(charts["movement"]), "type": "diverging bar", "claim": "核心指标方向分化，需要同时判断流量、收入和承接效率。", "source_fields": ["summary_current", "summary_previous"]},
        {"section": "渠道效率诊断", "chart": rel(charts["channel"]), "type": "horizontal bar", "claim": "渠道 revenue/session 差异明显，Paid 有访问但收入承接弱。", "source_fields": ["channel_current"]},
        {"section": "付费落地页清单", "chart": rel(charts["paid_landing"]), "type": "ranked bar", "claim": "定位高流量 0 收入或低转化 paid landing pages。", "source_fields": ["landing_channel_current"]},
        {"section": "mobile vs desktop 漏斗", "chart": rel(charts["device"]), "type": "funnel bars", "claim": "设备端 ecommerce event 漏斗存在效率和追踪问题。", "source_fields": ["event_device_current"]},
        {"section": "商品漏斗", "chart": rel(charts["items"]), "type": "ranked bar", "claim": "高浏览商品加购不足，且商品收入追踪需要确认。", "source_fields": ["items_current"]},
        {"section": "SEO/内容页/Referral/AI 机会", "chart": rel(charts["seo"]), "type": "ranked bar", "claim": "自然搜索和 AI/referral 已有样本，但内容页未变现。", "source_fields": ["referral_ai_current", "pages_current"]},
    ]


def table_rows(items, columns):
    body = []
    for row in items:
        cells = []
        for label, getter in columns:
            value = getter(row)
            cells.append(f"<td>{html.escape(str(value))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return "\n".join(body) or f"<tr><td colspan=\"{len(columns)}\">本类数据本周没有可用样本。</td></tr>"


def build_shopify_html(recon):
    if not recon:
        return ""
    summary = recon.get("summary", {})
    bq = recon.get("bigQueryStatus", {})
    bq_next_steps = "；".join(bq.get("recommendedAccess", [])) or "等待下一轮探测。"
    if not summary:
        stale_range = recon.get("dateRange", {}).get("current", {})
        stale_note = (
            f"现有 Shopify 对账文件属于 {stale_range.get('startDate')} 至 {stale_range.get('endDate')}，"
            "与本期窗口不一致，已排除。"
            if recon.get("staleShopifyReconciliation")
            else "本期尚未生成 Shopify 订单明细对账文件。"
        )
        detail_gap = (
            "BigQuery Export 已可读取，但本轮尚未执行逐单 transaction-to-item 查询；需要运行该查询或补充本期 Shopify 导出。"
            if bq.get("status") == "ready"
            else "逐单 SKU、税费、运费、退款需补充本期 Shopify 导出，或等待 BigQuery Export 可读后再对账。"
        )
        return f"""
  <h3>Shopify 订单真值核验</h3>
  <p><strong>本期 Shopify 明细未接入核验：</strong>{html.escape(stale_note)}本周只能用 GA4 purchase transaction 与 itemRevenue 做内部一致性检查；{html.escape(detail_gap)}</p>
  <p><strong>BigQuery Export 状态：</strong>{html.escape(bq.get('adminApiBigQueryLinks', '未探测'))} {html.escape(bq.get('datasetProbe', ''))} {html.escape(bq.get('permissionGap', ''))} 下一步：{html.escape(bq_next_steps)}</p>
"""
    orders = recon.get("orders", [])
    exception_orders = [order for order in orders if order.get("exception")]
    order_rows = []
    for order in orders:
        items = "; ".join(
            f"{item.get('sku', '')} x{item.get('quantity', 0)}"
            for item in order.get("lineItems", [])
        )
        status = order.get("exception", {}).get("type", "matched")
        order_rows.append(
            "<tr>"
            f"<td>{html.escape(order.get('orderName', ''))}</td>"
            f"<td>{html.escape(order.get('transactionId', ''))}</td>"
            f"<td>{html.escape(order.get('ga4Channel', ''))}</td>"
            f"<td>{fmt_money(order.get('ga4PurchaseRevenue', 0))}</td>"
            f"<td>{fmt_money(order.get('shopifyCurrentTotal', 0))}</td>"
            f"<td>{html.escape(items)}</td>"
            f"<td>{html.escape(status)}</td>"
            "</tr>"
        )
    exception_note = "；".join(
        f"{order.get('orderName')} {order.get('exception', {}).get('details', '')}"
        for order in exception_orders
    ) or "本周未发现 GA4 transaction 与 Shopify 当前订单金额不一致。"
    transaction_count = summary.get("ga4PurchaseTransactions", len(orders))
    return f"""
  <h3>Shopify 订单真值核验</h3>
  <p><strong>Shopify 明细已接入本轮核验：</strong>GA4 {fmt_num(transaction_count)} 个 purchase transaction ID 全部匹配 Shopify 订单；GA4 purchaseRevenue 合计 {fmt_money(summary.get('matchedRevenueByGa4PurchaseRevenue', 0))}，Shopify 原始订单金额合计 {fmt_money(summary.get('shopifyOriginalTotalPrice', 0))}，当前订单金额合计 {fmt_money(summary.get('shopifyCurrentTotalPrice', 0))}。差异主要来自待处理退款/移除商品：{html.escape(exception_note)}</p>
  <table>
    <thead><tr><th>Order</th><th>Transaction ID</th><th>GA4 channel</th><th>GA4 revenue</th><th>Shopify current total</th><th>Line items</th><th>Status</th></tr></thead>
    <tbody>{"".join(order_rows)}</tbody>
  </table>
  <p><strong>BigQuery Export 状态：</strong>{html.escape(bq.get('adminApiBigQueryLinks', '未探测'))} {html.escape(bq.get('datasetProbe', ''))} {html.escape(bq.get('permissionGap', ''))} 下一步：{html.escape(bq_next_steps)}</p>
"""


def build_shopify_markdown(recon):
    if not recon:
        return ""
    summary = recon.get("summary", {})
    bq = recon.get("bigQueryStatus", {})
    bq_next_steps = "；".join(bq.get("recommendedAccess", [])) or "等待下一轮探测。"
    if not summary:
        stale_range = recon.get("dateRange", {}).get("current", {})
        stale_note = (
            f"现有 Shopify 对账文件属于 `{stale_range.get('startDate')}` 至 `{stale_range.get('endDate')}`，与本期窗口不一致，已排除。"
            if recon.get("staleShopifyReconciliation")
            else "本期尚未生成 Shopify 订单明细对账文件。"
        )
        detail_gap = (
            "BigQuery Export 已可读取，但本轮尚未执行逐单 transaction-to-item 查询；需要运行该查询或补充本期 Shopify 导出。"
            if bq.get("status") == "ready"
            else "逐单 SKU、税费、运费、退款需补充本期 Shopify 导出，或等待 BigQuery Export 可读后再对账。"
        )
        return "\n".join([
            "## Shopify 订单真值核验",
            "",
            f"- 本期 Shopify 明细未接入核验：{stale_note}",
            f"- 本周只能用 GA4 purchase transaction 与 itemRevenue 做内部一致性检查；{detail_gap}",
            f"- BigQuery Export 状态：{bq.get('adminApiBigQueryLinks', '未探测')} {bq.get('datasetProbe', '')} {bq.get('permissionGap', '')}",
            f"- 下一步：{bq_next_steps}",
            "",
        ])
    lines = [
        "## Shopify 订单真值核验",
        "",
        f"- GA4 purchase transaction ID `{summary.get('ga4PurchaseTransactions', 0)}` 个，Shopify 匹配订单 `{summary.get('shopifyMatchedOrders', 0)}` 个。",
        f"- GA4 purchaseRevenue `{fmt_money(summary.get('matchedRevenueByGa4PurchaseRevenue', 0))}`；Shopify 原始订单金额 `{fmt_money(summary.get('shopifyOriginalTotalPrice', 0))}`；Shopify 当前订单金额 `{fmt_money(summary.get('shopifyCurrentTotalPrice', 0))}`。",
        f"- 待处理退款/当前订单金额差异 `{fmt_money(summary.get('pendingRefundImpact', 0))}`。",
        "",
        "| Order | Transaction ID | GA4 channel | GA4 revenue | Shopify current total | Line items | Status |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for order in recon.get("orders", []):
        items = "; ".join(
            f"{item.get('sku', '')} x{item.get('quantity', 0)}"
            for item in order.get("lineItems", [])
        )
        status = order.get("exception", {}).get("type", "matched")
        lines.append(
            f"| {order.get('orderName', '')} | {order.get('transactionId', '')} | {order.get('ga4Channel', '')} | "
            f"{fmt_money(order.get('ga4PurchaseRevenue', 0))} | {fmt_money(order.get('shopifyCurrentTotal', 0))} | {items} | {status} |"
        )
    lines.extend([
        "",
        f"BigQuery Export 状态：{bq.get('adminApiBigQueryLinks', '未探测')} {bq.get('datasetProbe', '')} {bq.get('permissionGap', '')}",
        f"下一步：{bq_next_steps}",
        "",
    ])
    return "\n".join(lines)


def build_html(data, charts):
    cur = first_row(data, "summary_current")
    prev = first_row(data, "summary_previous")
    current = data["dateRanges"]["current"]
    previous = data["dateRanges"]["previous"]
    property_id = data.get("propertyId", "unknown")
    shopify_recon = load_shopify_reconciliation(data)
    shopify_section = build_shopify_html(shopify_recon)
    tz = data.get("propertyTimeZone", "unknown")
    generated = data.get("generatedAt", "")
    health = health_findings(data)
    paid_search = index_by(rows(data, "channel_current"), "sessionDefaultChannelGroup").get("Paid Search", {})
    paid_shopping = index_by(rows(data, "channel_current"), "sessionDefaultChannelGroup").get("Paid Shopping", {})
    direct = health["direct"]
    daily = rows(data, "daily_current")
    top_session_day = max(daily, key=lambda r: r.get("sessions", 0)) if daily else {}
    top_revenue_day = max(daily, key=lambda r: r.get("totalRevenue", 0)) if daily else {}
    zero_rev_dates = [ymd_zh(r.get("date", "")) for r in health["zero_revenue_conversions"]]
    zero_rev_note = "、".join(zero_rev_dates) if zero_rev_dates else "本周未观察到"
    sessions_delta = fmt_delta_ratio(cur.get("sessions", 0), prev.get("sessions", 0))
    revenue_delta = fmt_delta_ratio(cur.get("totalRevenue", 0), prev.get("totalRevenue", 0))
    rps_delta = fmt_delta_ratio(cur.get("revenuePerSession", 0), prev.get("revenuePerSession", 0))
    if prev.get("totalRevenue", 0) == 0 and cur.get("totalRevenue", 0) > 0:
        revenue_change_note = f"从 {fmt_money(prev.get('totalRevenue', 0))} 恢复"
    else:
        revenue_change_note = revenue_delta
    if prev.get("revenuePerSession", 0) == 0 and cur.get("revenuePerSession", 0) > 0:
        rps_change_note = f"从 {fmt_money(prev.get('revenuePerSession', 0))} 恢复至 {fmt_money(cur.get('revenuePerSession', 0))}"
        rps_card_note = f"从 {fmt_money(prev.get('revenuePerSession', 0))} 恢复"
    else:
        rps_change_note = rps_delta
        rps_card_note = rps_delta
    engagement_pp = fmt_pp(cur.get("engagementRate", 0) - prev.get("engagementRate", 0))
    duration_delta = fmt_delta_ratio(cur.get("averageSessionDuration", 0), prev.get("averageSessionDuration", 0))
    paid_rows = paid_landing_rows(data)[:6]
    campaign = [r for r in rows(data, "campaign_current") if r.get("sessionSourceMedium") == "google / cpc"][:8]
    best_cpc = max(campaign, key=lambda r: r.get("sessions", 0), default={})
    best_cpc_name = best_cpc.get("sessionCampaignName", "最高流量 Google CPC campaign")
    paid_diagnosis = paid_channel_diagnosis(data)
    campaign_action_note = campaign_action(best_cpc)
    source_map = index_by(rows(data, "source_medium_current"), "sessionSourceMedium")
    channel_map = index_by(rows(data, "channel_current"), "sessionDefaultChannelGroup")
    organic_search = channel_map.get("Organic Search", {})
    revenue_channels = [r for r in rows(data, "channel_current") if r.get("totalRevenue", 0) > 0]
    top_revenue_note = "、".join(
        f"{r.get('sessionDefaultChannelGroup', '(not set)')} {fmt_money(r.get('totalRevenue', 0))}"
        for r in sorted(revenue_channels, key=lambda row: row.get("totalRevenue", 0), reverse=True)[:3]
    ) or "本周无可用收入渠道样本"
    google_organic = source_map.get("google / organic", {})
    bing_organic = source_map.get("bing / organic", {})
    chatgpt_sessions = sum(r.get("sessions", 0) for r in rows(data, "source_medium_current") if "chatgpt" in r.get("sessionSourceMedium", "").lower())
    youtube_sessions = sum(r.get("sessions", 0) for r in rows(data, "source_medium_current") if "youtube" in r.get("sessionSourceMedium", "").lower())
    reddit_sessions = sum(r.get("sessions", 0) for r in rows(data, "source_medium_current") if "reddit" in r.get("sessionSourceMedium", "").lower())
    pinterest_sessions = sum(r.get("sessions", 0) for r in rows(data, "source_medium_current") if "pinterest" in r.get("sessionSourceMedium", "").lower())
    funnel = device_funnel(data)
    mobile_views = device_event(funnel, "mobile", "view_item")
    mobile_atc = device_event(funnel, "mobile", "add_to_cart")
    mobile_checkout = device_event(funnel, "mobile", "begin_checkout")
    mobile_purchase = device_event(funnel, "mobile", "purchase")
    desktop_views = device_event(funnel, "desktop", "view_item")
    desktop_atc = device_event(funnel, "desktop", "add_to_cart")
    desktop_checkout = device_event(funnel, "desktop", "begin_checkout")
    desktop_purchase = device_event(funnel, "desktop", "purchase")
    mobile = index_by(rows(data, "device_current"), "deviceCategory").get("mobile", {})
    desktop = index_by(rows(data, "device_current"), "deviceCategory").get("desktop", {})
    if mobile.get("engagementRate", 0) < desktop.get("engagementRate", 0):
        device_engagement_note = f"低于 Desktop {fmt_pct(desktop.get('engagementRate', 0))}"
    elif mobile.get("engagementRate", 0) > desktop.get("engagementRate", 0):
        device_engagement_note = f"高于 Desktop {fmt_pct(desktop.get('engagementRate', 0))}"
    else:
        device_engagement_note = f"与 Desktop 持平（{fmt_pct(desktop.get('engagementRate', 0))}）"
    item_rows = [r for r in rows(data, "items_current") if r.get("itemsViewed", 0) > 0]
    top_item = max(item_rows, key=lambda r: r.get("itemsViewed", 0), default={})
    top_content_page = max(
        rows(data, "pages_current"),
        key=lambda row: row.get("screenPageViews", 0),
        default={},
    )
    content_action_target = clean_page(top_content_page.get("pagePath", "最高流量内容页"))
    high_view_zero_atc = [r for r in item_rows[:10] if r.get("itemsViewed", 0) >= 7 and r.get("itemsAddedToCart", 0) == 0]
    item_revenue = sum(r.get("itemRevenue", 0) for r in item_rows)
    paid_total_sessions = paid_search.get("sessions", 0) + paid_shopping.get("sessions", 0)
    paid_total_revenue = paid_search.get("totalRevenue", 0) + paid_shopping.get("totalRevenue", 0)
    direct_interpretation = (
        "收入为 0，需确认广告点击、checkout、支付跳转是否丢 referrer。"
        if direct.get("sessions", 0) > 0 and direct.get("totalRevenue", 0) == 0
        else "已有收入记录，仍需结合 transaction 和来源丢失情况判断是否存在归因膨胀。"
    )
    organic_interpretation = (
        "自然搜索已产生收入，继续放大高意图页面的商品与 CTA 承接。"
        if google_organic.get("totalRevenue", 0) > 0
        else "自然搜索本周尚未产生可见收入，优先核对高流量页面意图与转化入口。"
    )
    session_direction = "下降" if cur.get("sessions", 0) < prev.get("sessions", 0) else "增长"
    if prev.get("totalRevenue", 0) == 0 and cur.get("totalRevenue", 0) > 0:
        revenue_sentence = f"Revenue 从 {fmt_money(prev.get('totalRevenue', 0))} 恢复至 {fmt_money(cur.get('totalRevenue', 0))}"
    else:
        revenue_sentence = f"Revenue 从 {fmt_money(prev.get('totalRevenue', 0))} 变为 {fmt_money(cur.get('totalRevenue', 0))}（{revenue_delta}）"
    if cur.get("sessions", 0) < prev.get("sessions", 0) and cur.get("totalRevenue", 0) > prev.get("totalRevenue", 0):
        conclusion = f"本周不是流量扩张，而是成交恢复：访问减少，但收入集中在 {top_revenue_note}。"
    elif cur.get("sessions", 0) > prev.get("sessions", 0) and cur.get("totalRevenue", 0) < prev.get("totalRevenue", 0):
        conclusion = "本周流量增长但收入走弱，增长质量没有跟上。"
    else:
        conclusion = "本周核心信号是流量、收入和转化效率方向分化，需要看渠道承接而不是只看总量。"
    paid_landing_note = paid_rows[0] if paid_rows else {}
    if mobile_purchase > 0 and desktop_purchase == 0:
        device_purchase_note = f"purchase 全部来自 Mobile；Desktop 有 {fmt_num(desktop_checkout)} 次 begin_checkout 但 0 次 purchase"
    elif mobile_purchase == 0 and desktop_purchase > 0:
        device_purchase_note = f"purchase 全部来自 Desktop；Mobile 有 {fmt_num(mobile_checkout)} 次 begin_checkout 但 0 次 purchase"
    else:
        device_purchase_note = f"Mobile {fmt_num(mobile_purchase)} 次 purchase，Desktop {fmt_num(desktop_purchase)} 次 purchase"
    reconciliation = build_key_event_reconciliation(data)
    purchase = reconciliation["purchase"]
    current_key_event_total = sum(key_events_value(row) for row in reconciliation["current_rows"])
    previous_key_event_total = sum(key_events_value(row) for row in reconciliation["previous_rows"])
    current_key_event_names = "、".join(
        f"{row.get('eventName', '(not set)')} {fmt_num(key_events_value(row))}"
        for row in reconciliation["current_rows"]
    ) or "无"
    previous_key_event_names = "、".join(
        f"{row.get('eventName', '(not set)')} {fmt_num(key_events_value(row))}"
        for row in reconciliation["previous_rows"]
    ) or "无"
    configured_names = "、".join(row.get("eventName", "(not set)") for row in reconciliation["configured"]) or "Admin API 未返回可用配置"
    if reconciliation["available"]:
        key_event_statement = (
            f"本周 {fmt_num(current_key_event_total)} 次 key events：{current_key_event_names}；"
            f"对比期 {fmt_num(previous_key_event_total)} 次：{previous_key_event_names}。"
        )
    else:
        key_event_statement = "事件级 key-event 查询不可用，不能把汇总 key events 直接解释为订单。"
    if purchase["ecommercePurchases"]:
        count_status = "一致" if reconciliation["purchase_counts_match"] else "不一致，需排查重复或缺失 transaction_id"
        revenue_status = "一致" if reconciliation["purchase_revenue_matches"] else "不一致，需核对 purchase value、退款或重复上报"
        item_status = "一致" if reconciliation["item_revenue_matches"] else "不一致，需核对税费、运费、退款和 item 参数"
        reconciliation_statement = (
            f"Purchase event、key events、ecommerce purchases、transactions 与唯一 transaction ID 数量{count_status}；"
            f"purchaseRevenue、totalRevenue 与交易明细合计{revenue_status}；itemRevenue 与 purchaseRevenue {item_status}。"
        )
    else:
        reconciliation_statement = "本周未观测到 purchase；非收入 key event 只能作为微转化，不能解释为订单。"
    key_event_table = "\n".join(
        f"<tr><td>{period}</td><td>{html.escape(row.get('eventName', '(not set)'))}</td>"
        f"<td>{fmt_num(key_events_value(row))}</td><td>{fmt_num(row.get('eventCount', 0))}</td>"
        f"<td>{fmt_money(row.get('eventValue', 0))}</td><td>{fmt_money(row.get('purchaseRevenue', 0))}</td>"
        f"<td>{'订单' if row.get('eventName') == 'purchase' else '非收入微转化' if not row.get('purchaseRevenue', 0) else '收入事件'}</td></tr>"
        for period, event_rows in [("本周", reconciliation["current_rows"]), ("对比期", reconciliation["previous_rows"])]
        for row in event_rows
    ) or '<tr><td colspan="7">事件级 key-event 数据不可用。</td></tr>'
    transaction_table = "\n".join(
        f"<tr><td>{html.escape(row.get('date', ''))}</td><td>{html.escape(row.get('transactionId', '(not set)'))}</td>"
        f"<td>{html.escape(row.get('deviceCategory', ''))}</td><td>{html.escape(row.get('sessionDefaultChannelGroup', ''))}</td>"
        f"<td>{html.escape(row.get('sessionSourceMedium', ''))}</td><td>{fmt_money(row.get('purchaseRevenue', 0))}</td></tr>"
        for row in reconciliation["transactions"][:20]
    ) or '<tr><td colspan="6">本周无 purchase 交易明细。</td></tr>'
    css = """
    :root { --ink:#1f2430; --muted:#667085; --line:#e6e8f0; --panel:#fff; --surface:#fbfcfd; --blue:#3e6fb6; --orange:#c9613d; --green:#4f8a57; }
    body { margin:0; background:var(--surface); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Arial Unicode MS",sans-serif; }
    main { max-width:1160px; margin:0 auto; padding:42px 28px 72px; }
    h1 { font-size:34px; margin:0 0 10px; letter-spacing:0; }
    h2 { font-size:23px; margin:38px 0 12px; letter-spacing:0; }
    h3 { font-size:18px; margin:24px 0 10px; letter-spacing:0; }
    p, li { font-size:16px; line-height:1.72; }
    .meta { color:var(--muted); font-size:14px; margin-bottom:22px; }
    .summary { border-left:5px solid var(--orange); padding:10px 0 10px 18px; background:#fff; }
    .cards { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:22px 0 30px; }
    .card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }
    .label { color:var(--muted); font-size:13px; margin-bottom:6px; }
    .value { font-size:26px; font-weight:700; }
    .delta { color:var(--muted); font-size:13px; margin-top:4px; }
    .chart { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; margin:14px 0 24px; }
    .chart img { display:block; width:100%; height:auto; border-radius:4px; }
    table { width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; margin:12px 0 24px; }
    th, td { border-bottom:1px solid var(--line); padding:10px 12px; text-align:left; font-size:14px; vertical-align:top; }
    th { color:var(--muted); font-weight:600; background:#f4f6f8; }
    .action { background:#fff; border-left:5px solid var(--blue); padding:12px 18px; margin:12px 0; }
    .risk { color:#9b2c34; font-weight:700; }
    @media (max-width:780px) { main { padding:28px 16px 56px; } .cards { grid-template-columns:1fr 1fr; } h1 { font-size:28px; } }
    """
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GA4 每周增长诊断老板版 {current['startDate']} 至 {current['endDate']}</title>
  <style>{css}</style>
</head>
<body>
<main>
  <h1>GA4 每周增长诊断老板版</h1>
  <div class="meta">Property {html.escape(str(property_id))} · GA4 时区 {html.escape(tz)} · 本周 {current['startDate']} 至 {current['endDate']} · 对比 {previous['startDate']} 至 {previous['endDate']} · 生成时间 {html.escape(generated)}</div>

  <h2>Executive Summary</h2>
  <div class="summary">
    <p><strong>结论：{conclusion}</strong> Sessions 从 {fmt_num(prev.get('sessions', 0))} 变为 {fmt_num(cur.get('sessions', 0))}（{sessions_delta}，{session_direction}），{revenue_sentence}，Revenue/session {rps_change_note}。</p>
    <p><strong class="risk">最大风险：{html.escape(paid_diagnosis['title'])}</strong> {html.escape(paid_diagnosis['evidence'])}。预算复盘前要先确认 paid landing page、UTM、checkout/referral 和 purchase revenue 回传。</p>
    <p><strong>新增信号：key event 已拆到事件名，不能把非收入微转化当订单。</strong> {html.escape(key_event_statement)} conversion/key event 有但 revenue 为 0 的日期：{zero_rev_note}。Mobile {fmt_num(mobile_views)} 次 view_item / {fmt_num(mobile_purchase)} 次 purchase，Desktop {fmt_num(desktop_views)} 次 view_item / {fmt_num(desktop_purchase)} 次 purchase；商品级 itemRevenue 合计 {fmt_money(item_revenue)}。</p>
  </div>

  <div class="cards">
    <div class="card"><div class="label">Sessions</div><div class="value">{fmt_num(cur.get('sessions', 0))}</div><div class="delta">上周 {fmt_num(prev.get('sessions', 0))} · {sessions_delta}</div></div>
    <div class="card"><div class="label">Revenue</div><div class="value">{fmt_money(cur.get('totalRevenue', 0))}</div><div class="delta">上周 {fmt_money(prev.get('totalRevenue', 0))} · {revenue_change_note}</div></div>
    <div class="card"><div class="label">Engagement rate</div><div class="value">{fmt_pct(cur.get('engagementRate', 0))}</div><div class="delta">上周 {fmt_pct(prev.get('engagementRate', 0))} · {engagement_pp}</div></div>
    <div class="card"><div class="label">Revenue/session</div><div class="value">{fmt_money(cur.get('revenuePerSession', 0))}</div><div class="delta">上周 {fmt_money(prev.get('revenuePerSession', 0))} · {rps_card_note}</div></div>
  </div>

  <h2>1. 本周新增或变化信号</h2>
  <p><strong>图表判断：</strong>下面的每日趋势显示，{ymd_zh(top_session_day.get('date', ''))} 是 sessions 峰值（{fmt_num(top_session_day.get('sessions', 0))}），但本周 revenue 主要出现在 {ymd_zh(top_revenue_day.get('date', ''))}（{fmt_money(top_revenue_day.get('totalRevenue', 0))}）；流量峰值和成交峰值不同步，说明新增访问没有稳定转化为收入。</p>
  <div class="chart"><img src="{rel(charts['daily'])}" alt="每日 sessions/revenue 趋势"></div>
  <p><strong>图表判断：</strong>核心指标周环比显示 sessions {sessions_delta}，revenue {revenue_change_note}、revenue/session {rps_change_note}、平均会话时长 {duration_delta}。老板应把重点放在流量质量和结账承接，而不是只看访问量。</p>
  <div class="chart"><img src="{rel(charts['movement'])}" alt="核心指标周环比"></div>

  <h2>2. 数据健康与归因问题</h2>
  <p><strong>图表判断：</strong>渠道分布显示 Direct 带来 {fmt_money(direct.get('totalRevenue', 0))}，Organic Search 带来 {fmt_money(organic_search.get('totalRevenue', 0))}，但 Paid Search + Paid Shopping 合计 {fmt_num(paid_total_sessions)} sessions 仍是 {fmt_money(paid_total_revenue)} revenue。老板应先看 paid 承接和归因，不宜只按访问量判断投放价值。</p>
  <div class="chart"><img src="{rel(charts['channel'])}" alt="渠道 sessions/revenue 分布"></div>
  <table>
    <thead><tr><th>问题</th><th>本周数字</th><th>老板解读</th></tr></thead>
    <tbody>
      <tr><td>Direct 异常</td><td>{fmt_num(direct.get('sessions', 0))} sessions / {fmt_money(direct.get('totalRevenue', 0))}</td><td>{html.escape(direct_interpretation)}</td></tr>
      <tr><td>Unassigned</td><td>{fmt_num(health['unassigned'].get('sessions', 0))} sessions / ER {fmt_pct(health['unassigned'].get('engagementRate', 0))}</td><td>仍有无法归类流量，UTM 和 channel grouping 需要清理。</td></tr>
      <tr><td>(not set)</td><td>{fmt_num(health['not_set'].get('sessions', 0))} sessions</td><td>落地页或来源字段缺失，影响页面级诊断。</td></tr>
      <tr><td>Key event 有但 revenue 为 0</td><td>{len(health['zero_revenue_conversions'])} 天出现</td><td>已通过 eventName 拆解识别订单与非收入微转化，预算复盘应以 purchase revenue 为准。</td></tr>
      <tr><td>内部/工具 Referral</td><td>admin.shopify.com {fmt_num(health['admin'].get('sessions', 0))} sessions；{html.escape(health['self_ref_label'])} self-referral {fmt_num(health['self_ref'].get('sessions', 0))} sessions</td><td>Shopify admin 和自 referral 需要加入排除或修正，否则会污染渠道复盘。</td></tr>
    </tbody>
  </table>
  <h3>Key event 与订单收入核验</h3>
  <p><strong>{html.escape(reconciliation_statement)}</strong> 当前配置中的 key events：{html.escape(configured_names)}。eventValue 是事件参数 value 的合计，不等于营业收入；订单判断以 purchase、transactionId 和 purchaseRevenue 为准。</p>
  <table>
    <thead><tr><th>周期</th><th>Event name</th><th>Key events</th><th>Event count</th><th>Event value</th><th>Purchase revenue</th><th>口径</th></tr></thead>
    <tbody>{key_event_table}</tbody>
  </table>
  <h3>本周 Purchase 交易明细</h3>
  <p>唯一 transaction ID {fmt_num(reconciliation['unique_transaction_ids'])} 个，缺失 transaction ID {fmt_num(reconciliation['missing_transaction_ids'])} 条；交易明细收入 {fmt_money(reconciliation['transaction_revenue'])}，商品 itemRevenue {fmt_money(reconciliation['item_revenue'])}。</p>
  <table>
    <thead><tr><th>Date</th><th>Transaction ID</th><th>Device</th><th>Channel</th><th>Source / medium</th><th>Purchase revenue</th></tr></thead>
    <tbody>{transaction_table}</tbody>
  </table>
  {shopify_section}

  <h2>3. 渠道效率诊断</h2>
  <table>
    <thead><tr><th>Channel</th><th>Sessions</th><th>Engagement rate</th><th>Key events</th><th>Revenue</th><th>Revenue/session</th></tr></thead>
    <tbody>{table_rows(rows(data, 'channel_current')[:10], [
        ('Channel', lambda r: r.get('sessionDefaultChannelGroup', '')),
        ('Sessions', lambda r: fmt_num(r.get('sessions', 0))),
        ('ER', lambda r: fmt_pct(r.get('engagementRate', 0))),
        ('Key events', lambda r: fmt_num(key_events_value(r))),
        ('Revenue', lambda r: fmt_money(r.get('totalRevenue', 0))),
        ('RPS', lambda r: fmt_money(r.get('revenuePerSession', 0))),
    ])}</tbody>
  </table>
  <h3>Google CPC campaign</h3>
  <table>
    <thead><tr><th>Campaign</th><th>Sessions</th><th>Engagement rate</th><th>Key events</th><th>Revenue</th><th>Revenue/session</th></tr></thead>
    <tbody>{table_rows(campaign, [
        ('Campaign', lambda r: truncate(r.get('sessionCampaignName', ''), 90)),
        ('Sessions', lambda r: fmt_num(r.get('sessions', 0))),
        ('ER', lambda r: fmt_pct(r.get('engagementRate', 0))),
        ('Key events', lambda r: fmt_num(key_events_value(r))),
        ('Revenue', lambda r: fmt_money(r.get('totalRevenue', 0))),
        ('RPS', lambda r: fmt_money(r.get('revenuePerSession', 0))),
    ])}</tbody>
  </table>

  <h2>4. 广告落地页清单</h2>
  <p><strong>图表判断：</strong>付费落地页图把“需要立刻复盘”的 URL 排出来。最高风险页是 {html.escape(clean_page(paid_landing_note.get('landingPagePlusQueryString', '本周无 paid landing 样本')))}，{fmt_num(paid_landing_note.get('sessions', 0))} sessions、{fmt_money(paid_landing_note.get('totalRevenue', 0))} revenue；需要先查购买路径、页面承接和订单事件回传。</p>
  <div class="chart"><img src="{rel(charts['paid_landing'])}" alt="付费落地页高流量0收入清单"></div>
  <table>
    <thead><tr><th>Channel</th><th>Landing page</th><th>Sessions</th><th>Engagement rate</th><th>Key events</th><th>Revenue</th></tr></thead>
    <tbody>{table_rows(paid_rows, [
        ('Channel', lambda r: r.get('sessionDefaultChannelGroup', '')),
        ('Landing', lambda r: truncate(clean_page(r.get('landingPagePlusQueryString', '')), 100)),
        ('Sessions', lambda r: fmt_num(r.get('sessions', 0))),
        ('ER', lambda r: fmt_pct(r.get('engagementRate', 0))),
        ('Key events', lambda r: fmt_num(key_events_value(r))),
        ('Revenue', lambda r: fmt_money(r.get('totalRevenue', 0))),
    ])}</tbody>
  </table>

  <h2>5. mobile vs desktop 漏斗</h2>
  <p><strong>图表判断：</strong>Mobile 本周有 {fmt_num(mobile_views)} 次 view_item、{fmt_num(mobile_atc)} 次 add_to_cart、{fmt_num(mobile_checkout)} 次 begin_checkout、{fmt_num(mobile_purchase)} 次 purchase；Desktop 有 {fmt_num(desktop_views)} 次 view_item、{fmt_num(desktop_atc)} 次 add_to_cart、{fmt_num(desktop_checkout)} 次 begin_checkout、{fmt_num(desktop_purchase)} 次 purchase。Mobile engagement rate {fmt_pct(mobile.get('engagementRate', 0))}，{device_engagement_note}；结合漏斗阶段判断应优先检查的设备端体验。</p>
  <div class="chart"><img src="{rel(charts['device'])}" alt="mobile vs desktop 漏斗"></div>

  <h2>6. 商品漏斗与商品追踪健康</h2>
  <p><strong>图表判断：</strong>最高浏览商品是 {html.escape(truncate(top_item.get('itemName', '无商品样本'), 90))}，{fmt_num(top_item.get('itemsViewed', 0))} views、{fmt_num(top_item.get('itemsAddedToCart', 0))} ATC、{fmt_num(top_item.get('itemsPurchased', 0))} purchase；前 10 个高浏览商品中 {len(high_view_zero_atc)} 个 0 加购。老板应优先看高浏览低加购 SKU 的页面说服力、价格/配送信息和加购按钮可见性，同时核对 GA4 itemRevenue 是否漏传。</p>
  <div class="chart"><img src="{rel(charts['items'])}" alt="商品浏览加购购买表现"></div>

  <h2>7. SEO、内容页、Referral/AI 来源机会</h2>
  <p><strong>图表判断：</strong>Google organic 本周 {fmt_num(google_organic.get('sessions', 0))} sessions、{fmt_money(google_organic.get('totalRevenue', 0))} revenue，Bing organic {fmt_num(bing_organic.get('sessions', 0))} sessions，ChatGPT 相关来源 {fmt_num(chatgpt_sessions)} sessions，YouTube {fmt_num(youtube_sessions)} sessions，Reddit {fmt_num(reddit_sessions)} sessions，Pinterest {fmt_num(pinterest_sessions)} sessions。{html.escape(organic_interpretation)} AI/referral 样本应继续通过内容页 CTA 和商品推荐承接。</p>
  <div class="chart"><img src="{rel(charts['seo'])}" alt="SEO 内容页 Referral AI 机会"></div>

  <h2>本周建议老板拍板的 5 个动作</h2>
  <div class="action"><strong>1. 先修数据口径，再判断预算。</strong> 核查 gclid 保留、Google Ads auto-tagging、Shopify checkout/支付跳转、self-referral 排除、GA4 key event 定义。</div>
  <div class="action"><strong>2. 复盘 Google CPC 高流量 campaign。</strong> `{html.escape(best_cpc_name)}` 本周 {fmt_num(best_cpc.get('sessions', 0))} sessions、{fmt_money(best_cpc.get('totalRevenue', 0))} revenue；{html.escape(campaign_action_note)}</div>
  <div class="action"><strong>3. 当天做 mobile + desktop 下单 QA。</strong> {device_purchase_note}；用真实设备覆盖商品页、加购、checkout、支付和 thank-you page，确认订单、渠道和 itemRevenue 是否完整进入 GA4。</div>
  <div class="action"><strong>4. 处理高浏览低加购 SKU。</strong> 优先补强 `{html.escape(truncate(top_item.get('itemName', '最高浏览商品'), 70))}` 等前 3 个商品的首屏购买理由、配送安装承诺、评价/案例、套装权益和加购按钮位置。</div>
  <div class="action"><strong>5. 给 SEO/AI 来源页面加转化承接。</strong> 优先处理 `{html.escape(content_action_target)}` 等高流量页面，增加相关商品模块、报价/咨询入口和 FAQ schema。</div>

  <h2>缺口与下一步数据需求</h2>
  <p>本次 GA4 API 已读取 key event 拆解、purchase 交易明细和配置中的 key events。Core Data API 不能稳定提供 transactionId × itemName 的一对一关联；若要逐单核验 SKU、税费、运费、退款和订单状态，需要接入 GA4 BigQuery Export 或 Shopify 订单明细。</p>
</main>
</body>
</html>
"""


def build_markdown(data, charts):
    cur = first_row(data, "summary_current")
    prev = first_row(data, "summary_previous")
    current = data["dateRanges"]["current"]
    previous = data["dateRanges"]["previous"]
    property_id = data.get("propertyId", "unknown")
    shopify_recon = load_shopify_reconciliation(data)
    shopify_section = build_shopify_markdown(shopify_recon)
    campaign = [r for r in rows(data, "campaign_current") if r.get("sessionSourceMedium") == "google / cpc"]
    best_cpc = max(campaign, key=lambda r: r.get("sessions", 0), default={})
    best_cpc_name = best_cpc.get("sessionCampaignName", "最高流量 Google CPC campaign")
    paid_diagnosis = paid_channel_diagnosis(data)
    campaign_action_note = campaign_action(best_cpc)
    revenue_channels = [r for r in rows(data, "channel_current") if r.get("totalRevenue", 0) > 0]
    top_revenue_note = "、".join(
        f"{r.get('sessionDefaultChannelGroup', '(not set)')} {fmt_money(r.get('totalRevenue', 0))}"
        for r in sorted(revenue_channels, key=lambda row: row.get("totalRevenue", 0), reverse=True)[:3]
    ) or "本周无可用收入渠道样本"
    funnel = device_funnel(data)
    item_rows = [r for r in rows(data, "items_current") if r.get("itemsViewed", 0) > 0]
    top_item = max(item_rows, key=lambda r: r.get("itemsViewed", 0), default={})
    top_content_page = max(
        rows(data, "pages_current"),
        key=lambda row: row.get("screenPageViews", 0),
        default={},
    )
    content_action_target = clean_page(top_content_page.get("pagePath", "最高流量内容页"))
    item_revenue = sum(r.get("itemRevenue", 0) for r in item_rows)
    reconciliation = build_key_event_reconciliation(data)
    event_lines = []
    for period, event_rows in [("本周", reconciliation["current_rows"]), ("对比期", reconciliation["previous_rows"])]:
        for row in event_rows:
            event_lines.append(
                f"| {period} | {row.get('eventName', '(not set)')} | {fmt_num(key_events_value(row))} | "
                f"{fmt_num(row.get('eventCount', 0))} | {fmt_money(row.get('eventValue', 0))} | "
                f"{fmt_money(row.get('purchaseRevenue', 0))} |"
            )
    if not event_lines:
        event_lines.append("| - | 事件级数据不可用 | 0 | 0 | $0.00 | $0.00 |")
    transaction_lines = [
        f"| {row.get('date', '')} | {row.get('transactionId', '(not set)')} | {row.get('deviceCategory', '')} | "
        f"{row.get('sessionDefaultChannelGroup', '')} | {row.get('sessionSourceMedium', '')} | {fmt_money(row.get('purchaseRevenue', 0))} |"
        for row in reconciliation["transactions"][:20]
    ]
    if not transaction_lines:
        transaction_lines.append("| - | 本周无 purchase | - | - | - | $0.00 |")
    configured_names = "、".join(row.get("eventName", "(not set)") for row in reconciliation["configured"]) or "Admin API 未返回可用配置"
    if cur.get("sessions", 0) < prev.get("sessions", 0) and cur.get("totalRevenue", 0) > prev.get("totalRevenue", 0):
        conclusion = f"本周不是流量扩张，而是成交恢复：访问减少，但收入集中在 {top_revenue_note}。"
    elif cur.get("sessions", 0) > prev.get("sessions", 0) and cur.get("totalRevenue", 0) < prev.get("totalRevenue", 0):
        conclusion = "本周流量增长但收入走弱，增长质量没有跟上。"
    else:
        conclusion = "本周核心信号是流量、收入和转化效率方向分化，需要看渠道承接而不是只看总量。"
    mobile_purchase = device_event(funnel, "mobile", "purchase")
    desktop_purchase = device_event(funnel, "desktop", "purchase")
    desktop_checkout = device_event(funnel, "desktop", "begin_checkout")
    if mobile_purchase > 0 and desktop_purchase == 0:
        device_purchase_note = f"purchase 全部来自 Mobile；Desktop 有 {fmt_num(desktop_checkout)} 次 begin_checkout 但 0 次 purchase"
    elif mobile_purchase == 0 and desktop_purchase > 0:
        device_purchase_note = f"purchase 全部来自 Desktop；Mobile 没有 purchase"
    else:
        device_purchase_note = f"Mobile {fmt_num(mobile_purchase)} 次 purchase，Desktop {fmt_num(desktop_purchase)} 次 purchase"
    return f"""# GA4 每周增长诊断老板版

Property：`{property_id}`

GA4 时区：`{data.get('propertyTimeZone', 'unknown')}`

本周：`{current['startDate']}` 至 `{current['endDate']}`

对比：`{previous['startDate']}` 至 `{previous['endDate']}`

生成时间：`{data.get('generatedAt', '')}`

## Executive Summary

- 结论：{conclusion} Sessions `{fmt_num(cur.get('sessions', 0))}`，环比 `{fmt_delta_ratio(cur.get('sessions', 0), prev.get('sessions', 0))}`；Revenue `{fmt_money(cur.get('totalRevenue', 0))}`，上周 `{fmt_money(prev.get('totalRevenue', 0))}`；Revenue/session `{fmt_money(cur.get('revenuePerSession', 0))}`。
- 最大风险：{paid_diagnosis['title']} {paid_diagnosis['evidence']}。预算复盘前要先确认 paid landing page、UTM、checkout/referral 和 purchase revenue 回传。
- 新增信号：本周 `{fmt_num(key_events_value(cur))}` 次 key events，其中 purchase `{fmt_num(reconciliation['purchase']['ecommercePurchases'])}`；Mobile `{fmt_num(device_event(funnel, 'mobile', 'view_item'))}` 次 view_item / `{fmt_num(device_event(funnel, 'mobile', 'purchase'))}` 次 purchase；Desktop `{fmt_num(device_event(funnel, 'desktop', 'view_item'))}` 次 view_item / `{fmt_num(device_event(funnel, 'desktop', 'purchase'))}` 次 purchase。商品级 itemRevenue 合计 `{fmt_money(item_revenue)}`。

## Key event 与订单收入核验

当前配置：{configured_names}

| 周期 | Event name | Key events | Event count | Event value | Purchase revenue |
|---|---|---:|---:|---:|---:|
{chr(10).join(event_lines)}

| Date | Transaction ID | Device | Channel | Source / medium | Purchase revenue |
|---|---|---|---|---|---:|
{chr(10).join(transaction_lines)}

交易明细收入 `{fmt_money(reconciliation['transaction_revenue'])}`；商品收入 `{fmt_money(reconciliation['item_revenue'])}`。Core Data API 无法稳定提供 `transactionId × itemName` 一对一关联，精确订单商品核验需使用 GA4 BigQuery Export 或 Shopify 订单明细。

{shopify_section}

## 图表证据

![每日 sessions / revenue 趋势]({rel(charts['daily'])})

![核心指标周环比]({rel(charts['movement'])})

![渠道 sessions / revenue 分布]({rel(charts['channel'])})

![付费落地页高流量 0 收入 / 低转化清单]({rel(charts['paid_landing'])})

![mobile vs desktop 商品漏斗]({rel(charts['device'])})

![商品浏览 / 加购 / 购买表现]({rel(charts['items'])})

![SEO / 内容页 / Referral / AI 来源机会]({rel(charts['seo'])})

## 本周优先动作

1. 先修数据口径，再判断预算：核查 gclid、auto-tagging、Shopify checkout、self-referral 排除、GA4 key event。
2. 复盘 Google CPC 高流量 campaign：`{best_cpc_name}`；{campaign_action_note}
3. 当天做 mobile + desktop 下单 QA：{device_purchase_note}，确认订单、渠道和 itemRevenue 是否完整进入 GA4。
4. 处理高浏览低加购 SKU：优先补强 `{truncate(top_item.get('itemName', '最高浏览商品'), 70)}` 等前 3 个商品页。
5. 给 SEO/AI 来源页面加转化承接：优先处理 `{content_action_target}` 等高流量页面，增加相关商品、报价/咨询入口和 FAQ schema。
"""


def validate_images(html_path):
    content = html_path.read_text(encoding="utf-8")
    srcs = re.findall(r'<img[^>]+src="([^"]+)"', content)
    missing = []
    dimensions = {}
    for src in srcs:
        path = html_path.parent / src
        if not path.exists():
            missing.append(src)
            continue
        with Image.open(path) as img:
            dimensions[src] = {"width": img.width, "height": img.height, "bytes": path.stat().st_size}
            if img.width < 900 or img.height < 500 or path.stat().st_size < 5000:
                missing.append(f"{src}: unreadable-size")
    if missing:
        raise SystemExit(f"Image validation failed: {missing}")
    return dimensions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-dir", default="work")
    parser.add_argument("--report-date")
    parser.add_argument("--bigquery-probe")
    parser.add_argument("--shopify-reconciliation")
    parser.add_argument("--site-domain")
    args = parser.parse_args()

    global WORK, BIGQUERY_PROBE_PATH, SHOPIFY_RECON_PATH, SITE_DOMAIN
    WORK = Path(args.out_dir)
    BIGQUERY_PROBE_PATH = Path(args.bigquery_probe) if args.bigquery_probe else None
    SHOPIFY_RECON_PATH = Path(args.shopify_reconciliation) if args.shopify_reconciliation else None
    SITE_DOMAIN = args.site_domain

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    date = args.report_date or report_date(data)
    WORK.mkdir(parents=True, exist_ok=True)
    asset_dir = WORK / f"ga4_boss_report_assets_{date}"
    asset_dir.mkdir(parents=True, exist_ok=True)
    html_path = WORK / f"ga4_weekly_boss_report_{date}.html"
    md_path = WORK / f"ga4_weekly_boss_report_{date}.md"
    chart_map_path = WORK / f"ga4_boss_report_chart_map_{date}.json"
    charts = {
        "daily": asset_dir / "01_daily_sessions_revenue_trend.png",
        "movement": asset_dir / "02_core_metric_movement.png",
        "channel": asset_dir / "03_channel_sessions_revenue.png",
        "paid_landing": asset_dir / "04_paid_landing_zero_revenue.png",
        "device": asset_dir / "05_mobile_desktop_funnel.png",
        "items": asset_dir / "06_item_funnel.png",
        "seo": asset_dir / "07_seo_referral_ai_opportunity.png",
    }
    draw_daily_chart(data, charts["daily"])
    draw_movement_chart(data, charts["movement"])
    draw_channel_chart(data, charts["channel"])
    draw_paid_landing_chart(data, charts["paid_landing"])
    draw_device_funnel_chart(data, charts["device"])
    draw_item_chart(data, charts["items"])
    draw_seo_chart(data, charts["seo"])
    html_path.write_text(build_html(data, charts), encoding="utf-8")
    md_path.write_text(build_markdown(data, charts), encoding="utf-8")
    chart_map_path.write_text(json.dumps(build_chart_map(charts), ensure_ascii=False, indent=2), encoding="utf-8")
    dimensions = validate_images(html_path)
    print(json.dumps({
        "html": str(html_path),
        "markdown": str(md_path),
        "chart_map": str(chart_map_path),
        "asset_dir": str(asset_dir),
        "images": dimensions,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
