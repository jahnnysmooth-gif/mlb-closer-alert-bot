import json
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
POLL_MINUTES = 10

STATE_DIR = os.getenv("STATE_DIR", "/var/data")
STATE_FILE = os.path.join(STATE_DIR, "closer_alert_state.json")

ET = ZoneInfo("America/New_York")


def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()


def now_et():
    return datetime.now(ET)


def in_quiet_hours() -> bool:
    current_et = now_et()
    hour = current_et.hour
    return 2 <= hour < 13  # 2:00 AM ET through 12:59 PM ET


def ensure_state_dir():
    os.makedirs(STATE_DIR, exist_ok=True)


def load_state():
    ensure_state_dir()
    if not os.path.exists(STATE_FILE):
        return {"posted_events": []}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"posted_events": []}


def save_state(state):
    ensure_state_dir()
    posted = state.get("posted_events", [])
    if len(posted) > 5000:
        state["posted_events"] = posted[-3000:]

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def post_discord(embed):
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not set")

    payload = {"embeds": [embed]}
    r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=30)

    if r.status_code not in [200, 204]:
        print(f"[BOT] Discord error: {r.status_code} {r.text[:300]}")
        return False

    print(f"[BOT] Posted to Discord: {embed.get('title', 'No title')}")
    return True


def build_save_embed(team, pitcher, stats, score):
    return {
        "author": {"name": "The Bullpen Coach"},
        "title": "🚨 SAVE RECORDED",
        "color": 0x2ECC71,
        "fields": [
            {"name": "Team", "value": team, "inline": False},
            {"name": "Pitcher", "value": pitcher, "inline": False},
            {"name": "Line", "value": stats, "inline": False},
        ],
        "footer": {"text": score},
        "timestamp": now_utc_iso(),
    }


def build_blown_embed(team, pitcher, stats, score):
    return {
        "author": {"name": "The Bullpen Coach"},
        "title": "⚠️ BLOWN SAVE",
        "color": 0xE67E22,
        "fields": [
            {"name": "Team", "value": team, "inline": False},
            {"name": "Pitcher", "value": pitcher, "inline": False},
            {"name": "Line", "value": stats, "inline": False},
        ],
        "footer": {"text": score},
        "timestamp": now_utc_iso(),
    }


def get_games():
    today_et = now_et().date()
    yesterday_et = today_et - timedelta(days=1)

    games = []

    for d in [today_et, yesterday_et]:
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d.isoformat()}"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()

        if "dates" not in data or not data["dates"]:
            continue

        for g in data["dates"][0]["games"]:
            games.append(g)

    return games


def process_games():
    state = load_state()
    posted_events = set(state.get("posted_events", []))

    games = get_games()
    total_final_games = 0
    total_saves = 0
    total_blown = 0
    total_posted = 0

    print(f"[BOT] Games found: {len(games)}")

    for game in games:
        status = game.get("status", {}).get("detailedState", "")
        if status != "Final":
            continue

        total_final_games += 1
        game_pk = game.get("gamePk")
        if not game_pk:
            continue

        print(f"[BOT] Checking final game: {game_pk}")

        url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()

        box = data.get("liveData", {}).get("boxscore", {}).get("teams", {})
        if not box:
            print(f"[BOT] No boxscore found for game {game_pk}")
            continue

        away_team_box = box.get("away", {})
        home_team_box = box.get("home", {})

        away_abbr = away_team_box.get("team", {}).get("abbreviation", "AWAY")
        home_abbr = home_team_box.get("team", {}).get("abbreviation", "HOME")
        away_score = away_team_box.get("teamStats", {}).get("batting", {}).get("runs", 0)
        home_score = home_team_box.get("teamStats", {}).get("batting", {}).get("runs", 0)
        score = f"{away_abbr} {away_score} - {home_abbr} {home_score}"

        game_saves = 0
        game_blown = 0

        for side in ["home", "away"]:
            team_box = box.get(side, {})
            team = team_box.get("team", {}).get("name", "Unknown Team")
            players = team_box.get("players", {})

            for p in players.values():
                pitching_stats = p.get("stats", {}).get("pitching")
                if not pitching_stats:
                    continue

                pitcher = p.get("person", {}).get("fullName", "Unknown Pitcher")

                ip = pitching_stats.get("inningsPitched", "0.0")
                h = pitching_stats.get("hits", 0)
                er = pitching_stats.get("earnedRuns", 0)
                bb = pitching_stats.get("baseOnBalls", 0)
                k = pitching_stats.get("strikeOuts", 0)

                stat_line = f"IP: {ip} | H: {h} | ER: {er} | BB: {bb} | K: {k}"

                if pitching_stats.get("saves", 0) > 0:
                    total_saves += 1
                    game_saves += 1
                    key = f"save_{game_pk}_{pitcher}"

                    if key not in posted_events:
                        embed = build_save_embed(team, pitcher, stat_line, score)
                        if post_discord(embed):
                            posted_events.add(key)
                            total_posted += 1
                            print(f"[BOT] SAVE: {pitcher} | {team}")
                    else:
                        print(f"[BOT] Skipping duplicate save: {pitcher} | {team}")

                if pitching_stats.get("blownSaves", 0) > 0:
                    total_blown += 1
                    game_blown += 1
                    key = f"blown_{game_pk}_{pitcher}"

                    if key not in posted_events:
                        embed = build_blown_embed(team, pitcher, stat_line, score)
                        if post_discord(embed):
                            posted_events.add(key)
                            total_posted += 1
                            print(f"[BOT] BLOWN SAVE: {pitcher} | {team}")
                    else:
                        print(f"[BOT] Skipping duplicate blown save: {pitcher} | {team}")

        print(
            f"[BOT] Game {game_pk} complete | "
            f"Saves found: {game_saves} | Blown saves found: {game_blown}"
        )

    state["posted_events"] = list(posted_events)
    save_state(state)

    print(
        f"[BOT] Loop summary | Final games: {total_final_games} | "
        f"Total saves found: {total_saves} | Total blown saves found: {total_blown} | "
        f"Posted this loop: {total_posted}"
    )


def main():
    print("[BOT] === CLOSER ALERT BOT STARTED ===")
    print(f"[BOT] Poll interval: {POLL_MINUTES} minutes")
    print(f"[BOT] State file: {STATE_FILE}")

    while True:
        current_et = now_et().strftime("%Y-%m-%d %I:%M:%S %p %Z")
        print(f"[BOT] Loop start | ET time: {current_et}")

        try:
            if in_quiet_hours():
                print("[BOT] Quiet hours active (2:00 AM ET - 1:00 PM ET). Skipping this loop.")
            else:
                process_games()
        except Exception as e:
            print(f"[BOT] ERROR: {e}")

        print(f"[BOT] Sleeping {POLL_MINUTES} minutes")
        time.sleep(POLL_MINUTES * 60)


if __name__ == "__main__":
    main()
