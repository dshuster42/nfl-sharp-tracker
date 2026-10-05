"""
NFL sharp-money tracker.

Pulls games from an Apify task (Action Network scraper), keeps a season-long
store in data.json, flags reverse line movement, and optionally pushes alerts
to your phone through ntfy.

Env vars (set as GitHub secrets):
  APIFY_TOKEN    your Apify API token (required)
  APIFY_TASK_ID  your saved Apify task, e.g. "yourname~nfl-splits" (required)
  NTFY_TOPIC     ntfy topic for push alerts (optional)
  THRESHOLD      public ticket % that counts as lopsided (optional, default 70)

Local test:  python scripts/tracker.py --file sample.json
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data.json"
KEY_NUMBERS = (3, 7)


# ---------- fetch ----------

def fetch_from_apify(token, task_id):
    url = (
        "https://api.apify.com/v2/actor-tasks/"
        + urllib.parse.quote(task_id, safe="~")
        + "/run-sync-get-dataset-items?format=json&clean=true"
    )
    req = urllib.request.Request(
        url,
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=330) as resp:
        return json.load(resp)


# ---------- normalize ----------

def pct(node):
    node = node or {}
    return {"t": node.get("ticketsPercent"), "m": node.get("moneyPercent")}


def team(node):
    node = node or {}
    return {
        "abbr": node.get("abbreviation"),
        "name": node.get("displayName") or node.get("name"),
        "color": node.get("primaryColor"),
    }


def normalize(raw):
    lm = raw.get("lineMovement") or {}
    pb = raw.get("publicBetting") or {}
    box = raw.get("boxscore") or {}
    res = raw.get("result") or {}
    final = None
    if raw.get("isFinal") and box.get("homeScore") is not None:
        final = {"home": box.get("homeScore"), "away": box.get("awayScore")}
    return {
        "id": raw.get("gameId"),
        "season": raw.get("season"),
        "week": raw.get("week"),
        "start": raw.get("startTime"),
        "status": "final" if raw.get("isFinal") else ("live" if raw.get("isLive") else "upcoming"),
        "home": team(raw.get("homeTeam")),
        "away": team(raw.get("awayTeam")),
        "spread": {
            "open": lm.get("openSpreadHome"),
            "current": lm.get("currentSpreadHome", raw.get("consensusSpreadHome")),
            "close": res.get("closingSpreadHome"),
        },
        "total": {
            "open": lm.get("openTotal"),
            "current": lm.get("currentTotal", raw.get("consensusTotal")),
            "close": res.get("closingTotal"),
        },
        "splits": {
            "spreadHome": pct(pb.get("spreadHome")),
            "spreadAway": pct(pb.get("spreadAway")),
            "over": pct(pb.get("over")),
            "under": pct(pb.get("under")),
        },
        "betCount": raw.get("betCount"),
        "url": raw.get("url"),
        "final": final,
    }


def merge(old, new, now):
    """Update a stored game. Lines and splits freeze once the game kicks off."""
    if old is None or old["status"] == "upcoming" or new["status"] == "upcoming":
        merged = dict(new)
        merged["snapshotAt"] = now
        if old:
            merged["alerted"] = old.get("alerted", [])
        return merged
    merged = dict(old)
    merged["status"] = new["status"]
    if new["final"]:
        merged["final"] = new["final"]
    for market in ("spread", "total"):
        if new[market]["close"] is not None:
            merged[market] = dict(old[market], close=new[market]["close"])
    return merged


# ---------- flag logic (mirrored in index.html) ----------

def _num(x):
    return x if isinstance(x, (int, float)) else None


def crosses_key(a, b):
    lo, hi = sorted((abs(a), abs(b)))
    return a != b and any(lo <= k <= hi for k in KEY_NUMBERS)


def flags_for(game, threshold):
    out = []
    s = game["splits"]
    o, c = _num(game["spread"]["open"]), _num(game["spread"]["current"])
    if o is not None and c is not None:
        for side, other in (("home", "away"), ("away", "home")):
            pub = s["spreadHome" if side == "home" else "spreadAway"]
            sharp = s["spreadHome" if other == "home" else "spreadAway"]
            if (pub["t"] or 0) < threshold:
                continue
            sign = 1 if side == "home" else -1
            move = sign * c - sign * o  # positive = line got better for the public side
            if move > 0:
                out.append({
                    "market": "spread",
                    "publicSide": side,
                    "sharpSide": other,
                    "sharpLine": -sign * c,
                    "publicPct": pub["t"],
                    "move": move,
                    "gap": (sharp["m"] or 0) - (sharp["t"] or 0),
                    "keyNumber": crosses_key(o, c),
                })
    o, c = _num(game["total"]["open"]), _num(game["total"]["current"])
    if o is not None and c is not None:
        for side, other, wrong_way in (("over", "under", c < o), ("under", "over", c > o)):
            pub, sharp = s[side], s[other]
            if (pub["t"] or 0) >= threshold and wrong_way:
                out.append({
                    "market": "total",
                    "publicSide": side,
                    "sharpSide": other,
                    "sharpLine": c,
                    "publicPct": pub["t"],
                    "move": abs(c - o),
                    "gap": (sharp["m"] or 0) - (sharp["t"] or 0),
                    "keyNumber": False,
                })
    return out


def label(game, flag):
    if flag["market"] == "spread":
        t = game[flag["sharpSide"]]["name"]
        line = flag["sharpLine"]
        return f"{t} {'+' if line > 0 else ''}{line:g}" if line else f"{t} PK"
    return f"{flag['sharpSide'].title()} {flag['sharpLine']:g}"


# ---------- alerts ----------

def notify(topic, title, body):
    req = urllib.request.Request(
        "https://ntfy.sh/" + urllib.parse.quote(topic),
        data=body.encode(),
        method="POST",
        headers={"Title": title, "Tags": "football"},
    )
    try:
        urllib.request.urlopen(req, timeout=20)
    except Exception as exc:  # alerts are best-effort
        print(f"ntfy failed: {exc}", file=sys.stderr)


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="read scraper output from a local JSON file instead of Apify")
    args = ap.parse_args()

    threshold = float(os.environ.get("THRESHOLD", 70))
    if args.file:
        rows = json.loads(Path(args.file).read_text())
    else:
        token, task = os.environ.get("APIFY_TOKEN"), os.environ.get("APIFY_TASK_ID")
        if not token or not task:
            sys.exit("Missing APIFY_TOKEN or APIFY_TASK_ID secret.")
        rows = fetch_from_apify(token, task)

    store = json.loads(STORE.read_text()) if STORE.exists() else {"games": {}}
    games = store.get("games", {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    topic = os.environ.get("NTFY_TOPIC")

    seen = 0
    for raw in rows:
        if raw.get("league") != "nfl" or raw.get("period", "event") != "event":
            continue
        seen += 1
        new = normalize(raw)
        key = str(new["id"])
        game = merge(games.get(key), new, now)
        games[key] = game

        if game["status"] != "upcoming":
            continue
        game.setdefault("alerted", [])
        for flag in flags_for(game, threshold):
            fkey = f"{flag['market']}:{flag['sharpSide']}"
            if fkey in game["alerted"]:
                continue
            game["alerted"].append(fkey)
            pick = label(game, flag)
            msg = (f"{game['away']['abbr']} @ {game['home']['abbr']}: {flag['publicPct']:g}% of tickets "
                   f"on the {flag['publicSide']}, line moved {flag['move']:g} the other way.")
            print(f"FLAG  {pick}  |  {msg}")
            if topic:
                notify(topic, f"Sharp side: {pick}", msg)

    store = {"updatedAt": now, "defaultThreshold": threshold, "games": games}
    STORE.write_text(json.dumps(store, indent=1))
    print(f"Processed {seen} NFL games; store now holds {len(games)}.")


if __name__ == "__main__":
    main()
