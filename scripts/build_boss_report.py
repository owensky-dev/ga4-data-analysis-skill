#!/usr/bin/env python3
import argparse
import html
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


TOKENS = {
    "surface": "#FCFCFD",
    "panel": "#FFFFFF",
    "ink": "#1F2430",
    "muted": "#6F768A",
    "grid": "#E6E8F0",
    "axis": "#D7DBE7",
    "blue": "#5477C4",
    "blue_light": "#CEDFFE",
    "gold": "#B8A037",
    "gold_light": "#FFEA8F",
    "orange": "#CC6F47",
    "orange_light": "#FFBDA1",
    "olive": "#71B436",
    "neutral": "#C5CAD3",
    "neutral_dark": "#464C55",
}

FONT_CANDIDATES = [
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
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


def text_width(draw, text, fnt):
    box = draw.textbbox((0, 0), str(text), font=fnt)
    return box[2] - box[0]


def text_height(draw, text, fnt):
    box = draw.textbbox((0, 0), str(text), font=fnt)
    return box[3] - box[1]


def wrap_text(draw, text, fnt, max_width):
    words = str(text).replace("\n", " ").split(" ")
    lines, current = [], ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if text_width(draw, candidate, fnt) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        if text_width(draw, word, fnt) <= max_width:
            current = word
            continue
        chunk = ""
        for ch in word:
            candidate = f"{chunk}{ch}"
            if text_width(draw, candidate, fnt) <= max_width:
                chunk = candidate
            else:
                if chunk:
                    lines.append(chunk)
                chunk = ch
        current = chunk
    if current:
        lines.append(current)
    return lines


def draw_wrapped(draw, xy, text, fnt, fill, max_width, line_gap=6):
    x, y = xy
    for line in wrap_text(draw, text, fnt, max_width):
        draw.text((x, y), line, font=fnt, fill=fill)
        y += text_height(draw, line, fnt) + line_gap
    return y


def canvas(width=1400, height=760):
    return Image.new("RGB", (width, height), TOKENS["surface"])


def header(draw, title, subtitle, width):
    draw_wrapped(draw, (54, 30), title, font(34), TOKENS["ink"], width - 108, 8)
    draw_wrapped(draw, (54, 82), subtitle, font(18), TOKENS["muted"], width - 108, 6)


def fmt_pct(value, digits=1):
    return f"{value * 100:.{digits}f}%"


def fmt_money(value):
    return f"${float(value or 0):,.2f}"


def fmt_num(value):
    return f"{float(value or 0):,.0f}"


def rows(data, key):
    return data.get("results", {}).get(key, {}).get("rows", [])


def summary(data, key):
    values = rows(data, key)
    return values[0] if values else {}


def aggregate_device_funnel(data, key):
    funnel = {"mobile": {}, "desktop": {}}
    for row in rows(data, key):
        device = row.get("deviceCategory")
        event_name = row.get("eventName")
        if device in funnel and event_name:
            funnel[device][event_name] = funnel[device].get(event_name, 0) + row.get("eventCount", 0)
    return funnel


def key_events_value(row):
    return row.get("keyEvents", row.get("conversions", 0))


def build_key_event_reconciliation(data):
    current_rows = [row for row in rows(data, "key_events_current") if key_events_value(row) > 0]
    previous_rows = [row for row in rows(data, "key_events_previous") if key_events_value(row) > 0]
    transactions = rows(data, "purchase_transactions_current")
    configured = rows(data, "configured_key_events")
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
        "configured": configured,
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


def rel(path, out_dir):
    return path.relative_to(out_dir).as_posix()


def draw_daily(data, path):
    img = canvas()
    draw = ImageDraw.Draw(img)
    header(draw, "每日会话趋势", "最近完整 7 天；收入标签显示 totalRevenue，帮助区分放量和成交是否同步。", img.width)
    daily = rows(data, "daily_current")
    sessions = [r.get("sessions", 0) for r in daily]
    revenue = [r.get("totalRevenue", 0) for r in daily]
    dates = [r.get("date", "")[5:] for r in daily]
    if not sessions:
        img.save(path)
        return
    left, top, right, bottom = 86, 160, 1300, 610
    max_v = max(sessions) * 1.15 or 1
    draw.line((left, bottom, right, bottom), fill=TOKENS["axis"], width=2)
    draw.line((left, top, left, bottom), fill=TOKENS["axis"], width=2)
    for i in range(5):
        x = left + (right - left) * i / 4
        draw.line((x, top, x, bottom), fill=TOKENS["grid"], width=1)
        draw.text((x - 16, bottom + 12), fmt_num(max_v * i / 4), font=font(14), fill=TOKENS["muted"])
    points = []
    for i, value in enumerate(sessions):
        x = left + (right - left) * i / max(1, len(sessions) - 1)
        y = bottom - (bottom - top) * value / max_v
        points.append((x, y))
    if len(points) > 1:
        draw.line(points, fill=TOKENS["blue"], width=5)
    for (x, y), value, date, rev in zip(points, sessions, dates, revenue):
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=TOKENS["panel"], outline=TOKENS["blue"], width=3)
        draw.text((x - 24, bottom + 42), date, font=font(15), fill=TOKENS["muted"])
        draw.text((x - 12, y - 32), str(value), font=font(15), fill=TOKENS["ink"])
        if rev:
            draw.rounded_rectangle((x - 46, y + 18, x + 46, y + 48), radius=8, fill=TOKENS["gold_light"], outline=TOKENS["gold"])
            draw.text((x - 36, y + 23), fmt_money(rev), font=font(13), fill=TOKENS["neutral_dark"])
    draw.text((left, bottom + 82), "指标：sessions；收入标签显示 totalRevenue。", font=font(15), fill=TOKENS["muted"])
    img.save(path)


