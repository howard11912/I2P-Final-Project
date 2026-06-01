# 外送大師 🏍️ — Delivery Master

A location-based delivery game built with Python, Flask, and real map APIs as a final project for CS101 (Introduction to Programming with Python).

## Gameplay

Players have **60 seconds** to complete as many delivery orders as possible.

1. **Browse orders** — 3 customer requests appear on the map simultaneously, each with a tier (普通 / 急單 / VIP) and reward amount
2. **Accept an order** — the app searches for real nearby restaurants or shops
3. **Pick a restaurant** — choose from the ranked list; the map shows all options with `#1`, `#2`... labels matching the sidebar
4. **Watch the delivery** — a motorcycle animates along the real walking route (restaurant → customer)
5. **Earn rewards** — deliver before the time limit for a punctuality bonus
6. **Repeat** — next order starts from your last delivery location

Final score is saved to the leaderboard.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Web server | Flask |
| Map rendering | Folium (Leaflet.js) |
| Geocoding | Nominatim (OpenStreetMap) |
| Routing | OSRM (Open Source Routing Machine) |
| Persistence | JSON file (leaderboard) |

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\Activate.ps1      # Windows PowerShell
# source venv/bin/activate     # macOS / Linux

# 2. Install dependencies
pip install flask folium requests

# 3. Run
cd FP
python app.py
```

Visit `http://localhost:5000` in your browser.

## Project Structure

```
FP/
├── app.py              # Flask routes and game state management
├── config.py           # All game parameters (duration, tiers, API settings)
├── utils/
│   ├── geocoding.py    # Nominatim API wrapper (with rate limiting)
│   ├── routing.py      # OSRM API wrapper (coordinate conversion, speed scaling)
│   ├── game_engine.py  # Order generation algorithm, random seed
│   └── map_builder.py  # Folium map + JS animation injection
├── templates/
│   ├── start.html      # Title screen with leaderboard management
│   ├── loading.html    # Loading screen (API calls run in background thread)
│   ├── game.html       # Main game screen (3-panel layout)
│   └── result.html     # Score settlement screen
├── static/css/style.css
└── data/leaderboard.json
```

## API Notes

Both APIs are **free and require no API key**.

**Nominatim** (geocoding & place search)
- Max 1 request/second — enforced automatically
- Must include a `User-Agent` header with contact email

**OSRM** (walking routes)
- Demo server: `https://router.project-osrm.org`
- Coordinates are `longitude, latitude` order (opposite of most libraries)

## Configuration

Key settings in `config.py`:

```python
GAME_DURATION       = 60    # seconds per round
DEMO_SEED           = 42    # fixed random seed for reproducible demos; set None to disable
VENUE_SEARCH_RADIUS = 2000  # metres to search for restaurants around player
DEBUG_LOCATION      = "國立清華大學, 新竹市東區, 台灣"  # pre-filled start location
```

## Game Architecture

```
Loading phase  (1 Nominatim call, ~2s)
  → Geocode player start location
  → Generate initial 3 orders

Accept order  (~1–3 Nominatim calls, ~1–3s)
  → Search venues near player using amenity= / shop= structured params
  → Fallback chain: 7-Eleven → 全家 → 萊爾富 → supermarket

Select restaurant  (2 OSRM calls, ~0.5s)
  → player → restaurant route (leg 1)
  → restaurant → customer route (leg 2)

Animation (no API calls)
  → Two-leg motorcycle animation runs entirely in the map iframe
  → postMessage to parent on arrival at restaurant and at customer
```
