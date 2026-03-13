import asyncio
import json
import os
import time
import io
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
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

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
POLL_MINUTES = int(os.getenv("POLL_MINUTES", "10"))

STATE_DIR = os.getenv("STATE_DIR", "/var/data")
STATE_FILE = os.path.join(STATE_DIR, "closer_alert_state_test.json")

ET = ZoneInfo("America/New_York")

intents = discord.Intents.default()
client = discord.Client(intents=intents)


def log(msg):
    print(msg, flush=True)


def now_utc():
    return datetime.now(timezone.utc)


def now_et():
    return datetime.now(ET)


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
        json.dump(state, f)


def get_games():
    today = now_et().date()
    yesterday = today - timedelta(days=1)

    games = []

    for d in [today, yesterday]:
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d.isoformat()}"
        r = requests.get(url)
        data = r.json()

        if not data.get("dates"):
            continue

        games += data["dates"][0]["games"]

    return games


def build_save_embed(team, pitcher, stats, score, team_abbr):

    color = TEAM_COLORS.get(team_abbr, 0x2ECC71)

    embed = discord.Embed(
        title="🚨 SAVE RECORDED",
        description=f"**Final Score**\n{score}",
        color=color,
        timestamp=now_utc(),
    )

    embed.set_author(name="The Bullpen Coach")

    embed.add_field(name="Team", value=team, inline=False)
    embed.add_field(name="Pitcher", value=pitcher, inline=False)
    embed.add_field(name="Pitching Line", value=stats, inline=False)

    return embed


def build_blown_embed(team, pitcher, stats, score, team_abbr):

    color = TEAM_COLORS.get(team_abbr, 0xE67E22)

    embed = discord.Embed(
        title="⚠️ BLOWN SAVE",
        description=f"**Final Score**\n{score}",
        color=color,
        timestamp=now_utc(),
    )

    embed.set_author(name="The Bullpen Coach")

    embed.add_field(name="Team", value=team, inline=False)
    embed.add_field(name="Pitcher", value=pitcher, inline=False)
    embed.add_field(name="Pitching Line", value=stats, inline=False)

    return embed


async def send_embed(channel, embed, team_abbr):

    logo_url = TEAM_LOGOS.get(team_abbr)

    if not logo_url:
        await channel.send(embed=embed)
        return

    r = requests.get(logo_url)
    file = discord.File(io.BytesIO(r.content), filename="logo.png")

    embed.set_thumbnail(url="attachment://logo.png")

    await channel.send(embed=embed, file=file)


async def process_games():

    state = load_state()

    posted = set(state["posted_events"])
    processed = state["processed_final_games"]

    channel = client.get_channel(DISCORD_CHANNEL_ID)

    games = get_games()

    for game in games:

        if game["status"]["detailedState"] != "Final":
            continue

        game_pk = str(game["gamePk"])

        if game_pk in processed:
            continue

        url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
        data = requests.get(url).json()

        box = data["liveData"]["boxscore"]["teams"]

        away = box["away"]
        home = box["home"]

        away_abbr = away["team"].get("abbreviation", "AWAY")
home_abbr = home["team"].get("abbreviation", "HOME")

        score = f"{away_abbr} {away['teamStats']['batting']['runs']} - {home_abbr} {home['teamStats']['batting']['runs']}"

        for side in ["away", "home"]:

            team_box = box[side]

            team = team_box["team"]["name"]
            team_abbr = team_box["team"].get("abbreviation", "")

            players = team_box["players"]

            for p in players.values():

                pitching = p.get("stats", {}).get("pitching")

                if not pitching:
                    continue

                pitcher = p["person"]["fullName"]

                ip = pitching.get("inningsPitched", "0.0")
                h = pitching.get("hits", 0)
                er = pitching.get("earnedRuns", 0)
                bb = pitching.get("baseOnBalls", 0)
                k = pitching.get("strikeOuts", 0)

                line = f"IP: {ip} | H: {h} | ER: {er} | BB: {bb} | K: {k}"

                if pitching.get("saves", 0) > 0:

                    key = f"save_{game_pk}_{pitcher}"

                    if key not in posted:

                        embed = build_save_embed(team, pitcher, line, score, team_abbr)

                        await send_embed(channel, embed, team_abbr)

                        posted.add(key)

                        log(f"SAVE: {pitcher} | {team}")

                if pitching.get("blownSaves", 0) > 0:

                    key = f"blown_{game_pk}_{team}"

                    if key not in posted:

                        embed = build_blown_embed(team, pitcher, line, score, team_abbr)

                        await send_embed(channel, embed, team_abbr)

                        posted.add(key)

                        log(f"BLOWN SAVE: {pitcher} | {team}")

        processed[game_pk] = True

    state["posted_events"] = list(posted)
    state["processed_final_games"] = processed

    save_state(state)


async def loop():

    await client.wait_until_ready()

    log("Bullpen bot started")

    while True:

        try:
            await process_games()
        except Exception as e:
            log(e)

        await asyncio.sleep(POLL_MINUTES * 60)


@client.event
async def on_ready():
    log(f"Logged in as {client.user}")
    client.loop.create_task(loop())


client.run(DISCORD_TOKEN)