def draw_metric_movement(data, path):
    img = canvas(1400, 700)
    draw = ImageDraw.Draw(img)
    header(draw, "核心指标周环比", "流量与收入增长时，同步检查参与度和会话时长，避免把低质量放量误判为增长。", img.width)
    cur, prev = summary(data, "summary_current"), summary(data, "summary_previous")
    metric_rows = [
        ("Sessions", (cur.get("sessions", 0) - prev.get("sessions", 0)) / prev.get("sessions", 1), None),
        ("New users", (cur.get("newUsers", 0) - prev.get("newUsers", 0)) / prev.get("newUsers", 1), None),
        ("Revenue", (cur.get("totalRevenue", 0) - prev.get("totalRevenue", 0)) / (prev.get("totalRevenue", 1) or 1), None),
        ("Engagement", cur.get("engagementRate", 0) - prev.get("engagementRate", 0), "pp"),
        ("Avg duration", (cur.get("averageSessionDuration", 0) - prev.get("averageSessionDuration", 0)) / (prev.get("averageSessionDuration", 1) or 1), None),
    ]
    zero, scale = 690, 480
    draw.line((zero, 138, zero, 585), fill=TOKENS["axis"], width=2)
    for i, (label, value, unit) in enumerate(metric_rows):
        y = 165 + i * 84
        draw.text((74, y + 7), label, font=font(20), fill=TOKENS["ink"])
        shown = f"{value * 100:+.1f} pp" if unit == "pp" else f"{value * 100:+.1f}%"
        if value >= 0:
            x1, x2 = zero, zero + min(value, 0.8) * scale
            color = TOKENS["gold"] if label == "Revenue" else TOKENS["blue"]
            tx = x2 + 18
        else:
            x1, x2 = zero + max(value, -0.8) * scale, zero
            color = TOKENS["orange"]
            tx = x1 - text_width(draw, shown, font(18)) - 18
        draw.rounded_rectangle((x1, y, x2, y + 46), radius=8, fill=color)
        draw.text((tx, y + 9), shown, font=font(18), fill=TOKENS["neutral_dark"])
    img.save(path)


