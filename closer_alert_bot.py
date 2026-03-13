import os
import json
import time
import requests
import discord
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BOT_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

POLL_MINUTES = int(os.getenv("POLL_MINUTES", "10"))
STATE_DIR = os.getenv("STATE_DIR", "/var/data")
STATE_FILE = os.path.join(STATE_DIR, "closer_alert_state_test10.json")

ET = ZoneInfo("America/New_York")

TEAM_LOGOS = {
109:"https://a.espncdn.com/i/teamlogos/mlb/500/ari.png",
133:"https://a.espncdn.com/i/teamlogos/mlb/500/oak.png",
144:"https://a.espncdn.com/i/teamlogos/mlb/500/atl.png",
110:"https://a.espncdn.com/i/teamlogos/mlb/500/bal.png",
111:"https://a.espncdn.com/i/teamlogos/mlb/500/bos.png",
112:"https://a.espncdn.com/i/teamlogos/mlb/500/chc.png",
145:"https://a.espncdn.com/i/teamlogos/mlb/500/chw.png",
113:"https://a.espncdn.com/i/teamlogos/mlb/500/cin.png",
114:"https://a.espncdn.com/i/teamlogos/mlb/500/cle.png",
115:"https://a.espncdn.com/i/teamlogos/mlb/500/col.png",
116:"https://a.espncdn.com/i/teamlogos/mlb/500/det.png",
117:"https://a.espncdn.com/i/teamlogos/mlb/500/hou.png",
118:"https://a.espncdn.com/i/teamlogos/mlb/500/kc.png",
108:"https://a.espncdn.com/i/teamlogos/mlb/500/laa.png",
119:"https://a.espncdn.com/i/teamlogos/mlb/500/lad.png",
146:"https://a.espncdn.com/i/teamlogos/mlb/500/mia.png",
158:"https://a.espncdn.com/i/teamlogos/mlb/500/mil.png",
142:"https://a.espncdn.com/i/teamlogos/mlb/500/min.png",
121:"https://a.espncdn.com/i/teamlogos/mlb/500/nym.png",
147:"https://a.espncdn.com/i/teamlogos/mlb/500/nyy.png",
143:"https://a.espncdn.com/i/teamlogos/mlb/500/phi.png",
134:"https://a.espncdn.com/i/teamlogos/mlb/500/pit.png",
135:"https://a.espncdn.com/i/teamlogos/mlb/500/sd.png",
137:"https://a.espncdn.com/i/teamlogos/mlb/500/sf.png",
136:"https://a.espncdn.com/i/teamlogos/mlb/500/sea.png",
138:"https://a.espncdn.com/i/teamlogos/mlb/500/stl.png",
139:"https://a.espncdn.com/i/teamlogos/mlb/500/tb.png",
140:"https://a.espncdn.com/i/teamlogos/mlb/500/tex.png",
141:"https://a.espncdn.com/i/teamlogos/mlb/500/tor.png",
120:"https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png"
}

intents = discord.Intents.default()
client = discord.Client(intents=intents)

def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()

def now_et():
    return datetime.now(ET)

def ensure_state_dir():
    os.makedirs(STATE_DIR, exist_ok=True)

def load_state():
    ensure_state_dir()

    if not os.path.exists(STATE_FILE):
        return {"posted_events":[], "processed_final_games":{}}

    with open(STATE_FILE,"r") as f:
        return json.load(f)

def save_state(state):
    ensure_state_dir()
    with open(STATE_FILE,"w") as f:
        json.dump(state,f)

def build_save_embed(team, pitcher, stats, score, team_id):

    logo = TEAM_LOGOS.get(team_id)

    embed = discord.Embed(
        title="🚨 SAVE RECORDED",
        color=0x2ECC71,
        timestamp=datetime.utcnow()
    )

    embed.add_field(name="Team", value=team, inline=False)
    embed.add_field(name="Pitcher", value=pitcher, inline=False)
    embed.add_field(name="Line", value=stats, inline=False)

    embed.set_footer(text=score)

    if logo:
        embed.set_thumbnail(url=logo)

    return embed

