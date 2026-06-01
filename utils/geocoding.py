import requests
import time
import config


class GeocodingError(Exception):
    pass


class Geocoder:
    def __init__(self):
        self.headers = {"User-Agent": config.USER_AGENT}
        self._last_call = 0.0

    def _wait(self):
        elapsed = time.time() - self._last_call
        if elapsed < config.API_DELAY:
            time.sleep(config.API_DELAY - elapsed)
        self._last_call = time.time()

    def geocode(self, address):
        """Return {'lat', 'lon', 'display_name'} for an address string."""
        self._wait()
        resp = requests.get(
            f"{config.NOMINATIM_URL}/search",
            params={"q": address, "format": "json", "limit": 1},
            headers=self.headers,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
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
        self._wait()
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

        resp = requests.get(
            f"{config.NOMINATIM_URL}/search",
            params=params,
            headers=self.headers,
            timeout=10,
        )
        resp.raise_for_status()

        results = []
        for item in resp.json():
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
