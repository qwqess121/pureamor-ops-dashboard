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
OUT_DIR = os.path.join(HERE, "..", "dashboard")
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


def combo_chart_svg(rows, bar_key, line_key, width=740, height=200, bar_color="var(--accent-2)", line_color="var(--accent)"):
    bar_vals = [bar_key(r) for r in rows]
    line_vals = [line_key(r) for r in rows]
    pad = 8
    max_bar = max([v for v in bar_vals if v is not None] or [1])
    n_ = len(rows)
    bw = (width - 2 * pad) / n_ * 0.62
    step = (width - 2 * pad) / max(n_ - 1, 1) if n_ > 1 else 0

    bars = []
    for i, v in enumerate(bar_vals):
        if v is None:
            continue
        x = pad + i * step - bw / 2 if n_ > 1 else width / 2 - bw / 2
        h = (height - 2 * pad) * 0.72 * (v / max_bar)
        y = height - pad - h
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="2" fill="{bar_color}" opacity="0.75" />')

    line_pts, _, base_y = sparkline(line_vals, width, height, pad)
    path, _ = line_and_fill(line_pts, base_y, width, pad)
    dots = "\n".join(f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="2.4" fill="{line_color}" />'
                      for p in line_pts if p is not None)

    return f'''<svg viewBox="0 0 {width} {height}" class="trend-svg" preserveAspectRatio="none" role="img">
  <line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" class="axis-line" />
  {''.join(bars)}
  <path d="{path}" class="trend-line" style="stroke:{line_color}" />
  {dots}
</svg>'''


def hbar(label, left_val, right_val, left_color="var(--accent)", right_color="var(--accent-2)", left_label="", right_label=""):
    total = (left_val or 0) + (right_val or 0)
    lp = (left_val / total * 100) if total else 0
    rp = 100 - lp
    return f'''<div class="hbar-row">
      <div class="hbar-label">{label}</div>
      <div class="hbar-track">
        <div class="hbar-seg" style="width:{lp:.1f}%;background:{left_color}"></div>
        <div class="hbar-seg" style="width:{rp:.1f}%;background:{right_color}"></div>
      </div>
      <div class="hbar-values"><span style="color:{left_color}">{left_label}</span> · <span style="color:{right_color}">{right_label}</span></div>
    </div>'''


