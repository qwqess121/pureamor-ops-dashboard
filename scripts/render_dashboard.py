#!/usr/bin/env python3
"""Renders data/daily_metrics.jsonl into dashboard/index.html.

Schema (per line): {"date": "YYYY-MM-DD", "faire": {...}, "shopify": {...}}
— see import_backfill_xlsx.py (history) and sync_dashboard.py (forward daily
sync) for how each side gets populated. A side with status != "ok" renders
as an explicit pending/no-data state, never a fabricated number.

Pure stdlib string templating — no build step, no JS framework.
"""

import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")
JSONL_PATH = os.path.join(DATA_DIR, "daily_metrics.jsonl")
OUT_DIR = os.path.join(HERE, "..", "docs")  # GitHub Pages serves from /docs on main
OUT_PATH = os.path.join(OUT_DIR, "index.html")


def load_rows():
    rows = []
    with open(JSONL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda r: r["date"])
    return rows


def n(v):
    return v if v is not None else 0.0


def fmt_money(v):
    return f"${v:,.2f}" if v is not None else "—"


def fmt_money_short(v):
    if v is None:
        return "—"
    sign = "-" if v < 0 else ""
    av = abs(v)
    return f"{sign}${av/1000:.1f}k" if av >= 1000 else f"{sign}${av:.0f}"


def fmt_int(v):
    return f"{v:,.0f}" if v is not None else "—"


def fmt_pct(v):
    return f"{v*100:.1f}%" if v is not None else "—"


def fmt_x(v):
    return f"{v:.2f}x" if v is not None else "—"


def sparkline(values, width, height, pad=6):
    vals = [v for v in values if v is not None]
    if not vals:
        return [], 0, 0
    lo, hi = min(0, min(vals)), max(vals)
    span = (hi - lo) or 1
    n_ = len(values)
    step = (width - 2 * pad) / max(n_ - 1, 1)
    pts = []
    zero_y = pad + (height - 2 * pad) * (1 - (0 - lo) / span)
    for i, v in enumerate(values):
        if v is None:
            pts.append(None)
            continue
        x = pad + i * step
        y = pad + (height - 2 * pad) * (1 - (v - lo) / span)
        pts.append((x, y))
    return pts, zero_y, height - pad


def line_and_fill(pts, base_y, width, pad=6):
    path, started = "", False
    for p in pts:
        if p is None:
            started = False
            continue
        path += (f"M {p[0]:.1f} {p[1]:.1f} " if not started else f"L {p[0]:.1f} {p[1]:.1f} ")
        started = True
    first = next((p for p in pts if p is not None), None)
    last = next((p for p in reversed(pts) if p is not None), None)
    fill = ""
    if first and last:
        fill = path.strip() + f" L {last[0]:.1f} {base_y:.1f} L {first[0]:.1f} {base_y:.1f} Z"
    return path.strip(), fill


