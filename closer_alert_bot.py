import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

import requests

# =========================
# Config
# =========================
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
POLL_MINUTES = int(os.getenv("POLL_MINUTES", "10"))
STATE_DIR = os.getenv("STATE_DIR", "/var/data")
STATE_FILE = os.path.join(STATE_DIR, "closer_alert_state.json")

# Optional: JSON string like {"NYY":"Devin Williams","NYM":"Edwin Diaz"}
CLOSER_MAP_JSON = os.getenv("CLOSER_MAP_JSON", "").strip()

MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
MLB_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

USER_AGENT = "closer-alert-bot/1.0"


# =========================
# Helpers
# =========================
def ensure_state_dir() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)


def load_state() -> Dict:
    ensure_state_dir()
    if not os.path.exists(STATE_FILE):
        return {
            "posted_keys": [],
            "seen_game_updates": {},
            "last_run_utc": None,
        }
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("posted_keys", [])
        data.setdefault("seen_game_updates", {})
        data.setdefault("last_run_utc", None)
        return data
    except Exception:
        return {
            "posted_keys": [],
            "seen_game_updates": {},
            "last_run_utc": None,
        }


def save_state(state: Dict) -> None:
    ensure_state_dir()
    # cap old posted keys so file doesn't grow forever
    posted = state.get("posted_keys", [])
    if len(posted) > 5000:
        state["posted_keys"] = posted[-3000:]

    seen = state.get("seen_game_updates", {})
    # keep only recent game update stamps
    if len(seen) > 500:
        trimmed_items = list(seen.items())[-300:]
        state["seen_game_updates"] = dict(trimmed_items)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def load_closer_map() -> Dict[str, str]:
    if not CLOSER_MAP_JSON:
        return {}
    try:
        raw = json.loads(CLOSER_MAP_JSON)
        return {str(k).upper(): str(v) for k, v in raw.items()}
    except Exception:
        return {}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def requests_get_json(url: str, params: Optional[Dict] = None) -> Dict:
    resp = requests.get(
        url,
        params=params,
        timeout=30,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    return resp.json()


def post_discord_embed(embed: Dict) -> bool:
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError("Missing DISCORD_WEBHOOK_URL env var")

    payload = {"embeds": [embed]}
    resp = requests.post(
        DISCORD_WEBHOOK_URL,
        json=payload,
        timeout=30,
        headers={"User-Agent": USER_AGENT},
    )

    if resp.status_code in (200, 204):
        return True

    if resp.status_code == 429:
        retry_after = 5
        try:
            retry_after = max(1, int(resp.json().get("retry_after", 5)))
        except Exception:
            pass
        print(f"[BOT] Discord rate limited. Sleeping {retry_after}s")
        time.sleep(retry_after)
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=30,
            headers={"User-Agent": USER_AGENT},
        )
        return resp.status_code in (200, 204)

    print(f"[BOT] Discord post failed: {resp.status_code} {resp.text[:500]}")
    return False


def short_innings(outs: Optional[int]) -> str:
    if outs is None:
        return "—"
    whole = outs // 3
    rem = outs % 3
    return f"{whole}.{rem}"


def get_recent_dates() -> List[str]:
    # today + yesterday catches late finals / overnight timing
    eastern_buffer = [
        datetime.now(timezone.utc).date(),
        (datetime.now(timezone.utc) - timedelta(days=1)).date(),
    ]
    return [d.isoformat() for d in eastern_buffer]


def get_schedule_games_for_date(date_str: str) -> List[Dict]:
    params = {
        "sportId": 1,
        "date": date_str,
        "hydrate": "team,linescore,decisions",
    }
    data = requests_get_json(MLB_SCHEDULE_URL, params=params)
    dates = data.get("dates", [])
    if not dates:
        return []
    return dates[0].get("games", [])


def is_final_game(game: Dict) -> bool:
    detailed = (
        game.get("status", {}).get("detailedState", "") or ""
    ).lower()
    abstract = (
        game.get("status", {}).get("abstractGameState", "") or ""
    ).lower()

    final_markers = {"final", "game over", "completed early"}
    return detailed in final_markers or abstract == "final"


