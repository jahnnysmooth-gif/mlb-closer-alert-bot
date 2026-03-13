import json
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

TEAM_LOGOS = {
    "ARI": "https://a.espncdn.com/i/teamlogos/mlb/500/ari.png",
    "ATH": "https://a.espncdn.com/i/teamlogos/mlb/500/oak.png",
    "ATL": "https://a.espncdn.com/i/teamlogos/mlb/500/atl.png",
    "BAL": "https://a.espncdn.com/i/teamlogos/mlb/500/bal.png",
    "BOS": "https://a.espncdn.com/i/teamlogos/mlb/500/bos.png",
    "CHC": "https://a.espncdn.com/i/teamlogos/mlb/500/chc.png",
    "CWS": "https://a.espncdn.com/i/teamlogos/mlb/500/chw.png",
    "CIN": "https://a.espncdn.com/i/teamlogos/mlb/500/cin.png",
    "CLE": "https://a.espncdn.com/i/teamlogos/mlb/500/cle.png",
    "COL": "https://a.espncdn.com/i/teamlogos/mlb/500/col.png",
    "DET": "https://a.espncdn.com/i/teamlogos/mlb/500/det.png",
    "HOU": "https://a.espncdn.com/i/teamlogos/mlb/500/hou.png",
    "KC": "https://a.espncdn.com/i/teamlogos/mlb/500/kc.png",
    "LAA": "https://a.espncdn.com/i/teamlogos/mlb/500/laa.png",
    "LAD": "https://a.espncdn.com/i/teamlogos/mlb/500/lad.png",
    "MIA": "https://a.espncdn.com/i/teamlogos/mlb/500/mia.png",
    "MIL": "https://a.espncdn.com/i/teamlogos/mlb/500/mil.png",
    "MIN": "https://a.espncdn.com/i/teamlogos/mlb/500/min.png",
    "NYM": "https://a.espncdn.com/i/teamlogos/mlb/500/nym.png",
    "NYY": "https://a.espncdn.com/i/teamlogos/mlb/500/nyy.png",
    "PHI": "https://a.espncdn.com/i/teamlogos/mlb/500/phi.png",
    "PIT": "https://a.espncdn.com/i/teamlogos/mlb/500/pit.png",
    "SD": "https://a.espncdn.com/i/teamlogos/mlb/500/sd.png",
    "SF": "https://a.espncdn.com/i/teamlogos/mlb/500/sf.png",
    "SEA": "https://a.espncdn.com/i/teamlogos/mlb/500/sea.png",
    "STL": "https://a.espncdn.com/i/teamlogos/mlb/500/stl.png",
    "TB": "https://a.espncdn.com/i/teamlogos/mlb/500/tb.png",
    "TEX": "https://a.espncdn.com/i/teamlogos/mlb/500/tex.png",
    "TOR": "https://a.espncdn.com/i/teamlogos/mlb/500/tor.png",
    "WSH": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
}

TEAM_COLORS = {
    "ARI": 0xA71930,
    "ATL": 0xCE1141,
    "BAL": 0xDF4601,
    "BOS": 0xBD3039,
    "CHC": 0x0E3386,
    "CWS": 0x27251F,
    "CIN": 0xC6011F,
    "CLE": 0xE31937,
    "COL": 0x33006F,
    "DET": 0x0C2340,
    "HOU": 0xEB6E1F,
    "KC": 0x004687,
    "LAA": 0xBA0021,
    "LAD": 0x005A9C,
    "MIA": 0x00A3E0,
    "MIL": 0x12284B,
    "MIN": 0x002B5C,
    "NYM": 0xFF5910,
    "NYY": 0x0C2340,
    "PHI": 0xE81828,
    "PIT": 0xFDB827,
    "SD": 0x2F241D,
    "SF": 0xFD5A1E,
    "SEA": 0x005C5C,
    "STL": 0xC41E3A,
    "TB": 0x092C5C,
    "TEX": 0x003278,
    "TOR": 0x134A8E,
    "WSH": 0xAB0003,
}

