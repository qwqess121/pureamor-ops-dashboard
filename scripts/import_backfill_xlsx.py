#!/usr/bin/env python3
"""One-time backfill: import the real Faire + Shopify daily history that's
already been hand-kept in the "shopify & faire产品详情.xlsx" workbook
(sheets 'Faire每日新品追踪' / 'Shopify每日新品追踪'), and turn it into
data/daily_metrics.jsonl using the exact formulas documented in that
workbook's own header/notes rows:

  Shopify 利润 = GMV - (产品成本+运费) - 拣货费成本($1/单) - 广告花费(Meta+Google)
  Faire   利润 = 实际回款 - 产品成本 - 拣货费成本($7/单) - 广告费(分摊)
  Faire 每日广告费估算 = 当日GMV / 当月总GMV * 当月总广告花费
    (Faire's ads report is monthly, not daily, so the workbook allocates it
     proportionally by each day's share of that month's GMV — same rule
     applied here.)
  CTR = 广告点击/广告曝光, CVR = 广告订单/广告点击, ROAS = 广告GMV/广告花费,
  TACOS = 广告花费/总GMV, 自然订单占比 = (总订单-广告订单)/总订单

This is a backfill for HISTORY only. Going forward, sync_dashboard.py pulls
new days live from each platform's own API — this script never runs as
part of the daily job.

Usage:
    python3 import_backfill_xlsx.py "D:\\Downloads\\shopify & faire产品详情.xlsx"
"""

import json
import os
import sys
from datetime import date

from python_calamine import CalamineWorkbook

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")
OUT_PATH = os.path.join(DATA_DIR, "daily_metrics.jsonl")


