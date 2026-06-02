import json
import os
import threading
import time
import uuid

from flask import (Flask, jsonify, redirect, render_template,
                   request, session, url_for)

import config
from utils.game_engine import prepare_game, fresh_order, haversine
from utils.geocoding import Geocoder
from utils.map_builder import build_map
from utils.routing import Router, RoutingError

app = Flask(__name__)
app.secret_key = "delivery-master-secret-2024"

# ── In-memory game store (keyed by game_id) ──────────────────────────
_games: dict = {}
_games_lock = threading.Lock()

def get_game():
    gid = session.get("game_id")
    return _games.get(gid) if gid else None

def set_game(data):
    gid = session.get("game_id")
    if gid:
        with _games_lock:
            _games[gid] = data

# ── Leaderboard helpers ───────────────────────────────────────────────
def load_leaderboard():
    try:
        with open(config.LEADERBOARD_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("scores", [])
    except Exception:
        return []

def _dedup_scores(scores):
    """Keep only the highest score per player name."""
    best = {}
    for s in scores:
        n = s["name"]
        if n not in best or s["money"] > best[n]["money"]:
            best[n] = s
    return sorted(best.values(), key=lambda x: x["money"], reverse=True)

def _write_leaderboard(scores):
    os.makedirs("data", exist_ok=True)
    with open(config.LEADERBOARD_FILE, "w", encoding="utf-8") as f:
        json.dump({"scores": scores}, f, ensure_ascii=False, indent=2)

def save_score(name, money, deliveries, city):
    scores = load_leaderboard()
    scores.append({"name": name, "money": money,
                   "deliveries": deliveries, "city": city,
                   "date": time.strftime("%Y-%m-%d")})
    scores = _dedup_scores(scores)[:config.LEADERBOARD_MAX]
    _write_leaderboard(scores)
    rank = next((i + 1 for i, s in enumerate(scores)
                 if s["name"] == name and s["money"] == money), None)
    return rank, scores

# ── Helper: get order from pool by id ────────────────────────────────
def _get_order(g, order_id):
    for o in g["order_pool"]:
        if o["id"] == order_id:
            return o
    return None

# ── Background venue prefetch ─────────────────────────────────────────
def _prefetch_venues(game_id, order_id, player_pos):
    """
    Called in a background thread right after a delivery is completed.
    Searches for venues near the player's new position and caches the
    result in order["venues_prefetched"] so that api_accept can skip
    the slow Nominatim call entirely.
    """
    # Small delay so we don't collide with the map-rebuild request
    # that happens at the same time in api_deliver.
    time.sleep(0.8)

    with _games_lock:
        g = _games.get(game_id)
    if not g:
        return

    order = _get_order(g, order_id)
    if not order or order.get("venues") or order.get("venues_prefetched"):
        # Already fetched (or the player already accepted the order)
        return

    vinfo = config.VENUE_TYPES[order["venue_type"]]
    plat, plon = player_pos
    geocoder = Geocoder()
    try:
        venues = geocoder.search_venues(
            plat, plon,
            amenity=vinfo.get("amenity"),
            shop=vinfo.get("shop"),
            query=vinfo.get("query"),
            limit=6,
        )
        for fq in vinfo.get("fallback_queries", []):
            if venues:
                break
            venues = geocoder.search_venues(
                plat, plon, query=fq, limit=6, radius=4000,
            )
    except Exception:
        venues = []

    if venues:
        with _games_lock:
            # Re-fetch game state inside the lock to avoid races
            g2 = _games.get(game_id)
            if not g2:
                return
            order2 = _get_order(g2, order_id)
            if order2 and not order2.get("venues") and not order2.get("venues_prefetched"):
                order2["venues_prefetched"] = venues

# ── Routes ────────────────────────────────────────────────────────────
@app.route("/")
def start():
    return render_template("start.html", scores=load_leaderboard())

@app.route("/api/leaderboard/delete", methods=["POST"])
def leaderboard_delete():
    data = request.json or {}
    name  = data.get("name")
    money = data.get("money")
    scores = load_leaderboard()
    scores = [s for s in scores
              if not (s["name"] == name and s["money"] == money)]
    _write_leaderboard(scores)
    return jsonify({"ok": True, "scores": scores})

@app.route("/api/leaderboard/dedup", methods=["POST"])
def leaderboard_dedup():
    scores = _dedup_scores(load_leaderboard())[:config.LEADERBOARD_MAX]
    _write_leaderboard(scores)
    return jsonify({"ok": True, "scores": scores})

@app.route("/init", methods=["POST"])
def init_game():
    player_name = request.form.get("player_name", "外送員").strip() or "外送員"
    location    = request.form.get("location", "台北市").strip() or "台北市"

    game_id = str(uuid.uuid4())
    session["game_id"] = game_id

    with _games_lock:
        _games[game_id] = {
            "status": "loading", "player_name": player_name,
            "location_query": location, "progress_msg": "初始化中...", "error": None,
        }

    def _setup():
        def cb(msg):
            with _games_lock:
                if game_id in _games:
                    _games[game_id]["progress_msg"] = msg
        try:
            data = prepare_game(location, progress_cb=cb)
            data["player_name"]    = player_name
            data["location_query"] = location
            data["status"]         = "ready"
            data["map_html"]       = build_map(data)
            with _games_lock:
                _games[game_id] = data
        except Exception as e:
            with _games_lock:
                if game_id in _games:
                    _games[game_id]["status"] = "error"
                    _games[game_id]["error"]  = str(e)

    threading.Thread(target=_setup, daemon=True).start()
    return redirect(url_for("loading"))

@app.route("/loading")
def loading():
    return render_template("loading.html")

@app.route("/api/loading_status")
def loading_status():
    g = get_game()
    if not g:
        return jsonify({"status": "error", "msg": "找不到遊戲，請重新開始"})
    return jsonify({"status": g.get("status", "loading"),
                    "msg":    g.get("progress_msg", ""),
                    "error":  g.get("error")})

@app.route("/game")
def game():
    g = get_game()
    if not g or g.get("status") != "ready":
        return redirect(url_for("start"))
    g["status"]     = "playing"
    g["start_time"] = time.time()
    g["phase"]      = "idle"
    set_game(g)
    return render_template("game.html",
                           player_name=g["player_name"],
                           game_duration=config.GAME_DURATION)

@app.route("/map_view")
def map_view():
    g = get_game()
    if not g:
        return "<p style='color:white;text-align:center;padding:2rem'>地圖載入中...</p>"
    return g.get("map_html", "")

@app.route("/api/state")
def api_state():
    g = get_game()
    if not g:
        return jsonify({"error": "no game"})

    elapsed   = time.time() - g.get("start_time", time.time())
    remaining = max(0, config.GAME_DURATION - elapsed)

    if remaining <= 0 and g.get("phase") != "finished":
        g["phase"] = "finished"
        set_game(g)

    pool      = {o["id"]: o for o in g["order_pool"]}
    available = [pool[oid] for oid in g.get("available_order_ids", []) if oid in pool]
    active    = pool.get(g["active_order"]) if g.get("active_order") else None

    venue_options = []
    if g["phase"] == "selecting_venue" and active:
        plat, plon = g["player_pos"]
        for i, v in enumerate(active.get("venues") or []):
            dist = haversine(plat, plon, v["lat"], v["lon"])
            venue_options.append({"idx": i, "name": v["name"], "dist_m": int(dist)})
        venue_options.sort(key=lambda x: x["dist_m"])

    return jsonify({
        "phase":            g["phase"],
        "money":            g["money"],
        "deliveries":       len(g["completed"]),
        "remaining":        int(remaining),
        "available_orders": available,
        "active_order":     active,
        "venue_options":    venue_options,
    })

@app.route("/api/accept", methods=["POST"])
def api_accept():
    g = get_game()
    if not g or g["phase"] != "idle":
        return jsonify({"ok": False, "msg": "無法接單"})

    order_id = request.json.get("order_id")
    order    = _get_order(g, order_id)
    if not order:
        return jsonify({"ok": False, "msg": "訂單不存在"})

    vinfo      = config.VENUE_TYPES[order["venue_type"]]
    plat, plon = g["player_pos"]

    # ── Use prefetched venues if available, otherwise fetch now ──────
    if order.get("venues_prefetched"):
        venues = order.pop("venues_prefetched")
    else:
        geocoder = Geocoder()
        try:
            venues = geocoder.search_venues(
                plat, plon,
                amenity=vinfo.get("amenity"),
                shop   =vinfo.get("shop"),
                query  =vinfo.get("query"),
                limit  =6,
            )
            for fq in vinfo.get("fallback_queries", []):
                if venues:
                    break
                venues = geocoder.search_venues(
                    plat, plon, query=fq, limit=6, radius=4000,
                )
        except Exception:
            venues = []

    if not venues:
        return jsonify({"ok": False, "msg": f"附近找不到 {vinfo['emoji']}，請換一單或換地點"})

    # Sort by distance from player and add rank
    venues.sort(key=lambda v: haversine(plat, plon, v["lat"], v["lon"]))
    for i, v in enumerate(venues):
        v["rank"] = i + 1

    order["venues"]    = venues
    g["active_order"]  = order_id
    g["phase"]         = "selecting_venue"
    g["available_order_ids"] = [oid for oid in g["available_order_ids"] if oid != order_id]
    g["map_html"]      = build_map(g)
    set_game(g)
    return jsonify({"ok": True})

@app.route("/api/select_venue", methods=["POST"])
def api_select_venue():
    """Player chose a specific restaurant — compute real routes now."""
    g = get_game()
    if not g or g["phase"] != "selecting_venue":
        return jsonify({"ok": False, "msg": "不在選餐廳階段"})

    venue_idx = request.json.get("venue_idx")
    order     = _get_order(g, g["active_order"])
    if not order:
        return jsonify({"ok": False, "msg": "找不到訂單"})

    venues = order.get("venues") or []
    if venue_idx is None or venue_idx < 0 or venue_idx >= len(venues):
        return jsonify({"ok": False, "msg": "無效的餐廳"})

    venue      = venues[venue_idx]
    player_pos = tuple(g["player_pos"])
    router     = Router()
    try:
        leg1 = router.get_route(player_pos, (venue["lat"], venue["lon"]))
        leg2 = router.get_route((venue["lat"], venue["lon"]),
                                (order["customer_lat"], order["customer_lon"]))
    except RoutingError as e:
        return jsonify({"ok": False, "msg": f"路線計算失敗：{e}"})

    t1         = router.game_seconds(leg1["duration_s"])
    t2         = router.game_seconds(leg2["duration_s"])
    time_limit = int((t1 + t2) * config.ORDER_TIERS[order["tier"]]["time_factor"])

    order["venue_name"]      = venue["name"]
    order["venue_lat"]       = venue["lat"]
    order["venue_lon"]       = venue["lon"]
    order["pickup_seconds"]  = t1
    order["delivery_seconds"]= t2
    order["time_limit"]      = time_limit
    order["leg1_geometry"]   = leg1["geometry"]
    order["leg2_geometry"]   = leg2["geometry"]

    g["phase"]             = "pickup"
    g["active_selected_at"]= time.time()
    g["map_html"]          = build_map(g)
    set_game(g)
    return jsonify({"ok": True, "pickup_seconds": t1,
                    "delivery_seconds": t2, "time_limit": time_limit})

@app.route("/api/pickup", methods=["POST"])
def api_pickup():
    g = get_game()
    if not g or g["phase"] != "pickup":
        return jsonify({"ok": False})
    g["phase"] = "delivery"
    set_game(g)
    return jsonify({"ok": True})

@app.route("/api/deliver", methods=["POST"])
def api_deliver():
    g = get_game()
    if not g or g["phase"] != "delivery":
        return jsonify({"ok": False})

    order   = _get_order(g, g["active_order"])
    elapsed = time.time() - g.get("active_selected_at", time.time())

    earned    = order["reward"]
    got_bonus = order["time_limit"] and elapsed <= order["time_limit"]
    if got_bonus:
        earned += order["bonus"]

    g["money"] += earned
    g["completed"].append({
        "order_id":  order["id"],
        "earned":    earned,
        "got_bonus": got_bonus,
        "tier":      order["tier"],
        "venue_name":order["venue_name"] or "（未知）",
    })

    # Advance player position to delivery endpoint
    g["player_pos"]  = [order["customer_lat"], order["customer_lon"]]
    g["active_order"]= None
    g["phase"]       = "idle"

    # Generate a fresh order centred on the player's NEW position
    new_order = fresh_order(tuple(g["player_pos"]))
    g["order_pool"].append(new_order)
    g["available_order_ids"].append(new_order["id"])
    g["map_html"] = build_map(g)
    set_game(g)

    # ── Prefetch venues for the new order in the background ──────────
    gid          = session.get("game_id")
    new_player_pos = tuple(g["player_pos"])
    threading.Thread(
        target=_prefetch_venues,
        args=(gid, new_order["id"], new_player_pos),
        daemon=True,
    ).start()

    return jsonify({"ok": True, "earned": earned, "got_bonus": got_bonus,
                    "bonus_amount": order["bonus"] if got_bonus else 0})

@app.route("/api/skip", methods=["POST"])
def api_skip():
    g = get_game()
    if not g or g["phase"] != "idle":
        return jsonify({"ok": False})

    order_id = request.json.get("order_id")
    g["available_order_ids"] = [oid for oid in g["available_order_ids"] if oid != order_id]
    g["skipped"] = g.get("skipped", 0) + 1

    # Replace skipped order with a fresh one at current player position
    new_order = fresh_order(tuple(g["player_pos"]))
    g["order_pool"].append(new_order)
    g["available_order_ids"].append(new_order["id"])
    g["map_html"] = build_map(g)
    set_game(g)

    # ── Prefetch venues for the replacement order ─────────────────────
    gid = session.get("game_id")
    threading.Thread(
        target=_prefetch_venues,
        args=(gid, new_order["id"], tuple(g["player_pos"])),
        daemon=True,
    ).start()

    return jsonify({"ok": True})

@app.route("/api/cancel_venue", methods=["POST"])
def api_cancel_venue():
    """Player changed their mind while selecting a venue — put the order back."""
    g = get_game()
    if not g or g["phase"] != "selecting_venue":
        return jsonify({"ok": False})

    order_id         = g["active_order"]
    g["active_order"]= None
    g["phase"]       = "idle"

    if order_id and order_id not in g["available_order_ids"]:
        g["available_order_ids"].insert(0, order_id)

    g["map_html"] = build_map(g)
    set_game(g)
    return jsonify({"ok": True})

@app.route("/api/end", methods=["POST"])
def api_end():
    g = get_game()
    if not g:
        return jsonify({"ok": False})
    g["phase"] = "finished"
    set_game(g)
    return jsonify({"ok": True})

@app.route("/result")
def result():
    g = get_game()
    if not g:
        return redirect(url_for("start"))
    rank, scores = save_score(
        g["player_name"], g["money"],
        len(g["completed"]), g.get("location_query", "")
    )
    return render_template("result.html",
                           player_name=g["player_name"],
                           money=g["money"],
                           deliveries=len(g["completed"]),
                           completed=g["completed"],
                           city=g.get("location_query", ""),
                           rank=rank,
                           scores=scores)

if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