TEAM_ABBR_FIX = {
    "CWS": "CHW",  # White Sox
}

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
POLL_MINUTES = int(os.getenv("POLL_MINUTES", "10"))
STATE_DIR = os.getenv("STATE_DIR", "/var/data")
STATE_FILE = os.path.join(STATE_DIR, "closer_alert_state.json")

# Set in Render as JSON, example:
# {"NYY":"Devin Williams","NYM":"Edwin Diaz","BAL":"Felix Bautista"}
CLOSER_MAP_JSON = os.getenv("CLOSER_MAP_JSON", "")

ET = ZoneInfo("America/New_York")


def log(message: str) -> None:
    print(message, flush=True)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_et() -> datetime:
    return datetime.now(ET)


def in_quiet_hours() -> bool:
    hour = now_et().hour
    return 2 <= hour < 13


def ensure_state_dir() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)


def load_closer_map() -> dict:
    if not CLOSER_MAP_JSON.strip():
        return {}

    try:
        raw = json.loads(CLOSER_MAP_JSON)
        return {str(k).upper(): str(v) for k, v in raw.items()}
    except Exception as e:
        log(f"[BOT] Failed to parse CLOSER_MAP_JSON: {e}")
        return {}


def load_state() -> dict:
    ensure_state_dir()
    if not os.path.exists(STATE_FILE):
        return {
            "posted_events": [],
            "processed_final_games": {},
        }

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}

    state.setdefault("posted_events", [])
    state.setdefault("processed_final_games", {})
    return state


def save_state(state: dict) -> None:
    ensure_state_dir()

    posted_events = state.get("posted_events", [])
    if len(posted_events) > 5000:
        state["posted_events"] = posted_events[-3000:]

    processed_final_games = state.get("processed_final_games", {})
    if len(processed_final_games) > 500:
        items = list(processed_final_games.items())[-300:]
        state["processed_final_games"] = dict(items)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def post_discord(embed: dict, retries: int = 3) -> bool:
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not set")

    payload = {"embeds": [embed]}

    for attempt in range(1, retries + 1):
        try:
            r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=30)
        except Exception as e:
            log(f"[BOT] Discord request exception on attempt {attempt}: {e}")
            time.sleep(2 * attempt)
            continue

        if r.status_code in (200, 204):
            log(f"[BOT] Posted to Discord: {embed.get('title', 'No title')}")
            time.sleep(1.5)
            return True

        if r.status_code == 429:
            retry_after = 5
            try:
                retry_after = max(1, int(r.json().get("retry_after", 5)))
            except Exception:
                pass
            log(f"[BOT] Discord rate limit hit. Sleeping {retry_after}s")
            time.sleep(retry_after)
            continue

        if r.status_code >= 500:
            wait_time = 3 * attempt
            log(f"[BOT] Discord server error {r.status_code}. Retrying in {wait_time}s")
            time.sleep(wait_time)
            continue

        log(f"[BOT] Discord error: {r.status_code} {r.text[:300]}")
        return False

    return False

def build_save_embed(team, pitcher, stats, score, team_abbr):

    logo = TEAM_LOGOS.get(team_abbr)
    color = TEAM_COLORS.get(team_abbr, 0x2ECC71)

    embed = {
        "author": {"name": "The Bullpen Coach", "icon_url": logo},
        "title": "🚨 SAVE RECORDED",
        "description": f"**Final Score**\n{score}",
        "color": color,
        "fields": [
            {"name": "Team", "value": team, "inline": False},
            {"name": "Closer", "value": pitcher, "inline": False},
            {"name": "Pitching Line", "value": stats, "inline": False},
        ],
        "timestamp": now_utc_iso(),
    }

    if logo:
        embed["thumbnail"] = {"url": logo}

    return embed