def render(rows):
    first_date, last_date = rows[0]["date"], rows[-1]["date"]
    n_days = len(rows)

    faire_ok = [r for r in rows if r["faire"].get("status") == "ok"]
    shop_ok = [r for r in rows if r["shopify"].get("status") == "ok"]

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
    shop_meta_sales = sum((r["shopify"].get("ad_spend") or {}).get("meta") and 0 or 0 for r in shop_ok)  # placeholder unused

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
        table_rows.append(f"""
        <tr>
          <td class="c-date">{r['date']}</td>
          <td class="num">{fmt_money(f['gmv']) if f_ok else '—'}</td>
          <td class="num">{fmt_money(f['actual_payout']) if f_ok else '—'}</td>
          <td class="num">{fmt_money(f['ad_spend_allocated']) if f_ok else '—'}</td>
          <td class="num strong">{fmt_money(f['profit']) if f_ok and f['profit'] is not None else '—'}</td>
          <td class="num">{fmt_int(f['orders']) if f_ok else '—'}</td>
          <td class="num">{fmt_int(f['page_views']) if f_ok else '—'}</td>
          <td class="num">{fmt_money(s['gmv']) if s_ok else '—'}</td>
          <td class="num">{fmt_money((s['ad_spend'] or {}).get('meta')) if s_ok else '—'}</td>
          <td class="num">{fmt_money((s['ad_spend'] or {}).get('google')) if s_ok else '—'}</td>
          <td class="num strong">{fmt_money(s['profit']) if s_ok and s['profit'] is not None else '—'}</td>
          <td class="num">{fmt_int(s['orders']) if s_ok else '—'}</td>
          <td class="num">{fmt_int(s['visitors']) if s_ok else '—'}</td>
          <td class="num accent">{fmt_money(day_net)}</td>
          <td class="num accent">{fmt_money(day_profit)}</td>
          <td class="num">{fmt_int(day_orders)}</td>
        </tr>""")

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
  .kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; box-shadow: var(--shadow); }}
  .kpi .label {{ font-size: 12px; color: var(--ink-dim); margin-bottom: 6px; }}
  .kpi .value {{ font-family: "IBM Plex Mono", monospace; font-size: 22px; font-weight: 500; font-variant-numeric: tabular-nums; }}
  .kpi .value.accent {{ color: var(--accent); }}
  .kpi .foot {{ font-size: 11.5px; color: var(--ink-dim); margin-top: 4px; }}
  .two-col {{ display: grid; grid-template-columns: 1.3fr 1fr; gap: 16px; }}
  @media (max-width: 900px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
  .chart-card, .panel-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; box-shadow: var(--shadow); }}
  .chart-card .title, .panel-card .title {{ font-size: 13px; font-weight: 500; margin-bottom: 10px; }}
  .trend-svg {{ width: 100%; height: 200px; display: block; }}
  .axis-line {{ stroke: var(--border); stroke-width: 1; }}
  .trend-line {{ fill: none; stroke-width: 2; }}
  .legend {{ display: flex; gap: 16px; font-size: 11.5px; color: var(--ink-dim); margin-top: 8px; }}
  .legend span.dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:5px; }}
  .hbar-row {{ display: grid; grid-template-columns: 70px 1fr; row-gap: 2px; align-items: center; margin-bottom: 14px; }}
  .hbar-label {{ font-size: 12.5px; color: var(--ink-dim); }}
  .hbar-track {{ display: flex; height: 18px; border-radius: 4px; overflow: hidden; background: var(--surface-2); }}
  .hbar-seg {{ height: 100%; }}
  .hbar-values {{ grid-column: 2; font-size: 11.5px; color: var(--ink-dim); margin-top: 3px; }}
  .table-wrap {{ overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow); }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
  thead tr.group th {{ background: var(--surface-2); font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--ink-dim); text-align: center; padding: 6px; border-bottom: 1px solid var(--border); }}
  thead tr.cols th {{ position: sticky; top: 0; background: var(--surface-2); text-align: right; font-weight: 500; color: var(--ink-dim); padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }}
  thead tr.cols th.c-date {{ text-align: left; }}
  td {{ padding: 7px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }}
  td.c-date {{ font-family: "IBM Plex Mono", monospace; color: var(--ink-dim); }}
  td.strong {{ font-weight: 600; }}
  td.accent {{ font-weight: 600; color: var(--accent); }}
  tbody tr:last-child td {{ border-bottom: none; }}
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

<section class="two-col">
  <div class="chart-card">
    <div class="title">每日净收入构成（柱）与合计毛利（线）</div>
    {combo_svg}
    <div class="legend">
      <span><span class="dot" style="background:var(--accent-2)"></span>净收入 (Faire 回款 + Shopify 销售额)</span>
      <span><span class="dot" style="background:var(--accent)"></span>合计毛利</span>
    </div>
  </div>
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
          <th></th><th colspan="6">Faire（批发）</th><th colspan="6">Shopify（独立站）</th><th colspan="3">合计</th>
        </tr>
        <tr class="cols">
          <th class="c-date">日期</th>
          <th>批发GMV</th><th>实际回款</th><th>广告(分摊)</th><th>毛利</th><th>订单</th><th>PV</th>
          <th>销售额GMV</th><th>Meta广告</th><th>Google广告</th><th>毛利</th><th>订单</th><th>访客</th>
          <th>净收入</th><th>毛利</th><th>订单</th>
        </tr>
      </thead>
      <tbody>
        {''.join(table_rows)}
      </tbody>
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
"""


if __name__ == "__main__":
    rows = load_rows()
    html = render(rows)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {OUT_PATH} ({len(rows)} days)")
