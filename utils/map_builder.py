import json
import folium
import config


def _simplify(route, max_pts=60):
    n = len(route)
    if n <= max_pts:
        return route
    step = (n - 1) / (max_pts - 1)
    return [route[round(i * step)] for i in range(max_pts - 1)] + [route[-1]]


def _inject(html, script):
    for tag in ["</body>", "</html>"]:
        if tag in html:
            return html.replace(tag, script + "\n" + tag, 1)
    return html + script


_FIND_MAP = """
  function findMap() {
    var keys = Object.keys(window), k;
    for (var i = 0; i < keys.length; i++) {
      k = keys[i];
      if (/^map_[a-f0-9]+$/.test(k) && window[k] &&
          typeof window[k].addLayer === 'function') return window[k];
    }
    return null;
  }
"""


_ANIM_FN = """
  function makeMoto(map, startLatLng) {
    var icon = L.divIcon({
      html: '<span id="ms" style="font-size:24px;line-height:1;display:inline-block;' +
            'will-change:transform;transform:translateZ(0)">🏍️</span>',
      iconSize: [30,30], iconAnchor: [15,15], className: ''
    });
    return L.marker(startLatLng, {icon: icon, zIndexOffset: 9999}).addTo(map);
  }

  function animateLeg(marker, route, durMs, spr, onDone) {
    var done = false, safety = null, timer = null, t0 = 0;

    function finish() {
      if (done) return;
      done = true;
      if (timer)  { clearInterval(timer); timer = null; }
      if (safety) { clearTimeout(safety); safety = null; }
      if (route && route.length) {
        var last = route[route.length - 1];
        marker.setLatLng([last[0], last[1]]);
      }
      onDone();
    }

    if (!route || route.length < 2) {
      if (route && route.length === 1) marker.setLatLng(route[0]);
      safety = setTimeout(finish, durMs);
      return;
    }

    function render(now) {
      if (done) return;
      var prog = Math.min((now - t0) / durMs, 1);
      var pos  = prog * (route.length - 1);
      var idx  = Math.min(Math.floor(pos), route.length - 2);
      var f    = pos - idx;

      marker.setLatLng([
        route[idx][0] + (route[idx+1][0] - route[idx][0]) * f,
        route[idx][1] + (route[idx+1][1] - route[idx][1]) * f
      ]);

      if (!spr.el) {
        var el = marker.getElement();
        if (el) spr.el = el.querySelector('#ms');
      }

      if (spr.el) {
        var nx = Math.min(idx + 1, route.length - 1);
        spr.el.style.transform =
          route[nx][1] >= route[idx][1] ? 'scaleX(-1) translateZ(0)' : 'translateZ(0)';
      }

      if (prog >= 1) finish();
    }

    t0 = performance.now();
    safety = setTimeout(finish, durMs + 3000);
    timer  = setInterval(function() { render(performance.now()); }, 250);

    (function raf() {
      if (done) return;
      render(performance.now());
      if (!done) requestAnimationFrame(raf);
    })();
  }
"""


_TWO_LEG_TPL = """<script>
(function() {
  var LEG1 = __LEG1__;
  var LEG2 = __LEG2__;
  var DUR1 = Math.max(__DUR1__, 800);
  var DUR2 = Math.max(__DUR2__, 800);
  var tries = 0;

  __FINDMAP__
  __ANIMFN__

  function runJourney(map) {
    var start = (LEG1 && LEG1.length) ? LEG1[0]
              : (LEG2 && LEG2.length) ? LEG2[0] : null;

    if (!start) {
      try { window.parent.postMessage({type: 'pickup_done'}, '*'); } catch(e) {}
      try { window.parent.postMessage({type: 'delivery_done'}, '*'); } catch(e) {}
      return;
    }

    var marker = makeMoto(map, start);
    var spr = {el: null};

    animateLeg(marker, LEG1, DUR1, spr, function() {
      try { window.parent.postMessage({type: 'pickup_done'}, '*'); } catch(e) {}

      animateLeg(marker, LEG2, DUR2, spr, function() {
        try { window.parent.postMessage({type: 'delivery_done'}, '*'); } catch(e) {}
      });
    });
  }

  function tryStart() {
    var map = findMap();
    if (!map) {
      if (++tries < 60) setTimeout(tryStart, 100);
      return;
    }
    runJourney(map);
  }

  setTimeout(tryStart, 400);
})();
</script>"""