def draw_ranked_bars(data_rows, path, title, subtitle, label_fn, value_fn, color=TOKENS["blue_light"], outline=TOKENS["blue"], width=1500, height=840):
    img = canvas(width, height)
    draw = ImageDraw.Draw(img)
    header(draw, title, subtitle, img.width)
    rows_to_plot = data_rows[:8]
    max_v = max([value_fn(r)[0] for r in rows_to_plot] or [1])
    left, top, right = 600, 165, width - 110
    bar_h, gap = 46, 30
    for i, row in enumerate(rows_to_plot):
        y = top + i * (bar_h + gap)
        label = label_fn(row)
        value, note = value_fn(row)
        draw_wrapped(draw, (60, y - 4), label, font(16), TOKENS["ink"], 500, 4)
        w = (right - left) * value / max_v if max_v else 0
        draw.rounded_rectangle((left, y, left + w, y + bar_h), radius=8, fill=color, outline=outline)
        draw.text((left + w + 14, y + 13), note, font=font(15), fill=TOKENS["neutral_dark"])
    img.save(path)


def draw_channel(data, path):
    img = canvas(1500, 820)
    draw = ImageDraw.Draw(img)
    header(draw, "渠道会话与收入分布", "把 sessions 和 revenue 放在一起看，快速识别有量无收入或收入过度集中。", img.width)
    channel_rows = rows(data, "channel_current")[:8]
    max_s = max([r.get("sessions", 0) for r in channel_rows] or [1])
    max_r = max([r.get("totalRevenue", 0) for r in channel_rows] or [1]) or 1
    left, right, rleft, rright = 330, 900, 1050, 1370
    draw.text((left, 128), "Sessions", font=font(18), fill=TOKENS["muted"])
    draw.text((rleft, 128), "Revenue", font=font(18), fill=TOKENS["muted"])
    for i, row in enumerate(channel_rows):
        y = 170 + i * 74
        draw_wrapped(draw, (60, y + 2), row.get("sessionDefaultChannelGroup", ""), font(18), TOKENS["ink"], 245, 2)
        sw = (right - left) * row.get("sessions", 0) / max_s
        draw.rounded_rectangle((left, y, left + sw, y + 46), radius=7, fill=TOKENS["blue_light"], outline=TOKENS["blue"])
        draw.text((left + sw + 12, y + 11), fmt_num(row.get("sessions", 0)), font=font(14), fill=TOKENS["neutral_dark"])
        rev = row.get("totalRevenue", 0)
        if rev:
            rw = (rright - rleft) * rev / max_r
            draw.rounded_rectangle((rleft, y, rleft + rw, y + 46), radius=7, fill=TOKENS["gold_light"], outline=TOKENS["gold"])
            draw.text((rleft + rw + 12, y + 11), fmt_money(rev), font=font(14), fill=TOKENS["neutral_dark"])
        else:
            draw.text((rleft, y + 11), "$0", font=font(14), fill=TOKENS["muted"])
    img.save(path)


def draw_device(data, path):
    img = canvas(1500, 760)
    draw = ImageDraw.Draw(img)
    header(draw, "移动端与桌面端商品漏斗", "如果 mobile 有 begin_checkout 但没有 purchase，优先排查移动端结账后段。", img.width)
    funnel = aggregate_device_funnel(data, "event_device_current")
    stages = [("view_item", "View item"), ("add_to_cart", "Add to cart"), ("begin_checkout", "Begin checkout"), ("purchase", "Purchase")]
    max_v = max(funnel["mobile"].get("view_item", 0), funnel["desktop"].get("view_item", 0), 1)
    for idx, device in enumerate(["mobile", "desktop"]):
        x0 = 120 + idx * 690
        draw.text((x0, 135), device.title(), font=font(24), fill=TOKENS["ink"])
        for i, (key, label) in enumerate(stages):
            value = funnel[device].get(key, 0)
            y = 180 + i * 105
            w = max(8, 300 * value / max_v)
            color = TOKENS["orange"] if device == "mobile" else TOKENS["blue"]
            draw.text((x0, y - 30), label, font=font(16), fill=TOKENS["muted"])
            draw.rounded_rectangle((x0, y, x0 + w, y + 46), radius=8, fill=color if value else TOKENS["neutral"])
            draw.text((x0 + w + 16, y + 11), str(value), font=font(18), fill=TOKENS["neutral_dark"])
        vi = funnel[device].get("view_item", 0)
        pur = funnel[device].get("purchase", 0)
        draw.text((x0, 632), f"View-to-purchase: {fmt_pct(pur / vi if vi else 0, 2)}", font=font(18), fill=TOKENS["ink"])
    img.save(path)


