#!/usr/bin/env python3
"""Daily sync for the Faire + Shopify dashboard.

Pulls a given date's numbers from every connected source, appends/replaces
one line in data/daily_metrics.jsonl (schema matches import_backfill_xlsx.py
so history and live days render the same way), then re-renders the
dashboard HTML (render_dashboard.py) so it can be republished as the
Artifact.

Every source degrades to status="pending_credentials" (not a guessed
number) when its config.env keys aren't set yet — including Shopify, since
this script must keep working as pieces get wired in one at a time. As
each source's credentials land in config.env, this script starts pulling
it automatically; no code changes needed elsewhere.

Usage:
    python3 sync_dashboard.py                 # sync yesterday (shop-local)
    python3 sync_dashboard.py 2026-08-19       # sync a specific date
"""

import json
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")
JSONL_PATH = os.path.join(DATA_DIR, "daily_metrics.jsonl")
COGS_CSV = os.path.join(DATA_DIR, "cogs.csv")

sys.path.insert(0, HERE)

SHOPIFY_PICK_FEE = 1.0   # $/order, per Shopify每日新品追踪 template
FAIRE_PICK_FEE = 7.0     # $/order, per Faire每日新品追踪 template


def load_cogs_table():
    """SKU -> unit cost, manual fallback for when Shopify variant cost isn't set."""
    table = {}
    if os.path.exists(COGS_CSV):
        with open(COGS_CSV) as f:
            next(f, None)  # header
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                sku, cost = line.split(",")[:2]
                table[sku.strip()] = float(cost)
    return table


def pull_shopify(day):
    try:
        from shopify_api import ShopifyAPI
        api = ShopifyAPI()  # raises KeyError/SystemExit if config.env / keys missing
    except Exception:
        return {"status": "pending_credentials"}

    cogs = load_cogs_table()
    orders = api.orders_on(day)
    fulfilled = [o for o in orders if o.get("fulfillment_status") == "fulfilled"]

    gmv = sum(float(o["total_price"]) for o in orders)
    order_count = len(orders)
    refunds = sum(float(r.get("amount", 0)) for o in orders for r in o.get("refunds", []) or [])

    # Cost + shipping: only for fulfilled orders (ad spend is only attributed
    # once shipped, per the 5pm daily workflow).
    total_cost = 0.0
    cost_complete = True
    variant_cost_cache = {}
    for o in fulfilled:
        for li in o.get("line_items", []):
            sku = li.get("sku")
            qty = li.get("quantity", 0)
            variant_id = li.get("variant_id")
            unit_cost = cogs.get(sku)
            if unit_cost is None and variant_id:
                if variant_id not in variant_cost_cache:
                    try:
                        variant_cost_cache[variant_id] = api.variant_cost(variant_id)
                    except Exception:
                        variant_cost_cache[variant_id] = None
                unit_cost = variant_cost_cache[variant_id]
            if unit_cost is None:
                cost_complete = False
                continue
            total_cost += unit_cost * qty

    try:
        rows = api.shopifyql(
            f"FROM sessions SHOW sessions, online_store_visitors SINCE '{day}' UNTIL '{day}'"
        )
        visitors = int(rows[0]["online_store_visitors"]) if rows else None
    except Exception:
        visitors = None  # plan/app may not have analytics access

    meta = pull_meta(day)
    google = pull_google(day)
    ad_spend = {"meta": meta.get("spend"), "google": google.get("spend")}
    ad_spend_total = sum(v for v in ad_spend.values() if v is not None) or None

    pick_fee = SHOPIFY_PICK_FEE * order_count
    cost_plus_shipping = round(total_cost, 2) if cost_complete else None
    profit = round(gmv - cost_plus_shipping - pick_fee - (ad_spend_total or 0), 2) \
        if cost_plus_shipping is not None else None

    return {
        "status": "ok",
        "source": "sync_dashboard.py:shopify_api",
        "gmv": round(gmv, 2),
        "cost_plus_shipping": cost_plus_shipping,
        "cost_partial": (not cost_complete) and total_cost > 0,
        "pick_fee": pick_fee,
        "profit": profit,
        "orders": order_count,
        "orders_fulfilled": len(fulfilled),
        "visitors": visitors,
        "refunds": round(refunds, 2) if refunds else None,
        "aov": round(gmv / order_count, 2) if order_count else None,
        "ad_spend": ad_spend,
        "ad_spend_total": ad_spend_total,
        "impressions": {"meta": meta.get("impressions"), "google": google.get("impressions")},
    }


def pull_meta(day):
    try:
        from meta_ads_api import MetaAdsAPI
        api = MetaAdsAPI()
        data = api.spend_and_impressions_on(day)
        row = (data.get("data") or [{}])[0]
        return {"status": "ok", "spend": float(row.get("spend", 0)),
                "impressions": int(row.get("impressions", 0))}
    except NotImplementedError:
        return {"status": "pending_credentials", "spend": None, "impressions": None}
    except Exception:
        return {"status": "pending_credentials", "spend": None, "impressions": None}


def pull_google(day):
    try:
        from google_ads_api import GoogleAdsAPI
        api = GoogleAdsAPI()
        api.spend_and_impressions_on(day)
        raise RuntimeError("unreachable until implemented")
    except NotImplementedError:
        return {"status": "pending_credentials", "spend": None, "impressions": None}
    except Exception:
        return {"status": "pending_credentials", "spend": None, "impressions": None}


def pull_faire(day):
    try:
        from faire_api import FaireAPI
        api = FaireAPI()
        api.orders_on(day)
        raise RuntimeError("unreachable until implemented")
    except NotImplementedError:
        return {"status": "pending_credentials"}
    except Exception:
        return {"status": "pending_credentials"}


def sync_day(day):
    shopify = pull_shopify(day)
    faire = pull_faire(day)
    record = {"date": day, "faire": faire, "shopify": shopify}

    os.makedirs(DATA_DIR, exist_ok=True)
    lines = []
    if os.path.exists(JSONL_PATH):
        with open(JSONL_PATH, encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip() and json.loads(l)["date"] != day]
    lines.append(record)
    lines.sort(key=lambda r: r["date"])
    with open(JSONL_PATH, "w", encoding="utf-8") as f:
        for r in lines:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"synced {day}: shopify={shopify['status']} "
          f"({'gmv=' + str(shopify.get('gmv')) if shopify['status']=='ok' else 'no token yet'}), "
          f"faire={faire['status']}")
    return record


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else (date.today() - timedelta(days=1)).isoformat()
    sync_day(day)
    import subprocess
    subprocess.run([sys.executable, os.path.join(HERE, "render_dashboard.py")], check=True)
