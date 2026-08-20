"""Minimal Meta Marketing API client (stdlib only), mirroring sp_api.py conventions.

NOT YET USABLE — no access token has been issued yet. Every method raises
NotImplementedError until META_ACCESS_TOKEN/META_AD_ACCOUNT_ID are real.
sync_dashboard.py catches that and marks the Meta side of Shopify's ad
spend as "pending_credentials".

Setup (one-time):
    1. developers.facebook.com -> Create App -> add the Marketing API product.
    2. Generate a long-lived access token for a user with admin access to the
       ad account (System User token recommended for a long-running job, since
       it doesn't expire on a 60-day cycle like a personal token does).
    3. Find the ad account id (format: act_<numbers>) in Ads Manager.
    4. Set in config.env:
        META_ACCESS_TOKEN=...
        META_AD_ACCOUNT_ID=act_...
"""

import json
import urllib.parse
import urllib.request
import urllib.error

from sp_api import ENV_PATH, load_env

GRAPH_BASE = "https://graph.facebook.com/v21.0"


class MetaAdsAPI:
    def __init__(self, env=None):
        self.env = env or load_env()
        self.token = self.env.get("META_ACCESS_TOKEN", "")
        self.account_id = self.env.get("META_AD_ACCOUNT_ID", "")

    def _require_creds(self):
        if not self.token or not self.account_id:
            raise NotImplementedError(
                "META_ACCESS_TOKEN / META_AD_ACCOUNT_ID not set in config.env — "
                "Meta Marketing API access hasn't been set up yet. See module docstring."
            )

    def spend_and_impressions_on(self, day):
        """Once creds exist: GET /{account_id}/insights
        fields=spend,impressions,actions time_range={since:day,until:day}"""
        self._require_creds()
        url = (f"{GRAPH_BASE}/{self.account_id}/insights?" + urllib.parse.urlencode({
            "access_token": self.token,
            "fields": "spend,impressions,actions,action_values",
            "time_range": json.dumps({"since": day, "until": day}),
        }))
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code} GET insights\n{e.read().decode(errors='replace')}") from None


if __name__ == "__main__":
    api = MetaAdsAPI()
    print("META creds set:", bool(api.token and api.account_id))
    if not (api.token and api.account_id):
        print("Not usable yet — create a Meta app + long-lived token first.")
