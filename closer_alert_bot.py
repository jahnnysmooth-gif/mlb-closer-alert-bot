import requests
import os
import time
from datetime import datetime, timedelta, timezone

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
POLL_MINUTES = 10

posted_events = set()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def post_discord(embed):
    payload = {"embeds": [embed]}
    r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=30)

    if r.status_code not in [200, 204]:
        print("[BOT] Discord error:", r.status_code, r.text)
    else:
        print("[BOT] Posted to Discord:", embed.get("title", "No title"))


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
        "timestamp": now_iso(),
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
        "timestamp": now_iso(),
    }


def get_games():
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    games = []

    for d in [today, yesterday]:
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}"
        r = requests.get(url, timeout=30)
        data = r.json()

        if "dates" not in data or not data["dates"]:
            continue

        for g in data["dates"][0]["games"]:
            games.append(g)

    return games


def process_games():
    games = get_games()
    print(f"[BOT] Games found: {len(games)}")

    for game in games:
        status = game.get("status", {}).get("detailedState", "")
        if status != "Final":
            continue

        game_pk = game.get("gamePk")
        if not game_pk:
            continue

        print(f"[BOT] Checking final game: {game_pk}")

        url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
        r = requests.get(url, timeout=30)
        data = r.json()

        box = data.get("liveData", {}).get("boxscore", {}).get("teams", {})
        if not box:
            print(f"[BOT] No boxscore teams found for game {game_pk}")
            continue

        away_team_box = box.get("away", {})
        home_team_box = box.get("home", {})

        away_abbr = away_team_box.get("team", {}).get("abbreviation", "AWAY")
        home_abbr = home_team_box.get("team", {}).get("abbreviation", "HOME")
        away_score = away_team_box.get("teamStats", {}).get("batting", {}).get("runs", 0)
        home_score = home_team_box.get("teamStats", {}).get("batting", {}).get("runs", 0)
        score = f"{away_abbr} {away_score} - {home_abbr} {home_score}"

        saves_found = 0
        blown_found = 0

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
                    saves_found += 1
                    key = f"save_{game_pk}_{pitcher}"

                    if key not in posted_events:
                        embed = build_save_embed(team, pitcher, stat_line, score)
                        post_discord(embed)
                        posted_events.add(key)
                        print(f"[BOT] SAVE: {pitcher} | {team}")
                    else:
                        print(f"[BOT] Skipping duplicate save: {pitcher} | {team}")

                if pitching_stats.get("blownSaves", 0) > 0:
                    blown_found += 1
                    key = f"blown_{game_pk}_{pitcher}"

                    if key not in posted_events:
                        embed = build_blown_embed(team, pitcher, stat_line, score)
                        post_discord(embed)
                        posted_events.add(key)
                        print(f"[BOT] BLOWN SAVE: {pitcher} | {team}")
                    else:
                        print(f"[BOT] Skipping duplicate blown save: {pitcher} | {team}")

        print(f"[BOT] Game {game_pk} complete | Saves found: {saves_found} | Blown saves found: {blown_found}")


def main():
    print("[BOT] === CLOSER ALERT BOT STARTED ===")

    while True:
        try:
            process_games()
        except Exception as e:
            print("[BOT] ERROR:", e)

        print(f"[BOT] Sleeping {POLL_MINUTES} minutes")
        time.sleep(POLL_MINUTES * 60)


if __name__ == "__main__":
    main()