def to_float(v):
    if v in (None, "", "无货"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_faire(wb):
    ws = wb.get_sheet_by_name("Faire每日新品追踪").to_python()
    rows = ws[18:]  # header at 16, "2026年7月total" divider at 17
    by_date = {}
    for r in rows:
        d = r[0]
        if not isinstance(d, date):
            continue
        by_date[d.isoformat()] = {
            "gmv": to_float(r[1]),
            "actual_payout": to_float(r[2]),
            "product_cost": to_float(r[3]),
            "orders": to_float(r[7]),
            "retailers": to_float(r[8]),
            "new_retailers": to_float(r[9]),
            "repeat_retailers": to_float(r[10]),
            "page_views": to_float(r[11]),
            "monthly_ad_spend": to_float(r[14]),
            "monthly_ad_impressions": to_float(r[15]),
            "monthly_ad_clicks": to_float(r[16]),
            "monthly_ad_orders": to_float(r[17]),
            "monthly_ad_gmv": to_float(r[18]),
            "note": r[24] if len(r) > 24 else None,
        }
    return by_date


def parse_shopify(wb):
    ws = wb.get_sheet_by_name("Shopify每日新品追踪").to_python()
    rows = ws[17:]  # header at 15, "2026年7月total" divider at 16
    by_date = {}
    last_date = None
    for r in rows:
        d = r[0]
        if isinstance(d, date):
            last_date = d.isoformat()
            by_date[last_date] = {
                "gmv": to_float(r[1]),
                "cost_plus_shipping": to_float(r[2]),
                "orders": to_float(r[5]),
                "visitors": to_float(r[6]),
                "refunds": to_float(r[9]),
                "ads": [],
                "note": r[21] if len(r) > 21 else None,
            }
        if last_date is None:
            continue
        channel = r[20] if len(r) > 20 else None
        spend = to_float(r[10])
        if spend is not None and channel:
            by_date[last_date]["ads"].append({
                "channel": "meta" if "Meta" in str(channel) else "google",
                "spend": spend,
                "impressions": to_float(r[11]),
                "clicks": to_float(r[12]),
                "orders": to_float(r[13]),
                "sales": to_float(r[14]),
            })
    return by_date


def month_totals_faire(by_date):
    """Group each date's GMV by month, alongside that month's single recorded
    ad-report totals (parked on day 1 of the month in the source sheet)."""
    totals = {}
    for iso, rec in by_date.items():
        ym = iso[:7]
        t = totals.setdefault(ym, {"gmv_sum": 0.0, "ad_spend": None, "ad_impr": None,
                                    "ad_clicks": None, "ad_orders": None, "ad_gmv": None})
        t["gmv_sum"] += rec["gmv"] or 0.0
        for k, src in (("ad_spend", "monthly_ad_spend"), ("ad_impr", "monthly_ad_impressions"),
                       ("ad_clicks", "monthly_ad_clicks"), ("ad_orders", "monthly_ad_orders"),
                       ("ad_gmv", "monthly_ad_gmv")):
            if rec.get(src) is not None:
                t[k] = rec[src]
    return totals


def build_faire_record(iso, rec, month_tot):
    gmv = rec["gmv"] or 0.0
    orders = rec["orders"] or 0
    pick_fee = 7.0 * orders
    cost = rec["product_cost"]

    ad_spend = None
    if month_tot["ad_spend"] is not None and month_tot["gmv_sum"]:
        ad_spend = round(gmv / month_tot["gmv_sum"] * month_tot["ad_spend"], 2)

    profit = None
    if rec["actual_payout"] is not None and cost is not None and ad_spend is not None:
        profit = round(rec["actual_payout"] - cost - pick_fee - ad_spend, 2)

    # allocate the month's single ad-report totals (impressions/clicks/orders/ad_gmv)
    # by the same GMV share, so CTR/CVR/ROAS/TACOS can be computed per day too
    def alloc(total_key):
        tv = month_tot[total_key]
        if tv is None or not month_tot["gmv_sum"]:
            return None
        return gmv / month_tot["gmv_sum"] * tv

    ad_impr = alloc("ad_impr")
    ad_clicks = alloc("ad_clicks")
    ad_orders = alloc("ad_orders")
    ad_gmv = alloc("ad_gmv")

    ctr = (ad_clicks / ad_impr) if ad_clicks and ad_impr else None
    cvr = (ad_orders / ad_clicks) if ad_orders and ad_clicks else None
    roas = (ad_gmv / ad_spend) if ad_gmv and ad_spend else None
    tacos = (ad_spend / gmv) if ad_spend and gmv else None
    natural_ratio = ((orders - ad_orders) / orders) if ad_orders is not None and orders else None

    return {
        "status": "ok",
        "source": "xlsx_backfill:Faire每日新品追踪",
        "gmv": gmv,
        "actual_payout": rec["actual_payout"],
        "product_cost": cost,
        "pick_fee": pick_fee,
        "ad_spend_allocated": ad_spend,
        "profit": profit,
        "orders": orders,
        "retailers": rec["retailers"],
        "new_retailers": rec["new_retailers"],
        "repeat_retailers": rec["repeat_retailers"],
        "page_views": rec["page_views"],
        "aov": round(gmv / orders, 2) if orders else None,
        "ad_impressions_allocated": ad_impr,
        "ad_clicks_allocated": ad_clicks,
        "ad_orders_allocated": ad_orders,
        "ad_gmv_allocated": ad_gmv,
        "ctr": ctr, "cvr": cvr, "roas": roas, "tacos": tacos,
        "natural_order_ratio": natural_ratio,
        "note": rec["note"],
    }


def build_shopify_record(iso, rec):
    gmv = rec["gmv"] or 0.0
    orders = rec["orders"] or 0
    pick_fee = 1.0 * orders
    cost = rec["cost_plus_shipping"]
    ad_spend_total = sum(a["spend"] for a in rec["ads"] if a["spend"] is not None)
    ad_impr_total = sum((a["impressions"] or 0) for a in rec["ads"])
    ad_clicks_total = sum((a["clicks"] or 0) for a in rec["ads"])
    ad_orders_total = sum((a["orders"] or 0) for a in rec["ads"])
    ad_sales_total = sum((a["sales"] or 0) for a in rec["ads"])

    profit = None
    if cost is not None:
        profit = round(gmv - cost - pick_fee - ad_spend_total, 2)

    meta = next((a for a in rec["ads"] if a["channel"] == "meta"), None)
    google = next((a for a in rec["ads"] if a["channel"] == "google"), None)

    ctr = (ad_clicks_total / ad_impr_total) if ad_clicks_total and ad_impr_total else None
    cvr = (ad_orders_total / ad_clicks_total) if ad_orders_total and ad_clicks_total else None
    roas = (ad_sales_total / ad_spend_total) if ad_sales_total and ad_spend_total else None
    natural_ratio = ((orders - ad_orders_total) / orders) if orders else None

    return {
        "status": "ok",
        "source": "xlsx_backfill:Shopify每日新品追踪",
        "gmv": gmv,
        "cost_plus_shipping": cost,
        "pick_fee": pick_fee,
        "profit": profit,
        "orders": orders,
        "visitors": rec["visitors"],
        "refunds": rec["refunds"],
        "aov": round(gmv / orders, 2) if orders else None,
        "ad_spend": {"meta": meta["spend"] if meta else None, "google": google["spend"] if google else None},
        "ad_spend_total": ad_spend_total or None,
        "impressions": {"meta": meta["impressions"] if meta else None, "google": google["impressions"] if google else None},
        "ctr": ctr, "cvr": cvr, "roas": roas,
        "natural_order_ratio": natural_ratio,
        "note": rec["note"],
    }


def main(xlsx_path):
    wb = CalamineWorkbook.from_path(xlsx_path)
    faire_by_date = parse_faire(wb)
    shopify_by_date = parse_shopify(wb)
    faire_month_totals = month_totals_faire(faire_by_date)

    all_dates = sorted(set(faire_by_date) | set(shopify_by_date))
    records = []
    for iso in all_dates:
        f = faire_by_date.get(iso)
        s = shopify_by_date.get(iso)
        # skip trailing template rows with no real numbers on either side
        if (not f or f["gmv"] is None) and (not s or s["gmv"] is None):
            continue
        faire_rec = build_faire_record(iso, f, faire_month_totals[iso[:7]]) if f and f["gmv"] is not None else {
            "status": "no_data_this_day", "gmv": 0.0, "orders": 0,
        }
        shopify_rec = build_shopify_record(iso, s) if s and s["gmv"] is not None else {
            "status": "no_data_this_day", "gmv": 0.0, "orders": 0,
        }
        records.append({"date": iso, "faire": faire_rec, "shopify": shopify_rec})

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} days to {OUT_PATH} ({all_dates[0]}..{all_dates[-1]})")


if __name__ == "__main__":
    main(sys.argv[1])