def combo_chart_svg(rows, bar_key, line_key, width=760, height=240, bar_color="var(--accent-2)", line_color="var(--accent)"):
    bar_vals = [bar_key(r) for r in rows]
    line_vals = [line_key(r) for r in rows]
    dates = [r["date"] for r in rows]
    n_ = len(rows)

    pad_l, pad_r, pad_t, pad_b = 68, 68, 16, 32
    plot_top, plot_bottom = pad_t, height - pad_b
    plot_h = plot_bottom - plot_top
    plot_left, plot_right = pad_l, width - pad_r
    plot_w = plot_right - plot_left

    max_bar = max([v for v in bar_vals if v is not None] or [1]) * 1.08
    line_defined = [v for v in line_vals if v is not None]
    line_lo = min(0, min(line_defined)) if line_defined else 0
    line_hi = max(line_defined) if line_defined else 1
    line_span = (line_hi - line_lo) or 1

    step = plot_w / max(n_ - 1, 1) if n_ > 1 else 0
    bw = plot_w / n_ * 0.62

    def bar_y(v):
        return plot_bottom - plot_h * 0.58 * (v / max_bar)

    def line_y(v):
        return plot_top + plot_h * (1 - (v - line_lo) / line_span)

    bars, bar_i = [], 0
    for i, v in enumerate(bar_vals):
        if v is None:
            continue
        cx = plot_left + i * step if n_ > 1 else plot_left + plot_w / 2
        x = cx - bw / 2
        y = bar_y(v)
        h = plot_bottom - y
        delay = bar_i * 0.012
        bar_i += 1
        label_y = y - 4
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="2" '
            f'fill="{bar_color}" opacity="0.75" class="bar-anim" '
            f'style="animation-delay:{delay:.3f}s"><title>{dates[i]}: {fmt_money(v)}</title></rect>'
            f'<text x="{cx:.1f}" y="{label_y:.1f}" transform="rotate(-90 {cx:.1f} {label_y:.1f})" '
            f'text-anchor="start" class="bar-value-label" style="animation-delay:{delay+0.3:.3f}s">'
            f'{fmt_money_short(v)}</text>'
        )

    pts = [None if v is None else (plot_left + i * step, line_y(v)) for i, v in enumerate(line_vals)]
    path, fill_path = line_and_fill(pts, plot_bottom, width, 0)
    dots = "\n".join(
        f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="2.6" fill="{line_color}" class="dot-anim" '
        f'style="animation-delay:{1.1 + i*0.012:.3f}s"><title>{dates[i]}: {fmt_money(line_vals[i])}</title></circle>'
        for i, p in enumerate(pts) if p is not None
    )

    # y-axis gridlines: 4 ticks tied to the bar scale, with the matching line-scale
    # value labeled on the right so both series read off the same horizontal lines
    grid = []
    for frac in (0, 1/3, 2/3, 1):
        y = plot_bottom - plot_h * 0.78 * frac
        bar_v = max_bar * frac
        line_v = line_lo + line_span * (1 - (y - plot_top) / plot_h)
        grid.append(
            f'<line x1="{plot_left:.1f}" y1="{y:.1f}" x2="{plot_right:.1f}" y2="{y:.1f}" class="grid-line" />'
            f'<text x="{plot_left-8:.1f}" y="{y:.1f}" class="axis-label axis-label-bar" text-anchor="end" dominant-baseline="middle">{fmt_money_short(bar_v)}</text>'
            f'<text x="{plot_right+8:.1f}" y="{y:.1f}" class="axis-label axis-label-line" text-anchor="start" dominant-baseline="middle">{fmt_money_short(line_v)}</text>'
        )

    stride = max(1, round(n_ / 8))
    x_labels, last_i = [], None
    for i, d in enumerate(dates):
        is_last = i == n_ - 1
        if i % stride != 0 and not is_last:
            continue
        if is_last and last_i is not None and (i - last_i) * step < 28:
            continue
        last_i = i
        x = plot_left + i * step if n_ > 1 else plot_left + plot_w / 2
        x_labels.append(f'<text x="{x:.1f}" y="{plot_bottom+18:.1f}" class="axis-label" text-anchor="middle">{d[5:]}</text>')

    return f'''<svg viewBox="0 0 {width} {height}" class="trend-svg" preserveAspectRatio="xMidYMid meet" role="img">
  {''.join(grid)}
  <text x="{plot_left-8:.1f}" y="{plot_top-2:.1f}" class="axis-label axis-label-bar" text-anchor="end">净收入</text>
  <text x="{plot_right+8:.1f}" y="{plot_top-2:.1f}" class="axis-label axis-label-line" text-anchor="start">毛利</text>
  {''.join(bars)}
  <path d="{path}" class="trend-line line-anim" style="stroke:{line_color}" />
  {dots}
  {''.join(x_labels)}
</svg>'''


def hbar(label, left_val, right_val, left_color="var(--accent)", right_color="var(--accent-2)", left_label="", right_label=""):
    total = (left_val or 0) + (right_val or 0)
    lp = (left_val / total * 100) if total else 0
    rp = 100 - lp
    return f'''<div class="hbar-row">
      <div class="hbar-label">{label}</div>
      <div class="hbar-track">
        <div class="hbar-seg grow-w" data-w="{lp:.1f}" style="background:{left_color}" title="{left_label}"></div>
        <div class="hbar-seg grow-w" data-w="{rp:.1f}" style="background:{right_color}" title="{right_label}"></div>
      </div>
      <div class="hbar-values"><span style="color:{left_color}">{left_label}</span> · <span style="color:{right_color}">{right_label}</span></div>
    </div>'''