def build_blown_embed(team, pitcher, stats, score, team_id):

    logo = TEAM_LOGOS.get(team_id)

    embed = discord.Embed(
        title="⚠️ BLOWN SAVE",
        color=0xE67E22,
        timestamp=datetime.utcnow()
    )

    embed.add_field(name="Team", value=team, inline=False)
    embed.add_field(name="Pitcher", value=pitcher, inline=False)
    embed.add_field(name="Line", value=stats, inline=False)

    embed.set_footer(text=score)

    if logo:
        embed.set_thumbnail(url=logo)

    return embed

def get_games():

    today = now_et().date()
    yesterday = today - timedelta(days=1)

    games = []

    for d in [today,yesterday]:

        url=f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}"

        r=requests.get(url)
        data=r.json()

        if not data.get("dates"):
            continue

        for g in data["dates"][0]["games"]:
            games.append(g)

    return games

async def process_games():

    state = load_state()
    posted = set(state["posted_events"])
    processed = state["processed_final_games"]

    channel = client.get_channel(CHANNEL_ID)

    games = get_games()

    print("[BOT] Games found:",len(games))

    for game in games:

        if game["status"]["detailedState"] != "Final":
            continue

        game_pk = str(game["gamePk"])

        if game_pk in processed:
            print("[BOT] Skipping already processed final game:",game_pk)
            continue

        print("[BOT] Processing new final game:",game_pk)

        url=f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
        data=requests.get(url).json()

        teams=data["liveData"]["boxscore"]["teams"]

        away=teams["away"]
        home=teams["home"]

        away_id = away["team"]["id"]
        home_id = home["team"]["id"]

        away_abbr = away["team"]["abbreviation"]
        home_abbr = home["team"]["abbreviation"]

        score = f"{away_abbr} {away['teamStats']['batting']['runs']} - {home_abbr} {home['teamStats']['batting']['runs']}"

        for side,team_id in [("away",away_id),("home",home_id)]:

            t=teams[side]
            team=t["team"]["name"]

            for p in t["players"].values():

                stats=p.get("stats",{}).get("pitching")

                if not stats:
                    continue

                pitcher=p["person"]["fullName"]
                pitcher_id=p["person"]["id"]

                ip=stats.get("inningsPitched","0")
                h=stats.get("hits",0)
                er=stats.get("earnedRuns",0)
                bb=stats.get("baseOnBalls",0)
                k=stats.get("strikeOuts",0)

                line=f"IP:{ip} H:{h} ER:{er} BB:{bb} K:{k}"

                if stats.get("saves",0)>0:

                    key=f"save_{game_pk}_{pitcher_id}"

                    if key not in posted:

                        embed=build_save_embed(team,pitcher,line,score,team_id)

                        await channel.send(embed=embed)

                        posted.add(key)

                        print("[BOT] SAVE:",pitcher,"|",team)

                if stats.get("blownSaves",0)>0:

                    key=f"blown_{game_pk}_{team}"

                    if key not in posted:

                        embed=build_blown_embed(team,pitcher,line,score,team_id)

                        await channel.send(embed=embed)

                        posted.add(key)

                        print("[BOT] BLOWN SAVE:",pitcher,"|",team)

        processed[game_pk]=True

    state["posted_events"]=list(posted)
    state["processed_final_games"]=processed

    save_state(state)

async def loop():

    await client.wait_until_ready()

    while True:

        print("[BOT] Loop start | ET time:",now_et())

        try:
            await process_games()
        except Exception as e:
            print("[BOT] ERROR:",e)

        print("[BOT] Sleeping",POLL_MINUTES,"minutes")

        await asyncio.sleep(POLL_MINUTES*60)

import asyncio

@client.event
async def on_ready():

    print("Logged in as",client.user)
    print("Bullpen bot started")

    client.loop.create_task(loop())

client.run(BOT_TOKEN)