def _two_leg_script(leg1, leg2, dur1_s, dur2_s):
    return (_TWO_LEG_TPL
            .replace('__LEG1__', json.dumps(leg1))
            .replace('__LEG2__', json.dumps(leg2))
            .replace('__DUR1__', str(int(dur1_s * 1000)))
            .replace('__DUR2__', str(int(dur2_s * 1000)))
            .replace('__FINDMAP__', _FIND_MAP)
            .replace('__ANIMFN__', _ANIM_FN))


_ONE_LEG_TPL = """<script>
(function() {
  var ROUTE = __ROUTE__;
  var DUR   = Math.max(__DUR__, 800);
  var PHASE = '__PHASE__';
  var tries = 0;

  __FINDMAP__
  __ANIMFN__

  function tryStart() {
    var map = findMap();

    if (!map) {
      if (++tries < 60) setTimeout(tryStart, 100);
      return;
    }

    var start = (ROUTE && ROUTE.length) ? ROUTE[0] : null;

    if (!start) {
      try { window.parent.postMessage({type: PHASE + '_done'}, '*'); } catch(e) {}
      return;
    }

    var marker = makeMoto(map, start);
    var spr = {el: null};

    animateLeg(marker, ROUTE, DUR, spr, function() {
      try { window.parent.postMessage({type: PHASE + '_done'}, '*'); } catch(e) {}
    });
  }

  setTimeout(tryStart, 400);
})();
</script>"""


def _one_leg_script(route, dur_s, phase):
    return (_ONE_LEG_TPL
            .replace('__ROUTE__', json.dumps(route))
            .replace('__DUR__', str(int(dur_s * 1000)))
            .replace('__PHASE__', phase)
            .replace('__FINDMAP__', _FIND_MAP)
            .replace('__ANIMFN__', _ANIM_FN))


_CLICK_TPL = """<script>
(function() {
  var DATA  = __DATA__;
  var MTYPE = '__MTYPE__';
  var IKEY  = '__IKEY__';

  __FINDMAP__

  setTimeout(function() {
    var map = findMap();
    if (!map) return;

    map.eachLayer(function(layer) {
      if (!layer.getLatLng) return;

      var ll = layer.getLatLng();

      for (var i = 0; i < DATA.length; i++) {
        var d = DATA[i];

        if (Math.abs(ll.lat - d.lat) < 0.0003 &&
            Math.abs(ll.lng - d.lon) < 0.0003) {

          (function(dd) {
            var _last = 0;

            layer.on('click', function() {
              var now = Date.now();
              if (now - _last < 400) return;
              _last = now;

              var msg = {type: MTYPE};
              msg[IKEY] = dd[IKEY];

              window.parent.postMessage(msg, '*');
            });
          })(d);
        }
      }
    });
  }, 700);
})();
</script>"""


def _click_script(data, msg_type, id_field):
    return (_CLICK_TPL
            .replace('__DATA__', json.dumps(data))
            .replace('__MTYPE__', msg_type)
            .replace('__IKEY__', id_field)
            .replace('__FINDMAP__', _FIND_MAP))


_HIGHLIGHT_VENUE_TPL = """<script>
(function() {
  var DATA = __DATA__;
  var EMOJI = __EMOJI__;
  var markerLayers = {};
  var normalIcons = {};

  __FINDMAP__

  function makeHighlightIcon(rank) {
    return L.divIcon({
      html:
        '<div style="text-align:center;line-height:1;transform:scale(1.45);transition:.2s;">' +
          '<div style="background:#f39c12;color:#111;border-radius:50%;' +
          'width:44px;height:44px;display:flex;align-items:center;' +
          'justify-content:center;font-weight:bold;font-size:21px;' +
          'border:4px solid #fff;' +
          'box-shadow:0 0 18px #f39c12,0 0 35px rgba(243,156,18,.85);' +
          'margin:0 auto;">' + rank + '</div>' +
          '<div style="font-size:20px;margin-top:2px;text-shadow:0 0 5px #fff,0 0 5px #fff;">' +
            EMOJI +
          '</div>' +
        '</div>',
      iconSize: [58, 70],
      iconAnchor: [29, 14],
      className: ''
    });
  }

  function setupVenueMarkers() {
    var map = findMap();
    if (!map) return;

    map.eachLayer(function(layer) {
      if (!layer.getLatLng || !layer.setIcon) return;

      var ll = layer.getLatLng();

      for (var i = 0; i < DATA.length; i++) {
        var d = DATA[i];

        if (Math.abs(ll.lat - d.lat) < 0.0003 &&
            Math.abs(ll.lng - d.lon) < 0.0003) {

          markerLayers[d.idx] = layer;
          normalIcons[d.idx] = layer.options.icon;
        }
      }
    });
  }

  window.addEventListener('message', function(e) {
    if (!e.data || !e.data.type) return;

    var idx = e.data.idx;
    var layer = markerLayers[idx];

    if (!layer) return;

    if (e.data.type === 'highlight_venue_marker') {
      layer.setIcon(makeHighlightIcon(idx + 1));
      layer.setZIndexOffset(9999);

      var map = findMap();

      if (map) {
        map.panTo(layer.getLatLng(), {
          animate: true,
          duration: 0.3
        });
      }

      if (layer.openPopup) layer.openPopup();
    }

    if (e.data.type === 'unhighlight_venue_marker') {
      if (normalIcons[idx]) {
        layer.setIcon(normalIcons[idx]);
        layer.setZIndexOffset(0);
      }

      if (layer.closePopup) layer.closePopup();
    }
  });

  setTimeout(setupVenueMarkers, 800);
})();
</script>"""