def render(rows):
    first_date, last_date = rows[0]["date"], rows[-1]["date"]
    n_days = len(rows)

    faire_ok = [r for r in rows if r["faire"].get("status") == "ok"]
    shop_ok = [r for r in rows if r["shopify"].get("status") == "ok"]

    faire_gmv = sum(r["faire"]["gmv"] or 0 for r in faire_ok)
    faire_revenue = sum(r["faire"]["actual_payout"] or 0 for r in faire_ok)
    faire_profit = sum(r["faire"]["profit"] or 0 for r in faire_ok if r["faire"]["profit"] is not None)
    faire_orders = sum(r["faire"]["orders"] or 0 for r in faire_ok)
    faire_ad_spend = sum(r["faire"]["ad_spend_allocated"] or 0 for r in faire_ok)

    shop_revenue = sum(r["shopify"]["gmv"] or 0 for r in shop_ok)
    shop_profit = sum(r["shopify"]["profit"] or 0 for r in shop_ok if r["shopify"]["profit"] is not None)
    shop_orders = sum(r["shopify"]["orders"] or 0 for r in shop_ok)
    shop_ad_spend = sum(r["shopify"]["ad_spend_total"] or 0 for r in shop_ok)
    shop_meta_spend = sum((r["shopify"]["ad_spend"] or {}).get("meta") or 0 for r in shop_ok)
    shop_google_spend = sum((r["shopify"]["ad_spend"] or {}).get("google") or 0 for r in shop_ok)
    faire_new_retailers = sum(r["faire"].get("new_retailers") or 0 for r in faire_ok)
    faire_repeat_retailers = sum(r["faire"].get("repeat_retailers") or 0 for r in faire_ok)
    faire_page_views = sum(r["faire"].get("page_views") or 0 for r in faire_ok)
    shop_visitors = sum(r["shopify"].get("visitors") or 0 for r in shop_ok)
    faire_aov_avg = (faire_revenue / faire_orders) if faire_orders else None
    shop_aov_avg = (shop_revenue / shop_orders) if shop_orders else None
    faire_roas_avg = sum(r["faire"].get("ad_gmv_allocated") or 0 for r in faire_ok) / faire_ad_spend if faire_ad_spend else None
    faire_tacos_avg = (faire_ad_spend / faire_revenue) if faire_revenue else None

    total_net_revenue = faire_revenue + shop_revenue
    total_profit = faire_profit + shop_profit
    total_orders = faire_orders + shop_orders
    total_ad_spend = faire_ad_spend + shop_ad_spend
    total_aov = (total_net_revenue / total_orders) if total_orders else 0
    daily_profit_avg = total_profit / n_days if n_days else 0

    combo_svg = combo_chart_svg(
        rows,
        bar_key=lambda r: n(r["faire"].get("actual_payout")) + n(r["shopify"].get("gmv")),
        line_key=lambda r: (r["faire"].get("profit") or 0) + (r["shopify"].get("profit") or 0)
                            if r["faire"].get("status") == "ok" or r["shopify"].get("status") == "ok" else None,
        width=1200, height=320,
    )

    contribution_html = "\n".join([
        hbar("净收入", faire_revenue, shop_revenue,
             left_label=f"Faire {fmt_money(faire_revenue)}", right_label=f"Shopify {fmt_money(shop_revenue)}"),
        hbar("毛利", faire_profit, shop_profit,
             left_label=f"Faire {fmt_money(faire_profit)}", right_label=f"Shopify {fmt_money(shop_profit)}"),
        hbar("订单数", faire_orders, shop_orders,
             left_label=f"Faire {fmt_int(faire_orders)}", right_label=f"Shopify {fmt_int(shop_orders)}"),
        hbar("广告花费", faire_ad_spend, shop_ad_spend,
             left_label=f"Faire {fmt_money(faire_ad_spend)}", right_label=f"Shopify {fmt_money(shop_ad_spend)}"),
    ])

    meta_google_html = ""
    if shop_meta_spend or shop_google_spend:
        shop_meta_sales_sum = sum(0 for _ in shop_ok)  # ad sales not separately summed below; compute inline
        meta_google_html = hbar("Shopify 广告花费：Meta vs Google", shop_meta_spend, shop_google_spend,
                                 left_color="var(--accent)", right_color="var(--accent-2)",
                                 left_label=f"Meta {fmt_money(shop_meta_spend)}",
                                 right_label=f"Google {fmt_money(shop_google_spend)}")

    table_rows = []
    for r in rows:
        f, s = r["faire"], r["shopify"]
        f_ok = f.get("status") == "ok"
        s_ok = s.get("status") == "ok"
        day_net = (f["actual_payout"] if f_ok else 0) + (s["gmv"] if s_ok else 0)
        day_profit = (f["profit"] if f_ok and f["profit"] is not None else 0) + \
                     (s["profit"] if s_ok and s["profit"] is not None else 0)
        day_orders = (f["orders"] if f_ok else 0) + (s["orders"] if s_ok else 0)
        day_margin = (day_profit / day_net) if day_net else None
        day_aov = (day_net / day_orders) if day_orders else None
        row_class = "" if (f_ok or s_ok) else "row-empty"
        table_rows.append(f"""
        <tr class="{row_class}">
          <td class="c-date">{r['date']}</td>
          <td class="num grp-faire">{fmt_money(f['gmv']) if f_ok else '—'}</td>
          <td class="num grp-faire">{fmt_money(f['actual_payout']) if f_ok else '—'}</td>
          <td class="num grp-faire">{fmt_money(f['ad_spend_allocated']) if f_ok else '—'}</td>
          <td class="num grp-faire strong">{fmt_money(f['profit']) if f_ok and f['profit'] is not None else '—'}</td>
          <td class="num grp-faire">{fmt_int(f['orders']) if f_ok else '—'}</td>
          <td class="num grp-faire">{fmt_int(f['new_retailers']) if f_ok else '—'}</td>
          <td class="num grp-faire">{fmt_int(f['repeat_retailers']) if f_ok else '—'}</td>
          <td class="num grp-faire">{fmt_int(f['page_views']) if f_ok else '—'}</td>
          <td class="num grp-faire">{fmt_money(f['aov']) if f_ok else '—'}</td>
          <td class="num grp-faire">{fmt_x(f['roas']) if f_ok else '—'}</td>
          <td class="num grp-faire">{fmt_pct(f['tacos']) if f_ok else '—'}</td>
          <td class="num grp-shop">{fmt_money(s['gmv']) if s_ok else '—'}</td>
          <td class="num grp-shop">{fmt_money((s['ad_spend'] or {}).get('meta')) if s_ok else '—'}</td>
          <td class="num grp-shop">{fmt_money((s['ad_spend'] or {}).get('google')) if s_ok else '—'}</td>
          <td class="num grp-shop strong">{fmt_money(s['profit']) if s_ok and s['profit'] is not None else '—'}</td>
          <td class="num grp-shop">{fmt_int(s['orders']) if s_ok else '—'}</td>
          <td class="num grp-shop">{fmt_int(s['visitors']) if s_ok else '—'}</td>
          <td class="num grp-shop">{fmt_money(s['aov']) if s_ok else '—'}</td>
          <td class="num grp-shop">{fmt_x(s['roas']) if s_ok else '—'}</td>
          <td class="num grp-total accent">{fmt_money(day_net)}</td>
          <td class="num grp-total accent">{fmt_money(day_profit)}</td>
          <td class="num grp-total">{fmt_pct(day_margin)}</td>
          <td class="num grp-total">{fmt_int(day_orders)}</td>
          <td class="num grp-total">{fmt_money(day_aov)}</td>
        </tr>""")

    totals_row = f"""
        <tr class="totals-row">
          <td class="c-date">合计 {n_days} 天</td>
          <td class="num grp-faire">{fmt_money(faire_gmv)}</td>
          <td class="num grp-faire">{fmt_money(faire_revenue)}</td>
          <td class="num grp-faire">{fmt_money(faire_ad_spend)}</td>
          <td class="num grp-faire strong">{fmt_money(faire_profit)}</td>
          <td class="num grp-faire">{fmt_int(faire_orders)}</td>
          <td class="num grp-faire">{fmt_int(faire_new_retailers)}</td>
          <td class="num grp-faire">{fmt_int(faire_repeat_retailers)}</td>
          <td class="num grp-faire">{fmt_int(faire_page_views)}</td>
          <td class="num grp-faire">{fmt_money(faire_aov_avg)}</td>
          <td class="num grp-faire">{fmt_x(faire_roas_avg)}</td>
          <td class="num grp-faire">{fmt_pct(faire_tacos_avg)}</td>
          <td class="num grp-shop">{fmt_money(shop_revenue)}</td>
          <td class="num grp-shop">{fmt_money(shop_meta_spend)}</td>
          <td class="num grp-shop">{fmt_money(shop_google_spend)}</td>
          <td class="num grp-shop strong">{fmt_money(shop_profit)}</td>
          <td class="num grp-shop">{fmt_int(shop_orders)}</td>
          <td class="num grp-shop">{fmt_int(shop_visitors)}</td>
          <td class="num grp-shop">{fmt_money(shop_aov_avg)}</td>
          <td class="num grp-shop">—</td>
          <td class="num grp-total accent">{fmt_money(total_net_revenue)}</td>
          <td class="num grp-total accent">{fmt_money(total_profit)}</td>
          <td class="num grp-total">{fmt_pct(total_profit/total_net_revenue if total_net_revenue else None)}</td>
          <td class="num grp-total">{fmt_int(total_orders)}</td>
          <td class="num grp-total">{fmt_money(total_aov)}</td>
        </tr>
        <tr class="totals-row avg-row">
          <td class="c-date">日均</td>
          <td class="num grp-faire">{fmt_money(faire_gmv/n_days)}</td>
          <td class="num grp-faire">{fmt_money(faire_revenue/n_days)}</td>
          <td class="num grp-faire">{fmt_money(faire_ad_spend/n_days)}</td>
          <td class="num grp-faire">{fmt_money(faire_profit/n_days)}</td>
          <td class="num grp-faire">{faire_orders/n_days:.1f}</td>
          <td class="num grp-faire">—</td>
          <td class="num grp-faire">—</td>
          <td class="num grp-faire">{faire_page_views/n_days:.0f}</td>
          <td class="num grp-faire">—</td>
          <td class="num grp-faire">—</td>
          <td class="num grp-faire">—</td>
          <td class="num grp-shop">{fmt_money(shop_revenue/n_days)}</td>
          <td class="num grp-shop">{fmt_money(shop_meta_spend/n_days)}</td>
          <td class="num grp-shop">{fmt_money(shop_google_spend/n_days)}</td>
          <td class="num grp-shop">{fmt_money(shop_profit/n_days)}</td>
          <td class="num grp-shop">{shop_orders/n_days:.1f}</td>
          <td class="num grp-shop">{shop_visitors/n_days:.0f}</td>
          <td class="num grp-shop">—</td>
          <td class="num grp-shop">—</td>
          <td class="num grp-total accent">{fmt_money(total_net_revenue/n_days)}</td>
          <td class="num grp-total accent">{fmt_money(daily_profit_avg)}</td>
          <td class="num grp-total">—</td>
          <td class="num grp-total">{total_orders/n_days:.1f}</td>
          <td class="num grp-total">—</td>
        </tr>"""

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<title>Faire × Shopify 每日经营看板</title>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=Work+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #f5f4f1; --surface: #ffffff; --surface-2: #eeece7;
    --ink: #232032; --ink-dim: #6b6577; --border: #e2dfd8;
    --accent: #9a3b49; --accent-soft: #f3e3e0;
    --accent-2: #3b6e63; --accent-2-soft: #e2ece8;
    --shop: #b8862e; --shop-soft: #f5ecd9;
    --good: #3f8a5b; --good-soft: #e4f0e7;
    --pending: #9c9484; --pending-soft: #ece9e1;
    --critical: #b23a3a;
    --shadow: 0 1px 2px rgba(35,32,50,0.04), 0 8px 24px rgba(35,32,50,0.05);
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #1b1922; --surface: #242130; --surface-2: #2c2939;
      --ink: #ede9e3; --ink-dim: #a79fb0; --border: #383349;
      --accent: #e08d97; --accent-soft: #3a2429;
      --accent-2: #7fc0af; --accent-2-soft: #223330;
      --shop: #d9ac5c; --shop-soft: #3a3121;
      --good: #6fbb8b; --good-soft: #1f3327;
      --pending: #b3a998; --pending-soft: #2e2b25;
      --critical: #e18787;
      --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #1b1922; --surface: #242130; --surface-2: #2c2939;
    --ink: #ede9e3; --ink-dim: #a79fb0; --border: #383349;
    --accent: #e08d97; --accent-soft: #3a2429;
    --accent-2: #7fc0af; --accent-2-soft: #223330;
    --shop: #d9ac5c; --shop-soft: #3a3121;
    --good: #6fbb8b; --good-soft: #1f3327;
    --pending: #b3a998; --pending-soft: #2e2b25;
    --critical: #e18787;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: "Work Sans", ui-sans-serif, system-ui, sans-serif;
    font-size: 14px; line-height: 1.5;
    padding: 32px clamp(16px, 4vw, 48px) 64px;
  }}
  h1, h2 {{ font-family: "Fraunces", Georgia, serif; text-wrap: balance; margin: 0; letter-spacing: -0.01em; }}
  .num {{ font-family: "IBM Plex Mono", ui-monospace, monospace; font-variant-numeric: tabular-nums; text-align: right; }}
  header.page {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 12px 24px; margin-bottom: 28px; }}
  header.page h1 {{ font-size: 28px; font-weight: 600; }}
  header.page .sub {{ color: var(--ink-dim); font-size: 13px; }}
  section {{ margin-bottom: 32px; }}
  .section-title {{ font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-dim); margin: 0 0 12px; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }}
  .kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; box-shadow: var(--shadow); transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease; }}
  .kpi:hover {{ transform: translateY(-3px); box-shadow: 0 4px 10px rgba(35,32,50,0.08), 0 14px 30px rgba(35,32,50,0.10); border-color: var(--accent); }}
  .kpi .label {{ font-size: 12px; color: var(--ink-dim); margin-bottom: 6px; }}
  .kpi .value {{ font-family: "IBM Plex Mono", monospace; font-size: 22px; font-weight: 500; font-variant-numeric: tabular-nums; }}
  .kpi .value.accent {{ color: var(--accent); }}
  .kpi .foot {{ font-size: 11.5px; color: var(--ink-dim); margin-top: 4px; }}
  .chart-card, .panel-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; box-shadow: var(--shadow); transition: box-shadow .18s ease, border-color .18s ease; }}
  .chart-card-wide {{ padding: 20px 24px; }}
  .chart-card:hover, .panel-card:hover {{ box-shadow: 0 4px 10px rgba(35,32,50,0.08), 0 14px 30px rgba(35,32,50,0.10); border-color: var(--accent-2); }}
  .chart-card .title, .panel-card .title {{ font-size: 13px; font-weight: 500; margin-bottom: 10px; }}
  .trend-svg {{ width: 100%; height: 380px; display: block; }}
  .axis-line {{ stroke: var(--border); stroke-width: 1; }}
  .grid-line {{ stroke: var(--border); stroke-width: 1; opacity: 0.6; }}
  .axis-label {{ font-family: "IBM Plex Mono", monospace; font-size: 13px; fill: var(--ink-dim); }}
  .axis-label-bar {{ fill: var(--accent-2); font-weight: 600; }}
  .axis-label-line {{ fill: var(--accent); font-weight: 600; }}
  .bar-value-label {{ font-family: "IBM Plex Mono", monospace; font-size: 11px; font-weight: 500; fill: var(--accent-2); opacity: 0; animation: dotFadeIn .3s ease-out forwards; pointer-events: none; }}
  .trend-line {{ fill: none; stroke-width: 2; }}
  .bar-anim {{ transform-box: fill-box; transform-origin: bottom; animation: barGrow .5s cubic-bezier(.2,.8,.3,1) backwards; transition: opacity .15s ease; cursor: default; }}
  .bar-anim:hover {{ opacity: 1; }}
  .line-anim {{ stroke-dasharray: 2200; stroke-dashoffset: 2200; animation: drawLine 1.4s ease-out .1s forwards; }}
  .dot-anim {{ opacity: 0; animation: dotFadeIn .3s ease-out forwards; cursor: default; }}
  .dot-anim:hover {{ r: 4.5; }}
  @keyframes barGrow {{ from {{ transform: scaleY(0); }} to {{ transform: scaleY(1); }} }}
  @keyframes drawLine {{ to {{ stroke-dashoffset: 0; }} }}
  @keyframes dotFadeIn {{ to {{ opacity: 1; }} }}
  @media (prefers-reduced-motion: reduce) {{
    .bar-anim, .line-anim, .dot-anim, .grow-w {{ animation: none !important; transition: none !important; }}
    .bar-value-label, .dot-anim {{ opacity: 1 !important; }}
  }}
  .legend {{ display: flex; gap: 16px; font-size: 11.5px; color: var(--ink-dim); margin-top: 8px; }}
  .legend span.dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:5px; }}
  .hbar-row {{ display: grid; grid-template-columns: 70px 1fr; row-gap: 2px; align-items: center; margin-bottom: 14px; }}
  .hbar-label {{ font-size: 12.5px; color: var(--ink-dim); }}
  .hbar-track {{ display: flex; height: 18px; border-radius: 4px; overflow: hidden; background: var(--surface-2); }}
  .hbar-seg {{ height: 100%; width: 0; transition: width 1s cubic-bezier(.2,.8,.2,1), filter .15s ease; }}
  .hbar-seg:hover {{ filter: brightness(1.12); }}
  .hbar-values {{ grid-column: 2; font-size: 11.5px; color: var(--ink-dim); margin-top: 3px; }}
  .table-wrap {{ overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow); }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
  thead tr.group th {{ font-size: 11.5px; font-weight: 600; letter-spacing: .03em; text-align: center; padding: 7px; border-bottom: 1px solid var(--border); }}
  thead tr.group th.grp-head {{ color: white; }}
  thead tr.group th.grp-head-faire {{ background: var(--accent-2); }}
  thead tr.group th.grp-head-shop {{ background: var(--shop); }}
  thead tr.group th.grp-head-total {{ background: var(--ink); }}
  thead tr.cols th {{ position: sticky; top: 0; background: var(--surface-2); text-align: right; font-weight: 500; color: var(--ink-dim); padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }}
  thead tr.cols th.c-date {{ text-align: left; }}
  thead tr.cols th.grp-faire {{ background: var(--accent-2-soft); }}
  thead tr.cols th.grp-shop {{ background: var(--shop-soft); }}
  thead tr.cols th.grp-total {{ background: var(--surface-2); }}
  td {{ padding: 7px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; transition: background-color .12s ease; }}
  td.c-date {{ font-family: "IBM Plex Mono", monospace; color: var(--ink-dim); }}
  td.grp-faire {{ background: color-mix(in srgb, var(--accent-2-soft) 55%, transparent); }}
  td.grp-shop {{ background: color-mix(in srgb, var(--shop-soft) 55%, transparent); }}
  td.grp-total {{ background: color-mix(in srgb, var(--surface-2) 65%, transparent); }}
  td.strong {{ font-weight: 600; }}
  td.accent {{ font-weight: 600; color: var(--accent); }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover td {{ background: var(--accent-soft); }}
  tbody tr:hover td.grp-shop {{ background: var(--shop-soft); }}
  tr.row-empty td {{ color: var(--pending); }}
  tfoot .totals-row td {{ font-weight: 600; border-top: 2px solid var(--ink-dim); border-bottom: 1px solid var(--border); }}
  tfoot .avg-row td {{ color: var(--ink-dim); font-weight: 400; font-style: italic; }}
  .notes {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; box-shadow: var(--shadow); font-size: 12.5px; color: var(--ink-dim); }}
  .notes ul {{ margin: 8px 0 0; padding-left: 18px; }}
  .notes li {{ margin-bottom: 4px; }}
  .notes code {{ font-family: "IBM Plex Mono", monospace; background: var(--surface-2); padding: 1px 5px; border-radius: 4px; }}
