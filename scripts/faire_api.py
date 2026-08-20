"""Minimal Faire Partner API client (stdlib only), mirroring sp_api.py conventions.

NOT YET USABLE — no API key has been issued yet. Every method raises
NotImplementedError until FAIRE_API_KEY is real. sync_dashboard.py catches
that and marks the Faire side of the dashboard as "pending_credentials"
instead of guessing numbers.

Setup (one-time, once you have partner access):
    1. Faire brand portal -> Settings -> API -> request Partner API access
       (Faire has to approve this; it's not self-serve for every account).
    2. Once approved, generate an API key/token there.
    3. Set in config.env:
        FAIRE_API_KEY=...
    4. Fill in BASE / auth header / endpoints below from Faire's Partner API
       docs (https://faire.github.io/external-api-docs/) once you have access
       — the exact paths aren't guessable without it, so this file is
       intentionally a skeleton, not a guess.
"""

import os

from sp_api import ENV_PATH, load_env

BASE = "https://www.faire.com/external-api/v2"  # confirm against real docs once you have access


class FaireAPI:
    def __init__(self, env=None):
        self.env = env or load_env()
        self.api_key = self.env.get("FAIRE_API_KEY", "")

    def _require_key(self):
        if not self.api_key:
            raise NotImplementedError(
                "FAIRE_API_KEY not set in config.env — Faire Partner API access "
                "hasn't been granted yet. See module docstring."
            )

    def orders_on(self, day):
        self._require_key()
        raise NotImplementedError("Wire up GET /orders once Partner API access is confirmed")

    def ad_spend_on(self, day):
        self._require_key()
        raise NotImplementedError("Wire up ads/insights endpoint once Partner API access is confirmed")

    def impressions_on(self, day):
        self._require_key()
        raise NotImplementedError("Wire up storefront analytics endpoint once Partner API access is confirmed")


if __name__ == "__main__":
    api = FaireAPI()
    print("FAIRE_API_KEY set:", bool(api.api_key))
    if not api.api_key:
        print("Not usable yet — apply for Faire Partner API access first.")
