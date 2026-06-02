GAME_DURATION = 60          # seconds per round
MAX_VISIBLE_ORDERS = 3      # orders shown at once
ORDER_POOL_SIZE = 12        # pre-generate before game starts

# In-game travel speed: osrm_minutes * factor = game_seconds
SPEED_FACTOR = 0.4
MIN_TRAVEL_SECONDS = 3
MAX_TRAVEL_SECONDS = 12

NOMINATIM_URL = "https://nominatim.openstreetmap.org"
OSRM_URL = "http://router.project-osrm.org"
USER_AGENT = "jjdavid91988@gmail.com"
API_DELAY = 1.1             # Nominatim: >= 1 req/s

DEBUG_LOCATION = "國立清華大學, 新竹市東區, 台灣"
VENUE_SEARCH_RADIUS = 2000  # metres around player when searching restaurants

# Use Nominatim structured params (amenity= / shop=) for much better results
VENUE_TYPES = {
    "restaurant": {"amenity": "restaurant", "emoji": "🍔", "color": "#FF6B6B", "folium_color": "red",    "base_reward_range": (60, 120)},
    "bubble_tea": {"amenity": "cafe",       "emoji": "🧋", "color": "#4ECDC4", "folium_color": "blue",  "base_reward_range": (40, 90)},
    "convenience":{"query": "7-Eleven", "fallback_queries": ["全家", "萊爾富", "supermarket"],
                   "emoji": "🏪", "color": "#A29BFE", "folium_color": "purple", "base_reward_range": (30, 70)},
}

ORDER_TIERS = {
    "普通": {"emoji": "🟢", "label_color": "#00B894", "reward_mult": 1.0, "time_factor": 1.6, "weight": 60},
    "急單": {"emoji": "🟡", "label_color": "#FDCB6E", "reward_mult": 1.5, "time_factor": 1.1, "weight": 30},
    "VIP":  {"emoji": "🔴", "label_color": "#E17055", "reward_mult": 2.5, "time_factor": 1.3, "weight": 10},
}

CUSTOMER_DESIRES = {
    "restaurant": ["好想吃熱炒 🍳", "幫我訂一份正餐 🍽️", "肚子超餓，要吃飯！", "想吃點有份量的..."],
    "bubble_tea": ["超想喝手搖飲 🧋", "天氣好熱！要冰飲料", "一杯奶茶解解饞 🥤", "要喝飲料～"],
    "convenience": ["幫我買個便當 🏪", "需要買些日用品", "超商買點零食就好", "快去全家幫我買！"],
}

# Fixed random seed for reproducible demos. Set to None for normal random play.
DEMO_SEED = 42

LEADERBOARD_FILE = "data/leaderboard.json"
LEADERBOARD_MAX = 10

DEFAULT_MAP_ZOOM = 15
MAP_TILE = "CartoDB dark_matter"