def build_outputs(data, out_dir, report_date):
    asset_dir = out_dir / f"ga4_boss_report_assets_{report_date}"
    asset_dir.mkdir(parents=True, exist_ok=True)
    charts = {
        "daily": asset_dir / "01_daily_sessions_trend.png",
        "movement": asset_dir / "02_core_metric_movement.png",
        "channel": asset_dir / "03_channel_sessions_revenue.png",
        "paid_landing": asset_dir / "04_paid_landing_zero_revenue.png",
        "device": asset_dir / "05_device_funnel.png",
        "items": asset_dir / "06_item_funnel.png",
        "seo": asset_dir / "07_seo_content_opportunity.png",
    }
    draw_daily(data, charts["daily"])
    draw_metric_movement(data, charts["movement"])
    draw_channel(data, charts["channel"])
    paid_rows = [
        r for r in rows(data, "landing_channel_current")
        if ("Paid" in r.get("sessionDefaultChannelGroup", "") or "Cross-network" in r.get("sessionDefaultChannelGroup", ""))
        and r.get("sessions", 0) >= 3 and r.get("totalRevenue", 0) == 0
    ]
    draw_ranked_bars(
        paid_rows,
        charts["paid_landing"],
        "付费落地页：高流量但 0 收入",
        "优先复盘有付费 sessions 但没有 revenue 的集合页和 PDP。",
        lambda r: f"{r.get('sessionDefaultChannelGroup')} | {r.get('landingPagePlusQueryString', '').split('?')[0]}",
        lambda r: (r.get("sessions", 0), f"{r.get('sessions', 0)} sessions | {fmt_pct(r.get('engagementRate', 0))} ER | $0"),
        color=TOKENS["orange_light"],
        outline=TOKENS["orange"],
        height=860,
    )
    draw_device(data, charts["device"])
    item_rows = [r for r in rows(data, "items_current") if r.get("itemsViewed", 0) >= 5]
    draw_ranked_bars(
        item_rows,
        charts["items"],
        "高浏览商品的加购表现",
        "识别浏览集中但加购不足的 SKU，优先优化商品页购买理由。",
        lambda r: r.get("itemName", "").replace("COZY ", "").replace("Cozy ", ""),
        lambda r: (r.get("itemsViewed", 0), f"{r.get('itemsViewed', 0)} views | {r.get('itemsAddedToCart', 0)} ATC | {fmt_pct((r.get('itemsAddedToCart', 0) / r.get('itemsViewed', 1)) if r.get('itemsViewed', 0) else 0)}"),
        height=960,
    )
    seo_rows = rows(data, "referral_ai_current")[:8]
    draw_ranked_bars(
        seo_rows,
        charts["seo"],
        "SEO、Referral 与 AI 来源机会",
        "观察 organic、AI、社区和内容来源是否形成可见 sessions 及收入。",
        lambda r: r.get("sessionSourceMedium", ""),
        lambda r: (r.get("sessions", 0), f"{r.get('sessions', 0)} sessions | {fmt_pct(r.get('engagementRate', 0))} ER | {fmt_money(r.get('totalRevenue', 0))}"),
        color=TOKENS["olive"],
        outline=TOKENS["olive"],
        height=760,
    )
    return charts


