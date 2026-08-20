"""Minimal Google Ads API client (stdlib only), mirroring sp_api.py conventions.

NOT YET USABLE — no developer token / OAuth credentials issued yet. Every
method raises NotImplementedError until the GOOGLE_ADS_* keys are real.
sync_dashboard.py catches that and marks the Google side of Shopify's ad
spend as "pending_credentials".

Setup (one-time — this one has the most steps of the four):
    1. Apply for a developer token at ads.google.com/aw/apicenter (basic
       access is enough for a single account's own campaigns).
    2. Create an OAuth2 client (Google Cloud Console) with the Ads API scope
       (https://www.googleapis.com/auth/adwords), run the installed-app OAuth
       flow once to get a refresh token.
    3. Find the 10-digit customer id (no dashes) in the Ads UI.
    4. Set in config.env:
        GOOGLE_ADS_DEVELOPER_TOKEN=...
        GOOGLE_ADS_CLIENT_ID=...
        GOOGLE_ADS_CLIENT_SECRET=...
        GOOGLE_ADS_REFRESH_TOKEN=...
        GOOGLE_ADS_CUSTOMER_ID=...
"""

import json
import time
import urllib.parse
import urllib.request
import urllib.error

from sp_api import ENV_PATH, load_env

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_VERSION = "v18"


class GoogleAdsAPI:
    def __init__(self, env=None):
        self.env = env or load_env()
        self._access_token = None
        self._exp = 0

    def _required(self):
        keys = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET",
                "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_CUSTOMER_ID")
        if not all(self.env.get(k) for k in keys):
            raise NotImplementedError(
                "GOOGLE_ADS_* not fully set in config.env — Google Ads API access "
                "hasn't been set up yet. See module docstring."
            )

    def access_token(self):
        self._required()
        if self._access_token and time.time() < self._exp - 60:
            return self._access_token
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "client_id": self.env["GOOGLE_ADS_CLIENT_ID"],
            "client_secret": self.env["GOOGLE_ADS_CLIENT_SECRET"],
            "refresh_token": self.env["GOOGLE_ADS_REFRESH_TOKEN"],
        }).encode()
        req = urllib.request.Request(TOKEN_URL, data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        self._access_token = data["access_token"]
        self._exp = time.time() + int(data.get("expires_in", 3600))
        return self._access_token

    def spend_and_impressions_on(self, day):
        """Once creds exist: POST .../customers/{id}/googleAds:searchStream
        with a GAQL query selecting metrics.cost_micros, metrics.impressions,
        metrics.conversions_value for segments.date = day."""
        self._required()
        raise NotImplementedError("Wire up googleAds:searchStream once credentials are confirmed working")


if __name__ == "__main__":
    api = GoogleAdsAPI()
    try:
        api._required()
        print("Google Ads creds look complete.")
    except NotImplementedError as e:
        print(e)