</style>

<header class="page">
  <div>
    <h1>Faire × Shopify 每日经营看板</h1>
    <div class="sub">统计区间 {first_date} – {last_date}（{n_days} 天）· 生成时间 {generated_at}</div>
  </div>
</header>

<section>
  <p class="section-title">合计（{n_days} 天）</p>
  <div class="kpi-grid">
    <div class="kpi">
      <div class="label">净收入（Faire 回款 + Shopify 销售额）</div>
      <div class="value accent">{fmt_money(total_net_revenue)}</div>
      <div class="foot">日均 {fmt_money(total_net_revenue / n_days)}</div>
    </div>
    <div class="kpi">
      <div class="label">合计毛利</div>
      <div class="value">{fmt_money(total_profit)}</div>
      <div class="foot">毛利率 {fmt_pct(total_profit/total_net_revenue if total_net_revenue else None)} · 日均 {fmt_money(daily_profit_avg)}</div>
    </div>
    <div class="kpi">
      <div class="label">订单 / 客单价</div>
      <div class="value">{fmt_int(total_orders)} 单</div>
      <div class="foot">客单价 {fmt_money(total_aov)}</div>
    </div>
    <div class="kpi">
      <div class="label">广告花费合计</div>
      <div class="value">{fmt_money(total_ad_spend)}</div>
      <div class="foot">TACOS {fmt_pct(total_ad_spend/total_net_revenue if total_net_revenue else None)}</div>
    </div>
    <div class="kpi">
      <div class="label">Faire 回款 / 毛利</div>
      <div class="value">{fmt_money(faire_revenue)}</div>
      <div class="foot">毛利 {fmt_money(faire_profit)} · 占总毛利 {fmt_pct(faire_profit/total_profit if total_profit else None)}</div>
    </div>
    <div class="kpi">
      <div class="label">Shopify GMV / 毛利</div>
      <div class="value">{fmt_money(shop_revenue)}</div>
      <div class="foot">毛利 {fmt_money(shop_profit)} · 占总毛利 {fmt_pct(shop_profit/total_profit if total_profit else None)}</div>
    </div>
  </div>