def build_html(data, charts, out_dir, report_date):
    cur, prev = summary(data, "summary_current"), summary(data, "summary_previous")
    current, previous = data["dateRanges"]["current"], data["dateRanges"]["previous"]
    reconciliation = build_key_event_reconciliation(data)
    paid_rows = [
        r for r in rows(data, "landing_channel_current")
        if ("Paid" in r.get("sessionDefaultChannelGroup", "") or "Cross-network" in r.get("sessionDefaultChannelGroup", ""))
        and r.get("sessions", 0) >= 3 and r.get("totalRevenue", 0) == 0
    ][:5]
    campaign_rows = [r for r in rows(data, "campaign_current") if r.get("sessionSourceMedium") == "google / cpc"][:8]
    current_key_event_total = sum(key_events_value(row) for row in reconciliation["current_rows"])
    previous_key_event_total = sum(key_events_value(row) for row in reconciliation["previous_rows"])
    current_key_event_names = ", ".join(
        f"{row.get('eventName', '(not set)')} {fmt_num(key_events_value(row))}"
        for row in reconciliation["current_rows"]
    ) or "无"
    previous_key_event_names = ", ".join(
        f"{row.get('eventName', '(not set)')} {fmt_num(key_events_value(row))}"
        for row in reconciliation["previous_rows"]
    ) or "无"
    configured_names = ", ".join(row.get("eventName", "(not set)") for row in reconciliation["configured"]) or "Admin API 未返回可用配置"
    purchase = reconciliation["purchase"]
    if reconciliation["available"]:
        key_event_statement = (
            f"本周 {fmt_num(current_key_event_total)} 次 key events：{html.escape(current_key_event_names)}；"
            f"对比期 {fmt_num(previous_key_event_total)} 次：{html.escape(previous_key_event_names)}。"
        )
    else:
        key_event_statement = "事件级 key-event 查询不可用，不能把汇总 key events 直接解释为订单。"
    if purchase["ecommercePurchases"]:
        count_status = "一致" if reconciliation["purchase_counts_match"] else "不一致，需立即排查重复或缺失 transaction_id"
        revenue_status = "一致" if reconciliation["purchase_revenue_matches"] else "不一致，需核对 purchase value、退款和重复上报"
        item_status = (
            "与 purchaseRevenue 一致"
            if reconciliation["item_revenue_matches"]
            else "与 purchaseRevenue 不同；先核对税费、运费、退款和 item 参数"
        )
        reconciliation_statement = (
            f"Purchase event、key events、ecommerce purchases、transactions 与唯一 transaction ID 数量{count_status}；"
            f"purchaseRevenue、totalRevenue 与交易明细合计{revenue_status}；itemRevenue {item_status}。"
        )
    else:
        reconciliation_statement = "本周未观测到 purchase；非收入 key event 只能作为微转化，不能解释为订单。"
    css = """
body{margin:0;background:#fbfcfd;color:#1f2430;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Arial Unicode MS",sans-serif}main{max-width:1120px;margin:0 auto;padding:44px 28px 72px}h1{font-size:34px;margin:0 0 10px}h2{font-size:23px;margin:38px 0 12px}h3{font-size:18px;margin:24px 0 10px}p,li{font-size:16px;line-height:1.72}.meta{color:#667085;font-size:14px;margin-bottom:22px}.summary{border-left:5px solid #cc6f47;padding:8px 0 8px 18px;background:#fff}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0 30px}.card{background:#fff;border:1px solid #e6e8f0;border-radius:8px;padding:16px}.label{color:#667085;font-size:13px;margin-bottom:6px}.value{font-size:26px;font-weight:700}.delta{color:#667085;font-size:13px;margin-top:4px}.chart{background:#fff;border:1px solid #e6e8f0;border-radius:8px;padding:12px;margin:14px 0 24px}.chart img{display:block;width:100%;height:auto;border-radius:4px}table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e6e8f0}th,td{border-bottom:1px solid #e6e8f0;padding:11px 12px;text-align:left;font-size:14px;vertical-align:top}th{color:#667085;background:#f4f6f8}.action{background:#fff;border-left:5px solid #5477c4;padding:12px 18px;margin:12px 0}@media(max-width:780px){main{padding:28px 16px 56px}.cards{grid-template-columns:1fr 1fr}h1{font-size:28px}}
"""
    campaign_table = "\n".join(f"<tr><td>{html.escape(r.get('sessionCampaignName',''))}</td><td>{r.get('sessions',0)}</td><td>{fmt_pct(r.get('engagementRate',0))}</td><td>{fmt_num(key_events_value(r))}</td><td>{fmt_money(r.get('totalRevenue',0))}</td></tr>" for r in campaign_rows)
    paid_table = "\n".join(f"<tr><td>{html.escape(r.get('sessionDefaultChannelGroup',''))}</td><td>{html.escape(r.get('landingPagePlusQueryString','').split('?')[0])}</td><td>{r.get('sessions',0)}</td><td>{fmt_pct(r.get('engagementRate',0))}</td><td>{fmt_money(r.get('totalRevenue',0))}</td></tr>" for r in paid_rows)
    key_event_table = "\n".join(
        f"<tr><td>{period}</td><td>{html.escape(row.get('eventName', '(not set)'))}</td>"
        f"<td>{fmt_num(key_events_value(row))}</td><td>{fmt_num(row.get('eventCount', 0))}</td>"
        f"<td>{fmt_money(row.get('eventValue', 0))}</td><td>{fmt_money(row.get('purchaseRevenue', 0))}</td>"
        f"<td>{'订单' if row.get('eventName') == 'purchase' else '非收入微转化' if not row.get('purchaseRevenue', 0) else '收入事件'}</td></tr>"
        for period, event_rows in [("本周", reconciliation["current_rows"]), ("对比期", reconciliation["previous_rows"])]
        for row in event_rows
    ) or '<tr><td colspan="7">事件级 key-event 数据不可用</td></tr>'
    transaction_table = "\n".join(
        f"<tr><td>{html.escape(row.get('date', ''))}</td><td>{html.escape(row.get('transactionId', '(not set)'))}</td>"
        f"<td>{html.escape(row.get('deviceCategory', ''))}</td><td>{html.escape(row.get('sessionDefaultChannelGroup', ''))}</td>"
        f"<td>{html.escape(row.get('sessionSourceMedium', ''))}</td><td>{fmt_money(row.get('purchaseRevenue', 0))}</td></tr>"
        for row in reconciliation["transactions"][:20]
    ) or '<tr><td colspan="6">本周无 purchase 交易明细</td></tr>'
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GA4 每周增长诊断老板版</title><style>{css}</style></head><body><main>
<h1>GA4 每周增长诊断老板版</h1>
<div class="meta">Property {html.escape(str(data.get('propertyId','')))} · 本周 {current['startDate']} 至 {current['endDate']} · 对比 {previous['startDate']} 至 {previous['endDate']} · 站点时区 {html.escape(data.get('propertyTimeZone',''))}</div>
<h2>Executive Summary</h2>
<div class="summary">
<p><strong>本周先看增长质量，不只看总量。</strong> Sessions 从 {fmt_num(prev.get('sessions',0))} 到 {fmt_num(cur.get('sessions',0))}；Revenue 从 {fmt_money(prev.get('totalRevenue',0))} 到 {fmt_money(cur.get('totalRevenue',0))}。如果参与度或收入归因不同步，要先排查链路。</p>
<p><strong>Key event 已按事件名和订单明细拆解。</strong> {key_event_statement} {reconciliation_statement}</p>
</div>
<div class="cards">
<div class="card"><div class="label">Sessions</div><div class="value">{fmt_num(cur.get('sessions',0))}</div><div class="delta">上周 {fmt_num(prev.get('sessions',0))}</div></div>
<div class="card"><div class="label">Revenue</div><div class="value">{fmt_money(cur.get('totalRevenue',0))}</div><div class="delta">上周 {fmt_money(prev.get('totalRevenue',0))}</div></div>
<div class="card"><div class="label">Engagement rate</div><div class="value">{fmt_pct(cur.get('engagementRate',0))}</div><div class="delta">上周 {fmt_pct(prev.get('engagementRate',0))}</div></div>
<div class="card"><div class="label">Key events</div><div class="value">{fmt_num(key_events_value(cur))}</div><div class="delta">其中 purchase {fmt_num(purchase['ecommercePurchases'])}</div></div>
</div>
<h2>增长趋势与核心指标</h2><p><strong>先判断放量是否伴随收入。</strong> 趋势图用于识别流量峰值和成交日是否同步。</p><div class="chart"><img src="{rel(charts['daily'], out_dir)}" alt="每日会话趋势"></div><div class="chart"><img src="{rel(charts['movement'], out_dir)}" alt="核心指标周环比"></div>
<h2>渠道归因是否可信</h2><p><strong>同时看 sessions 和 revenue。</strong> 如果 Direct 收入异常集中而 paid/organic 有量无收入，应先排查归因和 checkout 跳转。</p><div class="chart"><img src="{rel(charts['channel'], out_dir)}" alt="渠道会话与收入"></div>
<h3>Key event 与订单收入核验</h3><p><strong>{key_event_statement}</strong> 配置中的 key events：{html.escape(configured_names)}。eventValue 是事件参数 value 的合计，不等于营业收入；订单判断以 purchase、transactionId 和 purchaseRevenue 为准。</p><table><thead><tr><th>周期</th><th>Event name</th><th>Key events</th><th>Event count</th><th>Event value</th><th>Purchase revenue</th><th>口径</th></tr></thead><tbody>{key_event_table}</tbody></table>
<h3>本周 Purchase 交易明细</h3><p><strong>{reconciliation_statement}</strong> 唯一 transaction ID {fmt_num(reconciliation['unique_transaction_ids'])} 个，缺失 transaction ID {fmt_num(reconciliation['missing_transaction_ids'])} 条；交易明细收入 {fmt_money(reconciliation['transaction_revenue'])}，商品收入 {fmt_money(reconciliation['item_revenue'])}。</p><table><thead><tr><th>Date</th><th>Transaction ID</th><th>Device</th><th>Channel</th><th>Source / medium</th><th>Purchase revenue</th></tr></thead><tbody>{transaction_table}</tbody></table>
<h3>Google CPC Campaign</h3><table><thead><tr><th>Campaign</th><th>Sessions</th><th>Engagement rate</th><th>Key events</th><th>Revenue</th></tr></thead><tbody>{campaign_table}</tbody></table>
<h2>付费落地页复盘</h2><p><strong>高 sessions 但 0 revenue 的 paid 页面优先复盘。</strong> 这类页面最容易消耗预算但不能证明购买承接。</p><div class="chart"><img src="{rel(charts['paid_landing'], out_dir)}" alt="付费落地页 0 收入"></div><table><thead><tr><th>Channel</th><th>Landing page</th><th>Sessions</th><th>ER</th><th>Revenue</th></tr></thead><tbody>{paid_table}</tbody></table>
<h2>Mobile vs Desktop 漏斗</h2><p><strong>Mobile 进入 checkout 但没有 purchase 时，先做移动端下单 QA。</strong> 这通常比泛泛改 PDP 更直接。</p><div class="chart"><img src="{rel(charts['device'], out_dir)}" alt="设备漏斗"></div>
<h2>商品漏斗与 SEO 机会</h2><p><strong>商品图看高浏览低加购 SKU，SEO 图看有需求但未变现的来源。</strong> 这两块决定本周 CRO 和内容承接动作。</p><div class="chart"><img src="{rel(charts['items'], out_dir)}" alt="商品漏斗"></div><div class="chart"><img src="{rel(charts['seo'], out_dir)}" alt="SEO 和 Referral 机会"></div>
<h2>本周优先动作</h2><div class="action"><strong>1. 修归因再调预算。</strong> 检查 auto-tagging、gclid 保留、跨域、支付跳转和 key event 设置。</div><div class="action"><strong>2. 复测 mobile checkout。</strong> 覆盖购物车、折扣、运费、地址校验和支付方式。</div><div class="action"><strong>3. 收紧付费落地页。</strong> 优先复盘 paid 集合页和主推 SKU 页。</div><div class="action"><strong>4. 统一 campaign 命名。</strong> 保证下周能稳定比较主题、品类、品牌词和 SKU 组。</div>
<h2>进一步问题与口径限制</h2><p>Core Data API 不能稳定提供 transactionId × itemName 的一对一关联；itemRevenue 与 purchaseRevenue 不一致时，先核对税费、运费、退款和 item 参数，若要精确到每笔订单的 SKU，使用 GA4 BigQuery Export。若 AI/社区来源没有样本，应表述为 GA4 本周未观测到可分析会话，而不是渠道没有机会。</p>
</main></body></html>"""


def build_markdown(data, charts, out_dir):
    current, previous = data["dateRanges"]["current"], data["dateRanges"]["previous"]
    cur, prev = summary(data, "summary_current"), summary(data, "summary_previous")
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
    configured_names = ", ".join(row.get("eventName", "(not set)") for row in reconciliation["configured"]) or "Admin API 未返回可用配置"
    return f"""# GA4 每周增长诊断老板版