def extract_game_meta(game: Dict) -> Dict:
    teams = game.get("teams", {})
    away = teams.get("away", {}).get("team", {})
    home = teams.get("home", {}).get("team", {})

    return {
        "gamePk": game.get("gamePk"),
        "gameDate": game.get("gameDate"),
        "away_name": away.get("name", "Away"),
        "away_abbr": away.get("abbreviation", "AWY"),
        "home_name": home.get("name", "Home"),
        "home_abbr": home.get("abbreviation", "HME"),
        "away_score": teams.get("away", {}).get("score"),
        "home_score": teams.get("home", {}).get("score"),
        "winning_team_name": (
            away.get("name")
            if (teams.get("away", {}).get("isWinner") is True)
            else home.get("name")
        ),
        "winning_team_abbr": (
            away.get("abbreviation")
            if (teams.get("away", {}).get("isWinner") is True)
            else home.get("abbreviation")
        ),
        "losing_team_name": (
            home.get("name")
            if (teams.get("away", {}).get("isWinner") is True)
            else away.get("name")
        ),
        "losing_team_abbr": (
            home.get("abbreviation")
            if (teams.get("away", {}).get("isWinner") is True)
            else away.get("abbreviation")
        ),
    }


def get_live_feed(game_pk: int) -> Dict:
    return requests_get_json(MLB_FEED_URL.format(game_pk=game_pk))


def iter_team_pitchers(team_box: Dict) -> List[Dict]:
    players = team_box.get("players", {}) or {}
    out = []
    for _, pdata in players.items():
        stats = pdata.get("stats", {}).get("pitching", {}) or {}
        if not stats:
            continue
        out.append(
            {
                "id": pdata.get("person", {}).get("id"),
                "name": pdata.get("person", {}).get("fullName", "Unknown Pitcher"),
                "jersey": pdata.get("jerseyNumber"),
                "stats": stats,
            }
        )
    return out


def detect_save_pitchers(feed: Dict) -> List[Dict]:
    out = []
    boxscore = feed.get("liveData", {}).get("boxscore", {}).get("teams", {}) or {}
    for side in ("away", "home"):
        team_box = boxscore.get(side, {})
        for p in iter_team_pitchers(team_box):
            if int(p["stats"].get("saves", 0) or 0) > 0:
                out.append(p)
    return out


def detect_blown_save_pitchers(feed: Dict) -> List[Dict]:
    out = []
    boxscore = feed.get("liveData", {}).get("boxscore", {}).get("teams", {}) or {}
    for side in ("away", "home"):
        team_box = boxscore.get(side, {})
        for p in iter_team_pitchers(team_box):
            if int(p["stats"].get("blownSaves", 0) or 0) > 0:
                out.append(p)
    return out


def get_pitcher_team_side(feed: Dict, pitcher_id: int) -> Optional[Tuple[str, Dict]]:
    boxscore = feed.get("liveData", {}).get("boxscore", {}).get("teams", {}) or {}
    for side in ("away", "home"):
        team_box = boxscore.get(side, {})
        players = team_box.get("players", {}) or {}
        key = f"ID{pitcher_id}"
        if key in players:
            return side, team_box
    return None


def team_name_from_box(team_box: Dict) -> str:
    return team_box.get("team", {}).get("name", "Unknown Team")


def team_abbr_from_box(team_box: Dict) -> str:
    return team_box.get("team", {}).get("abbreviation", "UNK")


def build_save_embed(game_meta: Dict, feed: Dict, pitcher: Dict, closer_map: Dict[str, str]) -> Dict:
    pitcher_id = pitcher.get("id")
    side_and_box = get_pitcher_team_side(feed, pitcher_id)
    team_name = game_meta["winning_team_name"]
    team_abbr = game_meta["winning_team_abbr"]

    if side_and_box:
        _, team_box = side_and_box
        team_name = team_name_from_box(team_box)
        team_abbr = team_abbr_from_box(team_box)

    stats = pitcher.get("stats", {})
    ip = stats.get("inningsPitched", short_innings(stats.get("outs")))
    h = stats.get("hits", 0)
    er = stats.get("earnedRuns", 0)
    bb = stats.get("baseOnBalls", 0)
    k = stats.get("strikeOuts", 0)
    pitches = stats.get("numberOfPitches", "—")

    expected_closer = closer_map.get(team_abbr.upper())
    closer_note = ""
    if expected_closer and expected_closer.lower() != pitcher["name"].lower():
        closer_note = f"\n⚠️ Not the listed closer ({expected_closer})."

    title = "🚨 SAVE RECORDED"
    description = (
        f"**{team_name}**\n\n"
        f"**{pitcher['name']}** recorded the save.\n\n"
        f"IP: **{ip}**  |  H: **{h}**  |  ER: **{er}**  |  BB: **{bb}**  |  K: **{k}**\n"
        f"Pitches: **{pitches}**{closer_note}"
    )

    footer_text = (
        f"{game_meta['away_abbr']} {game_meta['away_score']} - "
        f"{game_meta['home_abbr']} {game_meta['home_score']}"
    )

    return {
        "title": title,
        "description": description,
        "footer": {"text": footer_text},
        "timestamp": now_utc_iso(),
    }


