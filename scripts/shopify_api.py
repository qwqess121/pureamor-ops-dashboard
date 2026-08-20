"""Minimal Shopify Admin API client (stdlib only), mirroring sp_api.py conventions.

Auth: a custom app access token (Admin API), NOT the same as the interactive
MCP connection used inside a Claude Code session — this client is for the
unattended daily sync job, which cannot rely on a live MCP session.

Setup (one-time, in Shopify Admin):
    Settings -> Apps and sales channels -> Develop apps -> Create an app
    -> Configure Admin API scopes: read_orders, read_products, read_inventory
    -> Install app -> reveal the Admin API access token (starts with shpat_)
    Then set in config.env:
        SHOPIFY_STORE_DOMAIN=your-store.myshopify.com
        SHOPIFY_ADMIN_ACCESS_TOKEN=shpat_...

Notes:
- ShopifyQL analytics (sessions/visitors) is exposed via the GraphQL
  `shopifyqlQuery` mutation. Some plans/apps don't have access to it; callers
  should treat a failure here as "sessions unavailable" and fall back, not
  crash the whole sync.
- Line item cost: Admin REST inventory_items/{id}.json returns a `cost`
  field when set. If it's not set for a SKU, callers should fall back to
  data/cogs.csv (see sync_dashboard.py).
"""

import json
import os
import urllib.parse
import urllib.request
import urllib.error

from sp_api import ENV_PATH, load_env  # reuse the same .env parser/location

API_VERSION = "2024-10"


class ShopifyAPI:
    def __init__(self, env=None):
        self.env = env or load_env()
        domain = self.env["SHOPIFY_STORE_DOMAIN"].strip()
        self.base = f"https://{domain}/admin/api/{API_VERSION}"
        self.token = self.env["SHOPIFY_ADMIN_ACCESS_TOKEN"].strip()

    # --- generic REST request --------------------------------------------------
    def request(self, method, path, params=None, body=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        headers = {
            "X-Shopify-Access-Token": self.token,
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, method=method, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                links = resp.headers.get("Link", "")
                return (json.loads(raw) if raw else {}), links
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise RuntimeError(f"HTTP {e.code} {method} {path}\n{detail}") from None

    def get(self, path, params=None):
        data, _ = self.request("GET", path, params=params)
        return data

    def graphql(self, query, variables=None):
        body = {"query": query, "variables": variables or {}}
        data, _ = self.request("POST", "/graphql.json", body=body)
        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        return data["data"]

    # --- orders ------------------------------------------------------------
    def orders_on(self, day, status="any", fulfillment_status=None):
        """All orders created on a given ISO date (local shop day is not
        accounted for here — pass UTC-adjusted bounds if that matters)."""
        params = {
            "status": status,
            "created_at_min": f"{day}T00:00:00Z",
            "created_at_max": f"{day}T23:59:59Z",
            "limit": 250,
        }
        if fulfillment_status:
            params["fulfillment_status"] = fulfillment_status
        orders = []
        path = "/orders.json"
        while path:
            data, link_header = self.request("GET", path, params=params)
            orders.extend(data.get("orders", []))
            path, params = self._next_page(link_header)
        return orders

    @staticmethod
    def _next_page(link_header):
        for part in (link_header or "").split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip(" <>")
                q = urllib.parse.urlparse(url).query
                return "/orders.json", dict(urllib.parse.parse_qsl(q))
        return None, None

    # --- cost lookup ---------------------------------------------------------
    def variant_cost(self, variant_id):
        """Returns unit cost (float) for a variant via its inventory item, or
        None if not set. One REST round trip per variant — cache upstream."""
        v = self.get(f"/variants/{variant_id}.json").get("variant", {})
        inv_item_id = v.get("inventory_item_id")
        if not inv_item_id:
            return None
        item = self.get(f"/inventory_items/{inv_item_id}.json").get("inventory_item", {})
        cost = item.get("cost")
        return float(cost) if cost is not None else None

    # --- analytics (ShopifyQL) -------------------------------------------------
    def shopifyql(self, query):
        """Run a ShopifyQL query via GraphQL. Returns list of row dicts.
        Raises RuntimeError if the app/plan doesn't have analytics access —
        callers should catch this and mark the metric as unavailable."""
        gql = """
        query ShopifyQL($query: String!) {
          shopifyqlQuery(query: $query) {
            tableData {
              columns { name dataType }
              rowData
            }
            parseErrors { message }
          }
        }
        """
        data = self.graphql(gql, {"query": query})
        result = data["shopifyqlQuery"]
        if result.get("parseErrors"):
            raise RuntimeError(f"ShopifyQL parse errors: {result['parseErrors']}")
        table = result["tableData"]
        cols = [c["name"] for c in table["columns"]]
        return [dict(zip(cols, row)) for row in table["rowData"]]


if __name__ == "__main__":
    api = ShopifyAPI()
    print("Shop:", api.env["SHOPIFY_STORE_DOMAIN"])
    shop = api.get("/shop.json")["shop"]
    print("Name:", shop["name"], "| currency:", shop["currency"], "| plan:", shop["plan_name"])