本周范围：`{current['startDate']}` 至 `{current['endDate']}`；对比范围：`{previous['startDate']}` 至 `{previous['endDate']}`。

## Executive Summary

- **本周增长结果。** Sessions `{fmt_num(cur.get('sessions', 0))}`，上期 `{fmt_num(prev.get('sessions', 0))}`；Revenue `{fmt_money(cur.get('totalRevenue', 0))}`，上期 `{fmt_money(prev.get('totalRevenue', 0))}`。
- **Key event 已拆解。** 本周 `{fmt_num(key_events_value(cur))}` 次 key events，其中 purchase `{fmt_num(reconciliation['purchase']['ecommercePurchases'])}`；不能再把非收入微转化解释为订单。

## Key event 与订单收入核验

当前配置：{configured_names}

| 周期 | Event name | Key events | Event count | Event value | Purchase revenue |
|---|---|---:|---:|---:|---:|
{chr(10).join(event_lines)}

| Date | Transaction ID | Device | Channel | Source / medium | Purchase revenue |
|---|---|---|---|---|---:|
{chr(10).join(transaction_lines)}

交易明细收入 `{fmt_money(reconciliation['transaction_revenue'])}`；商品收入 `{fmt_money(reconciliation['item_revenue'])}`。Core Data API 无法稳定提供 `transactionId × itemName` 一对一关联，精确订单商品核验需使用 GA4 BigQuery Export。

