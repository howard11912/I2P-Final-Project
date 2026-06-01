import math
import random
import uuid

import config
from utils.geocoding import Geocoder, GeocodingError


def haversine(lat1, lon1, lat2, lon2):
    """Straight-line distance in metres."""
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _random_offset(lat, lon, min_m=400, max_m=1600):
    angle = random.uniform(0, 2 * math.pi)
    dist  = random.uniform(min_m, max_m)
    dlat  = (dist * math.cos(angle)) / 111_000
    dlon  = (dist * math.sin(angle)) / (111_000 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def _pick_tier():
    tiers   = list(config.ORDER_TIERS.keys())
    weights = [config.ORDER_TIERS[t]["weight"] for t in tiers]
    return random.choices(tiers, weights=weights)[0]


def _pick_venue_type():
    return random.choice(list(config.VENUE_TYPES.keys()))


def build_customer_order(venue_type, player_pos):
    """Create an order with customer location only. Venues are fetched at accept-time."""
    tier_key = _pick_tier()
    tier     = config.ORDER_TIERS[tier_key]
    vtype    = config.VENUE_TYPES[venue_type]

    customer_lat, customer_lon = _random_offset(player_pos[0], player_pos[1])

    dist_m = haversine(player_pos[0], player_pos[1], customer_lat, customer_lon)
    base   = random.randint(*vtype["base_reward_range"]) + int(dist_m / 100) * 5
    reward = int(base * tier["reward_mult"])
    bonus  = int(reward * 0.30)

    return {
        "id":              str(uuid.uuid4())[:8],
        "tier":            tier_key,
        "venue_type":      venue_type,
        "customer_desire": random.choice(config.CUSTOMER_DESIRES[venue_type]),
        "customer_lat":    customer_lat,
        "customer_lon":    customer_lon,
        "reward":          reward,
        "bonus":           bonus,
        # Filled after player accepts (venue search) and selects (route calc):
        "venues":          None,
        "time_limit":      None,
        "venue_name":      None,
        "venue_lat":       None,
        "venue_lon":       None,
        "pickup_seconds":  None,
        "delivery_seconds":None,
        "leg1_geometry":   None,
        "leg2_geometry":   None,
    }


def fresh_order(player_pos):
    """Generate one new order centred on the player's CURRENT position."""
    return build_customer_order(_pick_venue_type(), player_pos)


def prepare_game(location_query, progress_cb=None):
    """
    Fast setup: one geocode call + initial order batch.
    New orders are generated on-demand (fresh_order) after each delivery/skip,
    always centred on the player's current position.
    """
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    if config.DEMO_SEED is not None:
        random.seed(config.DEMO_SEED)

    log("正在定位起始地點...")
    geocoder   = Geocoder()
    origin     = geocoder.geocode(location_query)
    player_pos = (origin["lat"], origin["lon"])

    log("正在生成顧客訂單...")
    initial = [
        build_customer_order(_pick_venue_type(), player_pos)
        for _ in range(config.MAX_VISIBLE_ORDERS)
    ]

    log("準備完成！即將開始遊戲...")
    return {
        "origin":              origin,
        "player_pos":          list(player_pos),
        "order_pool":          initial,
        "available_order_ids": [o["id"] for o in initial],
        "active_order":        None,
        "completed":           [],
        "skipped":             0,
        "money":               0,
        "phase":               "idle",
    }
