#!/usr/bin/env python3
"""Monthly Shopify scent-family / individual-scent breakdown (Requirement #3).

Not part of the daily automation -- this is a monthly, interactive-session
task, because it needs the Shopify MCP connector's `run-analytics-query`
(ShopifyQL), which only works inside a live Claude Code session, not a
headless script.

Monthly workflow:
  1. In a Claude Code session with the Shopify connector, run:
     run-analytics-query: FROM sales SHOW gross_sales, net_sales, orders
       GROUP BY product_title, product_variant_title
       SINCE <month-start> UNTIL <month-end> ORDER BY gross_sales DESC LIMIT 200
  2. Save the "rows" array from that result as JSON, one row = [product_title,
     product_variant_title, gross_sales, net_sales, orders], to a file, e.g.
     data/scent_raw_2026-08.json
  3. Run: python scripts/scent_breakdown.py data/scent_raw_2026-08.json

Scent code convention (from 🎇sku信息匹配表 in the product xlsx):
  P1-P12  -> "Signature" family (12 named fragrances)
  V2, V3  -> "Vanilla" family
  G1/G2/G5/G6 -> "Fruit" family
This is Claude's own grouping by SKU prefix (the source sheet only lists
scent names, not an official 4-way family split) -- rename FAMILY_NAMES
below if you have an official taxonomy.
"""

import json
import re
import sys
from collections import defaultdict

CODE_RE = re.compile(r'\b([PVG]\d{1,2})\b')

FAMILY_OF = {}
for i in range(1, 13):
    FAMILY_OF[f"P{i}"] = "Signature (P系列)"
FAMILY_OF["V2"] = "Vanilla (V系列)"
FAMILY_OF["V3"] = "Vanilla (V系列)"
for code in ("G1", "G2", "G5", "G6"):
    FAMILY_OF[code] = "Fruit (G系列)"


def classify(product_title, variant_title):
    text = f"{product_title} {variant_title}"
    m = CODE_RE.search(text)
    if not m:
        return None, None
    code = m.group(1)
    return code, FAMILY_OF.get(code, "未分类")


def main(path):
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)

    by_scent = defaultdict(lambda: {"gross": 0.0, "net": 0.0, "orders": 0})
    by_family = defaultdict(lambda: {"gross": 0.0, "net": 0.0, "orders": 0})
    unattributed = {"gross": 0.0, "net": 0.0, "orders": 0, "lines": []}

    for row in rows:
        title, variant, gross, net, orders = row[0], row[1], float(row[2] or 0), float(row[3] or 0), int(row[4] or 0)
        code, family = classify(title, variant)
        if code is None:
            unattributed["gross"] += gross
            unattributed["net"] += net
            unattributed["orders"] += orders
            unattributed["lines"].append((title, variant, gross, orders))
            continue
        by_scent[code]["gross"] += gross
        by_scent[code]["net"] += net
        by_scent[code]["orders"] += orders
        by_family[family]["gross"] += gross
        by_family[family]["net"] += net
        by_family[family]["orders"] += orders

    total_gross = sum(v["gross"] for v in by_scent.values()) + unattributed["gross"]

    print(f"=== 按香型家族 (family) ===  总销售额基准 ${total_gross:,.2f}（含无法归属单香型的套装/展示架）")
    for fam, v in sorted(by_family.items(), key=lambda kv: -kv[1]["gross"]):
        pct = v["gross"] / total_gross * 100 if total_gross else 0
        print(f"  {fam:20s} ${v['gross']:>9,.2f}  ({pct:4.1f}%)  {v['orders']:>4d} 单")

    print(f"\n=== 按单个香味 (scent) ===")
    for code, v in sorted(by_scent.items(), key=lambda kv: -kv[1]["gross"]):
        pct = v["gross"] / total_gross * 100 if total_gross else 0
        print(f"  {code:5s} {FAMILY_OF.get(code,''):22s} ${v['gross']:>9,.2f}  ({pct:4.1f}%)  {v['orders']:>4d} 单  客单价 ${v['gross']/v['orders'] if v['orders'] else 0:6.2f}")

    print(f"\n=== 无法归属单一香型（套装/展示架/礼盒，混合多个香味）===  ${unattributed['gross']:,.2f}  ({unattributed['gross']/total_gross*100 if total_gross else 0:.1f}%)  {unattributed['orders']} 单")
    for title, variant, gross, orders in sorted(unattributed["lines"], key=lambda x: -x[2])[:10]:
        print(f"  ${gross:>8,.2f}  {orders:>3d}单  {title} / {variant}")


if __name__ == "__main__":
    main(sys.argv[1])