</section>

<section>
  <div class="chart-card chart-card-wide">
    <div class="title">每日净收入构成（柱）与合计毛利（线）</div>
    {combo_svg}
    <div class="legend">
      <span><span class="dot" style="background:var(--accent-2)"></span>净收入 (Faire 回款 + Shopify 销售额)</span>
      <span><span class="dot" style="background:var(--accent)"></span>合计毛利</span>
    </div>
  </div>
</section>

<section>
  <div class="panel-card">
    <div class="title">两平台贡献对比</div>
    {contribution_html}
    {meta_google_html}
  </div>
</section>

<section>
  <p class="section-title">双平台每日明细（{first_date} – {last_date}）</p>
  <div class="table-wrap">
    <table>
      <thead>
        <tr class="group">
          <th></th>
          <th colspan="11" class="grp-head grp-head-faire">Faire（批发）</th>
          <th colspan="8" class="grp-head grp-head-shop">Shopify（独立站）</th>
          <th colspan="5" class="grp-head grp-head-total">合计（双平台）</th>
        </tr>
        <tr class="cols">
          <th class="c-date">日期</th>
          <th class="grp-faire">批发GMV</th><th class="grp-faire">实际回款</th><th class="grp-faire">广告(分摊)</th><th class="grp-faire">毛利</th><th class="grp-faire">订单</th><th class="grp-faire">新客</th><th class="grp-faire">复购</th><th class="grp-faire">PV</th><th class="grp-faire">客单价</th><th class="grp-faire">ROAS</th><th class="grp-faire">TACOS</th>
          <th class="grp-shop">销售额GMV</th><th class="grp-shop">Meta广告</th><th class="grp-shop">Google广告</th><th class="grp-shop">毛利</th><th class="grp-shop">订单</th><th class="grp-shop">访客</th><th class="grp-shop">客单价</th><th class="grp-shop">ROAS</th>
          <th class="grp-total">净收入</th><th class="grp-total">毛利</th><th class="grp-total">毛利率</th><th class="grp-total">订单</th><th class="grp-total">客单价</th>
        </tr>
      </thead>
      <tbody>
        {''.join(table_rows)}
      </tbody>
      <tfoot>
        {totals_row}
      </tfoot>
    </table>
  </div>