def build_closer_alert_embed(team: str, pitcher: str, expected_closer: str, stats: str, score: str) -> dict:
    return {
        "author": {"name": "The Bullpen Coach"},
        "title": "🚨 CLOSER ALERT",
        "color": 0xE74C3C,
        "fields": [
            {"name": "Team", "value": team, "inline": False},
            {"name": "Save Recorded By", "value": pitcher, "inline": False},
            {"name": "Expected Closer", "value": expected_closer, "inline": False},
            {"name": "Line", "value": stats, "inline": False},
            {"name": "Note", "value": "Possible bullpen change.", "inline": False},
        ],
        "footer": {"text": score},
        "timestamp": now_utc_iso(),
    }


def build_blown_embed(team, pitcher, stats, score, team_abbr):

    logo = TEAM_LOGOS.get(team_abbr)
    color = TEAM_COLORS.get(team_abbr, 0xE67E22)

    embed = {
        "author": {"name": "The Bullpen Coach", "icon_url": logo},
        "title": "⚠️ BLOWN SAVE",
        "description": f"**Final Score**\n{score}",
        "color": color,
        "fields": [
            {"name": "Team", "value": team, "inline": False},
            {"name": "Pitcher", "value": pitcher, "inline": False},
            {"name": "Pitching Line", "value": stats, "inline": False},
        ],
        "timestamp": now_utc_iso(),
    }

    if logo:
        embed["thumbnail"] = {"url": logo}

    return embed


def get_games() -> list:
    today_et = now_et().date()
    yesterday_et = today_et - timedelta(days=1)

    games = []

    for d in [today_et, yesterday_et]:
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d.isoformat()}"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()

        if not data.get("dates"):
            continue

        for game in data["dates"][0].get("games", []):
            games.append(game)

    return games


def build_final_stamp(game: dict) -> str:
    status = game.get("status", {}).get("detailedState", "")
    away_score = game.get("teams", {}).get("away", {}).get("score", "")
    home_score = game.get("teams", {}).get("home", {}).get("score", "")
    game_date = game.get("gameDate", "")
    return f"{status}|{away_score}|{home_score}|{game_date}"


def process_games() -> None:
    state = load_state()
    posted_events = set(state.get("posted_events", []))
    processed_final_games = state.get("processed_final_games", {})
    closer_map = load_closer_map()

    games = get_games()
    total_final_games_seen = 0
    total_new_final_games = 0
    total_saves_found = 0
    total_blown_found = 0
    total_posted = 0

    log(f"[BOT] Games found: {len(games)}")

    for game in games:
        status = game.get("status", {}).get("detailedState", "")
        if status != "Final":
            continue

        total_final_games_seen += 1

        game_pk = game.get("gamePk")
        if not game_pk:
            continue

        game_pk_str = str(game_pk)
        final_stamp = build_final_stamp(game)

        if processed_final_games.get(game_pk_str) == final_stamp:
            log(f"[BOT] Skipping already processed final game: {game_pk}")
            continue

        total_new_final_games += 1
        log(f"[BOT] Processing new final game: {game_pk}")

        url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()

        box = data.get("liveData", {}).get("boxscore", {}).get("teams", {})
        if not box:
            log(f"[BOT] No boxscore found for game {game_pk}")
            processed_final_games[game_pk_str] = final_stamp
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
        game_posted = 0
        blown_posted_teams = set()

        for side in ["home", "away"]:
            team_box = box.get(side, {})
            team = team_box.get("team", {}).get("name", "Unknown Team")
            team_abbr = team_box.get("team", {}).get("abbreviation", "").upper()
