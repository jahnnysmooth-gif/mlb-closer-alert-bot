import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
import requests

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
POLL_MINUTES = int(os.getenv("POLL_MINUTES", "10"))
STATE_DIR = os.getenv("STATE_DIR", "/var/data")

STATE_FILE = os.path.join(STATE_DIR, "closer_alert_state.json")

ET = ZoneInfo("America/New_York")

TEAM_COLORS = {
    "ARI": 0xA71930,
    "ATH": 0x003831,
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

TEAM_NAME_TO_ABBR = {
    "Boston Red Sox": "BOS",
    "New York Yankees": "NYY",
    "New York Mets": "NYM",
    "Los Angeles Dodgers": "LAD",
    "Los Angeles Angels": "LAA",
    "Chicago White Sox": "CWS",
    "Chicago Cubs": "CHC",
    "San Diego Padres": "SD",
    "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",
    "Texas Rangers": "TEX",
    "Houston Astros": "HOU",
    "Atlanta Braves": "ATL",
    "Philadelphia Phillies": "PHI",
    "Washington Nationals": "WSH",
    "Toronto Blue Jays": "TOR",
    "Tampa Bay Rays": "TB",
    "Minnesota Twins": "MIN",
    "Detroit Tigers": "DET",
    "Kansas City Royals": "KC",
    "Cleveland Guardians": "CLE",
    "Milwaukee Brewers": "MIL",
    "St. Louis Cardinals": "STL",
    "Pittsburgh Pirates": "PIT",
    "Colorado Rockies": "COL",
    "Arizona Diamondbacks": "ARI",
    "Miami Marlins": "MIA",
    "Cincinnati Reds": "CIN",
    "Baltimore Orioles": "BAL",
    "Athletics": "ATH"
}

intents = discord.Intents.default()
client = discord.Client(intents=intents)


def log(message: str):
    print(message, flush=True)


def now_utc():
    return datetime.now(timezone.utc)


def now_et():
    return datetime.now(ET)


def in_quiet_hours():
    hour = now_et().hour
    return 2 <= hour < 13


def ensure_state_dir():
    os.makedirs(STATE_DIR, exist_ok=True)


def load_state():
    ensure_state_dir()

    if not os.path.exists(STATE_FILE):
        return {"posted_events": [], "processed_final_games": {}}

    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_logo(team_abbr):

    key = team_abbr.upper()

    if key in ("ATH", "OAK"):
        file_key = "oak"

    elif key == "CWS":
        file_key = "chw"

    else:
        file_key = key.lower()

    return f"https://a.espncdn.com/i/teamlogos/mlb/500/{file_key}.png"


def get_games():

    today = now_et().date()
    yesterday = today - timedelta(days=1)

    games = []

    for d in [today, yesterday]:

        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}"

        r = requests.get(url, timeout=30)
        data = r.json()

        for block in data.get("dates", []):
            games.extend(block.get("games", []))

    return games


def build_save_embed(team, pitcher, stats, score, team_abbr):

    logo = get_logo(team_abbr)

    embed = discord.Embed(
        title="🚨 SAVE RECORDED",
        description=f"**Final Score**\n{score}",
        color=TEAM_COLORS.get(team_abbr, 0x2ECC71),
        timestamp=now_utc()
    )

    embed.set_author(name="The Bullpen Coach")
    embed.set_thumbnail(url=logo)

    embed.add_field(name="Team", value=team, inline=False)
    embed.add_field(name="Pitcher", value=pitcher, inline=False)
    embed.add_field(name="Pitching Line", value=stats, inline=False)

    return embed


def build_blown_embed(team, pitcher, stats, score, team_abbr):

    logo = get_logo(team_abbr)

    embed = discord.Embed(
        title="⚠️ BLOWN SAVE",
        description=f"**Final Score**\n{score}",
        color=0xE67E22,
        timestamp=now_utc()
    )

    embed.set_author(name="The Bullpen Coach")
    embed.set_thumbnail(url=logo)

    embed.add_field(name="Team", value=team, inline=False)
    embed.add_field(name="Pitcher", value=pitcher, inline=False)
    embed.add_field(name="Pitching Line", value=stats, inline=False)

    return embed


async def get_channel():

    channel = client.get_channel(DISCORD_CHANNEL_ID)

    if channel:
        return channel

    return await client.fetch_channel(DISCORD_CHANNEL_ID)


async def process_games():

    state = load_state()

    posted_events = set(state["posted_events"])
    processed = state["processed_final_games"]

    channel = await get_channel()

    games = get_games()

    for game in games:

        if game["status"]["detailedState"] != "Final":
            continue

        game_pk = str(game["gamePk"])

        if game_pk in processed:
            continue

        log(f"[BOT] Processing game {game_pk}")

        url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

        data = requests.get(url).json()

        box = data["liveData"]["boxscore"]["teams"]

        away_abbr = game["teams"]["away"]["team"].get("abbreviation")
        home_abbr = game["teams"]["home"]["team"].get("abbreviation")

        away_team = box["away"]["team"]["name"]
        home_team = box["home"]["team"]["name"]

        if not away_abbr:
            away_abbr = TEAM_NAME_TO_ABBR.get(away_team, "UNK")

        if not home_abbr:
            home_abbr = TEAM_NAME_TO_ABBR.get(home_team, "UNK")

        away_runs = box["away"]["teamStats"]["batting"]["runs"]
        home_runs = box["home"]["teamStats"]["batting"]["runs"]

        score = f"{away_abbr} {away_runs} - {home_abbr} {home_runs}"

        for side in ["away", "home"]:

            team_box = box[side]

            team = team_box["team"]["name"]
            team_abbr = away_abbr if side == "away" else home_abbr

            for p in team_box["players"].values():

                stats = p.get("stats", {}).get("pitching")

                if not stats:
                    continue

                pitcher = p["person"]["fullName"]

                ip = stats.get("inningsPitched", "0.0")
                h = stats.get("hits", 0)
                er = stats.get("earnedRuns", 0)
                bb = stats.get("baseOnBalls", 0)
                k = stats.get("strikeOuts", 0)

                line = f"IP: {ip} | H: {h} | ER: {er} | BB: {bb} | K: {k}"

                if stats.get("saves", 0) > 0:

                    embed = build_save_embed(team, pitcher, line, score, team_abbr)

                    await channel.send(embed=embed)

                    log(f"[BOT] SAVE: {pitcher} | {team}")

                if stats.get("blownSaves", 0) > 0:

                    embed = build_blown_embed(team, pitcher, line, score, team_abbr)

                    await channel.send(embed=embed)

                    log(f"[BOT] BLOWN SAVE: {pitcher} | {team}")

        processed[game_pk] = True

    state["posted_events"] = list(posted_events)
    state["processed_final_games"] = processed

    save_state(state)


async def polling_loop():

    await client.wait_until_ready()

    log("[BOT] === CLOSER ALERT BOT STARTED ===")

    while not client.is_closed():

        try:

            if not in_quiet_hours():

                await process_games()

        except Exception as e:

            log(f"[BOT] ERROR: {e}")

        await asyncio.sleep(POLL_MINUTES * 60)


@client.event
async def on_ready():

    log(f"[BOT] Logged in as {client.user}")

    if not hasattr(client, "loop_task"):

        client.loop_task = asyncio.create_task(polling_loop())


if __name__ == "__main__":

    client.run(DISCORD_TOKEN)