def _highlight_venue_script(data, emoji):
    return (_HIGHLIGHT_VENUE_TPL
            .replace('__DATA__', json.dumps(data))
            .replace('__EMOJI__', json.dumps(emoji))
            .replace('__FINDMAP__', _FIND_MAP))


def _venue_div_icon(rank, emoji):
    colours = ["#e74c3c", "#2980b9", "#27ae60", "#8e44ad", "#d35400", "#16a085"]
    bg = colours[(rank - 1) % len(colours)]

    html = (
        f'<div style="text-align:center;line-height:1;">'
        f'<div style="background:{bg};color:#fff;border-radius:50%;'
        f'width:30px;height:30px;display:flex;align-items:center;'
        f'justify-content:center;font-weight:bold;font-size:14px;'
        f'border:2px solid #fff;box-shadow:0 2px 5px rgba(0,0,0,0.45);'
        f'margin:0 auto;">{rank}</div>'
        f'<div style="font-size:14px;margin-top:1px;'
        f'text-shadow:0 0 3px #fff,0 0 3px #fff;">{emoji}</div>'
        f'</div>'
    )

    return folium.DivIcon(
        html=html,
        icon_size=(34, 46),
        icon_anchor=(17, 8)
    )


def build_map(game_data):
    origin = game_data["origin"]
    phase = game_data["phase"]
    player_pos = game_data.get("player_pos", [origin["lat"], origin["lon"]])
    pool = {o["id"]: o for o in game_data["order_pool"]}
    active = pool.get(game_data.get("active_order"))

    m = folium.Map(
        location=[origin["lat"], origin["lon"]],
        zoom_start=config.DEFAULT_MAP_ZOOM,
        tiles=config.MAP_TILE,
    )

    at_origin = (
        abs(player_pos[0] - origin["lat"]) < 0.0001 and
        abs(player_pos[1] - origin["lon"]) < 0.0001
    )

    if at_origin:
        folium.Marker(
            location=[origin["lat"], origin["lon"]],
            tooltip="🏠 起點",
            popup=folium.Popup(
                f"<b>起點</b><br>{origin['display_name'][:60]}",
                max_width=220
            ),
            icon=folium.Icon(color="green", icon="home", prefix="fa"),
        ).add_to(m)
    else:
        folium.Marker(
            location=player_pos,
            tooltip="🏍️ 你目前的位置",
            icon=folium.Icon(color="blue", icon="motorcycle", prefix="fa"),
        ).add_to(m)

    if active and phase == "pickup":
        _add_delivery_markers(m, active)
        leg1 = _simplify(active["leg1_geometry"] or [])
        leg2 = _simplify(active["leg2_geometry"] or [])
        _fit(m, leg1 + leg2, origin)

        html = m.get_root().render()

        return _inject(
            html,
            _two_leg_script(
                leg1,
                leg2,
                active["pickup_seconds"],
                active["delivery_seconds"]
            )
        )

    if active and phase == "delivery":
        _add_delivery_markers(m, active, pickup_done=True)
        leg2 = _simplify(active.get("leg2_geometry") or [])
        _fit(m, leg2, origin)

        html = m.get_root().render()

        return _inject(
            html,
            _one_leg_script(
                leg2,
                active["delivery_seconds"],
                "delivery"
            )
        )

    if active and phase == "selecting_venue":
        vtype = config.VENUE_TYPES[active["venue_type"]]
        tier = config.ORDER_TIERS[active["tier"]]
        venues = active.get("venues") or []

        folium.Marker(
            location=[active["customer_lat"], active["customer_lon"]],
            tooltip=f"📍 {active.get('customer_desire', '顧客')}",
            popup=folium.Popup(
                f"<b>{tier['emoji']} {active['tier']}</b><br>"
                f"{active.get('customer_desire', '')}<br>"
                f"💰 ${active['reward']} + 準時 +${active['bonus']}",
                max_width=200,
            ),
            icon=folium.Icon(color="orange", icon="user", prefix="fa"),
        ).add_to(m)

        for v in venues:
            rank = v.get("rank", "?")

            folium.Marker(
                location=[v["lat"], v["lon"]],
                tooltip=f"#{rank} {vtype['emoji']} {v['name']}（點地圖可選）",
                popup=folium.Popup(
                    f"<b>#{rank} {vtype['emoji']} {v['name']}</b><br>"
                    f"點右側 #<b>{rank}</b> 「選這家」接單",
                    max_width=200,
                ),
                icon=_venue_div_icon(rank, vtype["emoji"]),
            ).add_to(m)

        all_lats = (
            [active["customer_lat"], origin["lat"], player_pos[0]]
            + [v["lat"] for v in venues]
        )

        all_lons = (
            [active["customer_lon"], origin["lon"], player_pos[1]]
            + [v["lon"] for v in venues]
        )

        m.fit_bounds([
            [min(all_lats), min(all_lons)],
            [max(all_lats), max(all_lons)]
        ])

        html = m.get_root().render()

        venue_data = [
            {
                "lat": v["lat"],
                "lon": v["lon"],
                "idx": v.get("rank", i + 1) - 1
            }
            for i, v in enumerate(venues)
        ]

        html = _inject(html, _click_script(venue_data, "venue_click", "idx"))
        html = _inject(html, _highlight_venue_script(venue_data, vtype["emoji"]))

        return html

    available_ids = game_data.get("available_order_ids", [])
    order_data = []

    if available_ids:
        all_lats = [origin["lat"], player_pos[0]]
        all_lons = [origin["lon"], player_pos[1]]

        for oid in available_ids:
            o = pool.get(oid)

            if not o:
                continue

            tier = config.ORDER_TIERS[o["tier"]]
            vtype = config.VENUE_TYPES[o["venue_type"]]

            color = (
                "orange" if o["tier"] == "VIP"
                else "beige" if o["tier"] == "急單"
                else "lightgray"
            )

            folium.Marker(
                location=[o["customer_lat"], o["customer_lon"]],
                tooltip=f"{tier['emoji']} {o['tier']} | {vtype['emoji']} | 💰${o['reward']}",
                popup=folium.Popup(
                    f"<b>{tier['emoji']} {o['tier']}</b><br>"
                    f"{o.get('customer_desire', '')}<br>"
                    f"💰 ${o['reward']} + 準時 +${o['bonus']}",
                    max_width=200,
                ),
                icon=folium.Icon(color=color, icon="user", prefix="fa"),
            ).add_to(m)

            all_lats.append(o["customer_lat"])
            all_lons.append(o["customer_lon"])

            order_data.append({
                "lat": o["customer_lat"],
                "lon": o["customer_lon"],
                "id": o["id"]
            })

        m.fit_bounds([
            [min(all_lats), min(all_lons)],
            [max(all_lats), max(all_lons)]
        ])

    html = m.get_root().render()

    if order_data:
        html = _inject(html, _click_script(order_data, "marker_click", "id"))

    return html


