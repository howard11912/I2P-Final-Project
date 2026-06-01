import requests
import config


class RoutingError(Exception):
    pass


class Router:
    def get_route(self, start, end):
        """
        start/end: (lat, lon) tuples.
        Returns {'distance_m', 'duration_s', 'geometry': [[lat,lon], ...]}.
        OSRM expects lon,lat order.
        """
        coords = f"{start[1]},{start[0]};{end[1]},{end[0]}"
        url = f"{config.OSRM_URL}/route/v1/foot/{coords}"
        resp = requests.get(
            url,
            params={"overview": "full", "geometries": "geojson"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "Ok":
            raise RoutingError(f"OSRM error: {data.get('message')}")
        route = data["routes"][0]
        # Convert geometry from [lon, lat] → [lat, lon] for Folium
        geometry = [[c[1], c[0]] for c in route["geometry"]["coordinates"]]
        return {
            "distance_m": route["distance"],
            "duration_s": route["duration"],
            "geometry": geometry,
        }

    def game_seconds(self, osrm_duration_s):
        """Scale real walking time to in-game seconds."""
        minutes = osrm_duration_s / 60
        raw = minutes * config.SPEED_FACTOR
        return int(max(config.MIN_TRAVEL_SECONDS,
                       min(config.MAX_TRAVEL_SECONDS, raw)))
