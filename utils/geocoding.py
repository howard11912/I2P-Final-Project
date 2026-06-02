import threading
import time

import requests

import config


class GeocodingError(Exception):
    pass


# ── Process-wide Nominatim rate limiter ───────────────────────────────
# Nominatim allows at most 1 request/second and will return HTTP 429 (and
# temporarily block the IP) on bursts. The throttle MUST be global: the app
# creates a fresh Geocoder() per request and also runs background prefetch
# threads, so a per-instance timestamp never actually limited anything.
# This lock serializes every /search call across all instances and threads
# and enforces at least API_DELAY seconds between consecutive requests.
_RATE_LOCK = threading.Lock()
_LAST_CALL = 0.0


class Geocoder:
    def __init__(self):
        self.headers = {"User-Agent": config.USER_AGENT}

    def _search(self, params):
        """Rate-limited, globally-serialized GET on Nominatim /search."""
        global _LAST_CALL
        with _RATE_LOCK:
            wait = config.API_DELAY - (time.time() - _LAST_CALL)
            if wait > 0:
                time.sleep(wait)
            _LAST_CALL = time.time()
            resp = requests.get(
                f"{config.NOMINATIM_URL}/search",
                params=params,
                headers=self.headers,
                timeout=10,
            )
        resp.raise_for_status()
        return resp.json()

    def geocode(self, address):
        """Return {'lat', 'lon', 'display_name'} for an address string."""
        data = self._search({"q": address, "format": "json", "limit": 1})
        if not data:
            raise GeocodingError(f"找不到地點：{address}")
        r = data[0]
        return {"lat": float(r["lat"]), "lon": float(r["lon"]),
                "display_name": r["display_name"]}

    def search_venues(self, lat, lon, amenity=None, shop=None, query=None,
                      limit=8, radius=None):
        """
        Search for venues near (lat, lon).

        Prefer structured params (amenity= / shop=) for accuracy;
        fall back to free-text q= if neither is given.
        """
        r     = radius if radius is not None else config.VENUE_SEARCH_RADIUS
        delta = r / 111_000
        viewbox = f"{lon-delta},{lat+delta},{lon+delta},{lat-delta}"

        params = {
            "format":  "json",
            "limit":   limit,
            "viewbox": viewbox,
            "bounded": 1,
        }
        if amenity:
            params["amenity"] = amenity
        elif shop:
            params["shop"] = shop
        elif query:
            params["q"] = query
        else:
            return []

        results = []
        for item in self._search(params):
            name = item.get("name") or item.get("display_name", "Unknown")
            name = name.split(",")[0].strip()
            if not name:
                continue
            results.append({
                "name": name,
                "lat":  float(item["lat"]),
                "lon":  float(item["lon"]),
            })
        return results