team_abbr = TEAM_ABBR_FIX.get(team_abbr, team_abbr)
            expected_closer = closer_map.get(team_abbr, "")
            players = team_box.get("players", {})

            for p in players.values():
                pitching_stats = p.get("stats", {}).get("pitching")
                if not pitching_stats:
                    continue

                pitcher = p.get("person", {}).get("fullName", "Unknown Pitcher")
                pitcher_id = p.get("person", {}).get("id", pitcher)

                ip = pitching_stats.get("inningsPitched", "0.0")
                h = pitching_stats.get("hits", 0)
                er = pitching_stats.get("earnedRuns", 0)
                bb = pitching_stats.get("baseOnBalls", 0)
                k = pitching_stats.get("strikeOuts", 0)

                stat_line = f"IP: {ip} | H: {h} | ER: {er} | BB: {bb} | K: {k}"

                if pitching_stats.get("saves", 0) > 0:
                    total_saves_found += 1
                    game_saves += 1
                    event_key = f"save_{game_pk}_{pitcher_id}"

                    if event_key in posted_events:
                        log(f"[BOT] Skipping duplicate save: {pitcher} | {team}")
                    else:
                        is_expected_closer = (
                            expected_closer.strip().lower() == pitcher.strip().lower()
                            if expected_closer else True
                        )

                        if expected_closer and not is_expected_closer:
                            embed = build_closer_alert_embed(
                                team=team,
                                pitcher=pitcher,
                                expected_closer=expected_closer,
                                stats=stat_line,
                                score=score,
                            )
                            if post_discord(embed):
                                posted_events.add(event_key)
                                total_posted += 1
                                game_posted += 1
                                log(f"[BOT] CLOSER ALERT: {pitcher} | {team} | Expected: {expected_closer}")
                        else:
                            embed = build_save_embed(team, pitcher, stat_line, score, team_abbr)
                            if post_discord(embed):
                                posted_events.add(event_key)
                                total_posted += 1
                                game_posted += 1
                                log(f"[BOT] SAVE: {pitcher} | {team}")

                if pitching_stats.get("blownSaves", 0) > 0:
                    total_blown_found += 1
                    game_blown += 1

                    if team in blown_posted_teams:
                        log(f"[BOT] Skipping extra blown save for team in same game: {team}")
                        continue

                    event_key = f"blown_team_{game_pk}_{team}"

                    if event_key in posted_events:
                        log(f"[BOT] Skipping duplicate blown save team alert: {team}")
                    else:
                        embed = build_blown_embed(team, pitcher, stat_line, score, team_abbr)
                        if post_discord(embed):
                            posted_events.add(event_key)
                            blown_posted_teams.add(team)
                            total_posted += 1
                            game_posted += 1
                            log(f"[BOT] BLOWN SAVE: {pitcher} | {team}")

        processed_final_games[game_pk_str] = final_stamp

        log(
            f"[BOT] Game {game_pk} complete | "
            f"Saves found: {game_saves} | "
            f"Blown saves found: {game_blown} | "
            f"Posted: {game_posted}"
        )

    state["posted_events"] = list(posted_events)
    state["processed_final_games"] = processed_final_games
    save_state(state)

    log(
        f"[BOT] Loop summary | "
        f"Final games seen: {total_final_games_seen} | "
        f"New finals processed: {total_new_final_games} | "
        f"Saves found: {total_saves_found} | "
        f"Blown saves found: {total_blown_found} | "
        f"Posted this loop: {total_posted}"
    )


def main() -> None:
    log("[BOT] === CLOSER ALERT BOT STARTED ===")
    log(f"[BOT] Poll interval: {POLL_MINUTES} minutes")
    log(f"[BOT] State file: {STATE_FILE}")

    while True:
        current_et = now_et().strftime("%Y-%m-%d %I:%M:%S %p %Z")
        log(f"[BOT] Loop start | ET time: {current_et}")

        try:
            if in_quiet_hours():
                log("[BOT] Quiet hours active (2:00 AM ET - 1:00 PM ET). Skipping this loop.")
            else:
                process_games()
        except Exception as e:
            log(f"[BOT] ERROR: {e}")

        log(f"[BOT] Sleeping {POLL_MINUTES} minutes")
        time.sleep(POLL_MINUTES * 60)


if __name__ == "__main__":
    main()