def _add_delivery_markers(m, active, pickup_done=False):
    vtype = config.VENUE_TYPES[active["venue_type"]]

    if active.get("leg1_geometry"):
        folium.PolyLine(
            locations=active["leg1_geometry"],
            color="#FDCB6E",
            weight=4,
            opacity=0.7,
            tooltip="取餐路線"
        ).add_to(m)

    if active.get("leg2_geometry"):
        folium.PolyLine(
            locations=active["leg2_geometry"],
            color="#74B9FF",
            weight=4,
            opacity=0.7,
            tooltip="外送路線"
        ).add_to(m)

    if active.get("venue_lat"):
        folium.Marker(
            location=[active["venue_lat"], active["venue_lon"]],
            tooltip=f"{vtype['emoji']} {active['venue_name']}",
            icon=folium.Icon(
                color="gray" if pickup_done else vtype["folium_color"],
                icon="shopping-bag",
                prefix="fa",
            ),
        ).add_to(m)

    folium.Marker(
        location=[active["customer_lat"], active["customer_lon"]],
        tooltip="📍 顧客位置",
        icon=folium.Icon(color="orange", icon="user", prefix="fa"),
    ).add_to(m)


def _fit(m, coords, origin):
    all_c = list(coords) + [[origin["lat"], origin["lon"]]]

    if len(all_c) > 1:
        m.fit_bounds([
            [min(c[0] for c in all_c), min(c[1] for c in all_c)],
            [max(c[0] for c in all_c), max(c[1] for c in all_c)]
        ])
