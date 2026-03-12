import requests
import os
import time
from datetime import datetime, timedelta

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

POLL_MINUTES = 10

posted_events = set()


def now_iso():
    return datetime.utcnow().isoformat()


def post_discord(embed):
    payload = {"embeds": [embed]}

    r = requests.post(DISCORD_WEBHOOK_URL, json=payload)

    if r.status_code not in [200, 204]:
        print("[BOT] Discord error:", r.text)


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
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)

    games = []

    for d in [today, yesterday]:
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}"

        r = requests.get(url)
        data = r.json()

        if "dates" not in data:
            continue

        for g in data["dates"][0]["games"]:
            games.append(g)

    return games


def process_games():

    games = get_games()

    print(f"[BOT] Games found: {len(games)}")

    for game in games:

        status = game["status"]["detailedState"]

        if status != "Final":
            continue

        game_pk = game["gamePk"]

        url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

        r = requests.get(url)
        data = r.json()

        box = data["liveData"]["boxscore"]["teams"]

        for side in ["home", "away"]:

            team = box[side]["team"]["name"]

            players = box[side]["players"]

            for p in players.values():

                if "pitching" not in p["stats"]:
                    continue

                stats = p["stats"]["pitching"]

                pitcher = p["person"]["fullName"]

                ip = stats.get("inningsPitched", "0")
                h = stats.get("hits", 0)
                er = stats.get("earnedRuns", 0)
                bb = stats.get("baseOnBalls", 0)
                k = stats.get("strikeOuts", 0)

                stat_line = f"IP: {ip} | H: {h} | ER: {er} | BB: {bb} | K: {k}"

                score = f"{game['teams']['away']['team']['abbreviation']} {game['teams']['away']['score']} - {game['teams']['home']['team']['abbreviation']} {game['teams']['home']['score']}"

                if stats.get("saves", 0) > 0:

                    key = f"save_{game_pk}_{pitcher}"

                    if key in posted_events:
                        continue

                    embed = build_save_embed(team, pitcher, stat_line, score)

                    post_discord(embed)

                    posted_events.add(key)

                    print(f"[BOT] SAVE: {pitcher} | {team}")

                if stats.get("blownSaves", 0) > 0:

                    key = f"blown_{game_pk}_{pitcher}"

                    if key in posted_events:
                        continue

                    embed = build_blown_embed(team, pitcher, stat_line, score)

                    post_discord(embed)

                    posted_events.add(key)

                    print(f"[BOT] BLOWN SAVE: {pitcher} | {team}")


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