</section>

<section>
  <div class="notes">
    <strong>口径与来源说明</strong>
    <ul>
      <li>历史数据（{first_date}–{last_date}）来自「shopify & faire产品详情.xlsx」里手工维护的 <code>Faire每日新品追踪</code> / <code>Shopify每日新品追踪</code> 两个 sheet，按其自带的公式口径重新计算：Faire 拣货费 $7/单、Shopify 拣货费 $1/单；Faire 广告费按月度报表 × 当日GMV占比分摊到每天；利润 = 净收入 − 产品成本 − 拣货费 − 广告花费。</li>
      <li>Faire 的 CTR/CVR/ROAS/TACOS 是用同样的月度占比分摊法从月度广告报表估算到每日，不是 Faire 后台的每日真实值——月度真实值本身是准的，每日拆分是估算。</li>
      <li>往后新的一天由 <code>scripts/sync_dashboard.py</code> 走各平台自己的 API 实时拉取（需要在 <code>scripts/config.env</code> 里配置 Shopify/Faire/Meta/Google 的凭证），不再依赖手工抄表。</li>
      <li>此页面由 <code>scripts/render_dashboard.py</code> 从 <code>data/daily_metrics.jsonl</code> 生成；数据源脚本见 <code>scripts/import_backfill_xlsx.py</code>（一次性历史导入）。</li>
    </ul>
  </div>
</section>

<script>
  requestAnimationFrame(() => requestAnimationFrame(() => {{
    document.querySelectorAll(".grow-w").forEach(el => {{
      el.style.width = el.dataset.w + "%";
    }});
  }}));
</script>
"""


if __name__ == "__main__":
    rows = load_rows()
    html = render(rows)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {OUT_PATH} ({len(rows)} days)")