def build_blown_save_embed(game_meta: Dict, feed: Dict, pitcher: Dict) -> Dict:
    pitcher_id = pitcher.get("id")
    side_and_box = get_pitcher_team_side(feed, pitcher_id)
    team_name = "Unknown Team"

    if side_and_box:
        _, team_box = side_and_box
        team_name = team_name_from_box(team_box)

    stats = pitcher.get("stats", {})
    ip = stats.get("inningsPitched", short_innings(stats.get("outs")))
    h = stats.get("hits", 0)
    er = stats.get("earnedRuns", 0)
    bb = stats.get("baseOnBalls", 0)
    k = stats.get("strikeOuts", 0)
    pitches = stats.get("numberOfPitches", "—")

    title = "⚠️ BLOWN SAVE"
    description = (
        f"**{team_name}**\n\n"
        f"**{pitcher['name']}** was charged with a blown save.\n\n"
        f"IP: **{ip}**  |  H: **{h}**  |  ER: **{er}**  |  BB: **{bb}**  |  K: **{k}**\n"
        f"Pitches: **{pitches}**"
    )

    footer_text = (
        f"{game_meta['away_abbr']} {game_meta['away_score']} - "
        f"{game_meta['home_abbr']} {game_meta['home_score']}"
    )

    return {
        "title": title,
        "description": description,
        "footer": {"text": footer_text},
        "timestamp": now_utc_iso(),
    }


def game_update_stamp(game: Dict) -> str:
    # used to skip reprocessing unchanged finals
    return (
        game.get("gameDate", "")
        + "|"
        + str(game.get("status", {}).get("codedGameState", ""))
        + "|"
        + str(game.get("teams", {}).get("away", {}).get("score", ""))
        + "-"
        + str(game.get("teams", {}).get("home", {}).get("score", ""))
    )


def process_games_once() -> None:
    state = load_state()
    posted_keys: Set[str] = set(state.get("posted_keys", []))
    seen_updates: Dict[str, str] = state.get("seen_game_updates", {})
    closer_map = load_closer_map()

    total_posts = 0
    dates = get_recent_dates()

    for date_str in dates:
        print(f"[BOT] Checking date: {date_str}")
        games = get_schedule_games_for_date(date_str)
        print(f"[BOT] Games found: {len(games)}")

        for game in games:
            if not is_final_game(game):
                continue

            meta = extract_game_meta(game)
            game_pk = meta["gamePk"]
            if not game_pk:
                continue

            stamp = game_update_stamp(game)
            old_stamp = seen_updates.get(str(game_pk))
            if old_stamp == stamp:
                continue

            print(f"[BOT] Processing final gamePk={game_pk}")
            try:
                feed = get_live_feed(game_pk)
            except Exception as e:
                print(f"[BOT] Failed live feed for {game_pk}: {e}")
                continue

            save_pitchers = detect_save_pitchers(feed)
            blown_pitchers = detect_blown_save_pitchers(feed)

            # Post all saves
            for pitcher in save_pitchers:
                pkey = f"save|{game_pk}|{pitcher.get('id')}"
                if pkey in posted_keys:
                    continue

                embed = build_save_embed(meta, feed, pitcher, closer_map)
                ok = post_discord_embed(embed)
                if ok:
                    print(f"[BOT] Posted save: {pitcher.get('name')} in game {game_pk}")
                    posted_keys.add(pkey)
                    total_posts += 1
                    time.sleep(1)

            # Post blown saves too
            for pitcher in blown_pitchers:
                pkey = f"blown|{game_pk}|{pitcher.get('id')}"
                if pkey in posted_keys:
                    continue

                embed = build_blown_save_embed(meta, feed, pitcher)
                ok = post_discord_embed(embed)
                if ok:
                    print(f"[BOT] Posted blown save: {pitcher.get('name')} in game {game_pk}")
                    posted_keys.add(pkey)
                    total_posts += 1
                    time.sleep(1)

            seen_updates[str(game_pk)] = stamp

    state["posted_keys"] = list(posted_keys)
    state["seen_game_updates"] = seen_updates
    state["last_run_utc"] = now_utc_iso()
    save_state(state)
    print(f"[BOT] Run complete. Posted: {total_posts}")


def main_loop() -> None:
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL env var is required")

    print("[BOT] === CLOSER ALERT BOT STARTED ===")
    print(f"[BOT] Poll interval: {POLL_MINUTES} minutes")
    print(f"[BOT] State file: {STATE_FILE}")

    while True:
        started = time.time()
        try:
            process_games_once()
        except Exception as e:
            print(f"[BOT] Unhandled error: {e}")

        elapsed = time.time() - started
        sleep_seconds = max(30, POLL_MINUTES * 60 - int(elapsed))
        print(f"[BOT] Sleeping {sleep_seconds}s")
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    main_loop()