## 图表

![每日会话趋势]({rel(charts['daily'], out_dir)})
![核心指标周环比]({rel(charts['movement'], out_dir)})
![渠道会话与收入]({rel(charts['channel'], out_dir)})
![付费落地页 0 收入]({rel(charts['paid_landing'], out_dir)})
![设备漏斗]({rel(charts['device'], out_dir)})
![商品漏斗]({rel(charts['items'], out_dir)})
![SEO 和 Referral 机会]({rel(charts['seo'], out_dir)})
"""


def validate_images(html_path):
    text = html_path.read_text(encoding="utf-8")
    missing = []
    for src in re.findall(r'<img src="([^"]+)"', text):
        if not (html_path.parent / src).exists():
            missing.append(src)
    if missing:
        raise SystemExit(f"Missing image references: {missing}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-dir", default="work")
    parser.add_argument("--report-date", required=True)
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    charts = build_outputs(data, out_dir, args.report_date)

    html_path = out_dir / f"ga4_weekly_boss_report_{args.report_date}.html"
    md_path = out_dir / f"ga4_weekly_boss_report_{args.report_date}.md"
    chart_map_path = out_dir / f"ga4_boss_report_chart_map_{args.report_date}.json"
    html_path.write_text(build_html(data, charts, out_dir, args.report_date), encoding="utf-8")
    md_path.write_text(build_markdown(data, charts, out_dir), encoding="utf-8")
    chart_map = [
        {"section": "增长趋势与核心指标", "chart": charts["daily"].name, "type": "line", "claim": "Daily sessions and revenue timing show whether traffic and purchases move together."},
        {"section": "核心指标周环比", "chart": charts["movement"].name, "type": "diverging bar", "claim": "Core metrics show growth quality, not only volume."},
        {"section": "渠道归因", "chart": charts["channel"].name, "type": "horizontal bar", "claim": "Channel sessions and revenue reveal attribution concentration or paid inefficiency."},
        {"section": "付费落地页", "chart": charts["paid_landing"].name, "type": "ranked bar", "claim": "Paid pages with sessions and zero revenue need budget and CRO review."},
        {"section": "设备漏斗", "chart": charts["device"].name, "type": "stage bars", "claim": "Mobile checkout gaps should trigger QA."},
        {"section": "商品漏斗", "chart": charts["items"].name, "type": "ranked bar", "claim": "High-view low-ATC SKUs need PDP optimization."},
        {"section": "SEO/Referral/AI", "chart": charts["seo"].name, "type": "ranked bar", "claim": "Organic and referral sessions identify non-paid opportunity."},
    ]
    chart_map_path.write_text(json.dumps(chart_map, ensure_ascii=False, indent=2), encoding="utf-8")
    validate_images(html_path)
    print(json.dumps({
        "html": str(html_path),
        "markdown": str(md_path),
        "chart_map": str(chart_map_path),
        "assets": [str(p) for p in charts.values()],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
