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
STATE_FILE = os.path.join(STATE_DIR, "closer_alert_state_test_espn.json")

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

intents = discord.Intents.default()
client = discord.Client(intents=intents)


def log(message: str) -> None:
    print(message, flush=True)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_et() -> datetime:
    return datetime.now(ET)


def in_quiet_hours() -> bool:
    hour = now_et().hour
    return 2 <= hour < 13


def ensure_state_dir() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)


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


def espn_scoreboard_url(date_obj) -> str:
    # ESPN scoreboard accepts dates as YYYYMMDD
    return (
        "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
        f"?dates={date_obj.strftime('%Y%m%d')}&limit=1000"
    )


def espn_summary_url(event_id: str) -> str:
    return (
        "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary"
        f"?event={event_id}"
    )


def get_games() -> list:
    today_et = now_et().date()
    yesterday_et = today_et - timedelta(days=1)

    events = []

    for d in [today_et, yesterday_et]:
        r = requests.get(espn_scoreboard_url(d), timeout=30)
        r.raise_for_status()
        data = r.json()
        events.extend(data.get("events", []))

    return events


def build_final_stamp(event: dict) -> str:
    competitions = event.get("competitions", [])
    if not competitions:
        return "no_competition"

    comp = competitions[0]
    status = comp.get("status", {}).get("type", {}).get("description", "")
    game_date = event.get("date", "")

    home_score = ""
    away_score = ""

    for competitor in comp.get("competitors", []):
        if competitor.get("homeAway") == "home":
            home_score = competitor.get("score", "")
        elif competitor.get("homeAway") == "away":
            away_score = competitor.get("score", "")

    return f"{status}|{away_score}|{home_score}|{game_date}"


def extract_competitor_info(event: dict) -> tuple[dict, dict]:
    comp = event.get("competitions", [{}])[0]
    home = {}
    away = {}

    for competitor in comp.get("competitors", []):
        if competitor.get("homeAway") == "home":
            home = competitor
        elif competitor.get("homeAway") == "away":
            away = competitor

    return away, home


def make_score_line(away_info: dict, home_info: dict) -> str:
    away_abbr = away_info.get("team", {}).get("abbreviation", "AWAY")
    home_abbr = home_info.get("team", {}).get("abbreviation", "HOME")
    away_score = away_info.get("score", "0")
    home_score = home_info.get("score", "0")
    return f"{away_abbr} {away_score} - {home_abbr} {home_score}"


def build_pitching_line(athlete: dict) -> str:
    stats = athlete.get("stats", [])
    if isinstance(stats, list):
        joined = " | ".join(str(x) for x in stats if str(x).strip())
        return joined or "No pitching line"
    return str(stats) if stats else "No pitching line"


def extract_save_pitcher(summary: dict, team_name: str) -> tuple[str | None, str]:
    boxscore = summary.get("boxscore", {})
    players = boxscore.get("players", [])

    for team_block in players:
        if team_block.get("team", {}).get("displayName") != team_name:
            continue

        for stat_group in team_block.get("statistics", []):
            if stat_group.get("name") != "pitching":
                continue

            for athlete in stat_group.get("athletes", []):
                display = athlete.get("displayValue", "")
                if "(S" in display or " S," in display or display.endswith(" S"):
                    return athlete.get("athlete", {}).get("displayName"), build_pitching_line(athlete)

    return None, ""


def extract_blown_save_pitchers(summary: dict, team_name: str) -> list[tuple[str, str]]:
    found = []
    boxscore = summary.get("boxscore", {})
    players = boxscore.get("players", [])

    for team_block in players:
        if team_block.get("team", {}).get("displayName") != team_name:
            continue

        for stat_group in team_block.get("statistics", []):
            if stat_group.get("name") != "pitching":
                continue

            for athlete in stat_group.get("athletes", []):
                display = athlete.get("displayValue", "")
                stats = athlete.get("stats", [])
                text = " ".join(str(x) for x in stats) + " " + display

                if "BS" in text or "(BS" in display:
                    found.append(
                        (
                            athlete.get("athlete", {}).get("displayName", "Unknown Pitcher"),
                            build_pitching_line(athlete),
                        )
                    )

    return found


def build_save_embed(team: str, pitcher: str, stats: str, score: str, team_abbr: str) -> discord.Embed:
    color = TEAM_COLORS.get(team_abbr, 0x2ECC71)
    logo = TEAM_LOGOS.get(team_abbr)

    embed = discord.Embed(
        title="🚨 SAVE RECORDED",
        description=f"**Final Score**\n{score}",
        color=color,
        timestamp=now_utc(),
    )
    embed.set_author(name="The Bullpen Coach")
    if logo:
        embed.set_thumbnail(url=logo)
    embed.add_field(name="Team", value=team, inline=False)
    embed.add_field(name="Pitcher", value=pitcher, inline=False)
    embed.add_field(name="Pitching Line", value=stats, inline=False)
    return embed


def build_blown_embed(team: str, pitcher: str, stats: str, score: str, team_abbr: str) -> discord.Embed:
    color = TEAM_COLORS.get(team_abbr, 0xE67E22)
    logo = TEAM_LOGOS.get(team_abbr)

    embed = discord.Embed(
        title="⚠️ BLOWN SAVE",
        description=f"**Final Score**\n{score}",
        color=color,
        timestamp=now_utc(),
    )
    embed.set_author(name="The Bullpen Coach")
    if logo:
        embed.set_thumbnail(url=logo)
    embed.add_field(name="Team", value=team, inline=False)
    embed.add_field(name="Pitcher", value=pitcher, inline=False)
    embed.add_field(name="Pitching Line", value=stats, inline=False)
    return embed


async def send_embed(channel: discord.TextChannel, embed: discord.Embed) -> None:
    await channel.send(embed=embed)


async def process_games() -> None:
    state = load_state()
    posted_events = set(state.get("posted_events", []))
    processed_final_games = state.get("processed_final_games", {})

    channel = client.get_channel(DISCORD_CHANNEL_ID)
    if channel is None:
        log(f"[BOT] ERROR: Could not find channel {DISCORD_CHANNEL_ID}")
        return

    games = get_games()
    total_final_games_seen = 0
    total_new_final_games = 0
    total_saves_found = 0
    total_blown_found = 0
    total_posted = 0

    log(f"[BOT] Games found: {len(games)}")

    for event in games:
        competitions = event.get("competitions", [])
        if not competitions:
            continue

        comp = competitions[0]
        status = comp.get("status", {}).get("type", {}).get("description", "")
        if status != "Final":
            continue

        total_final_games_seen += 1

        event_id = event.get("id")
        if not event_id:
            continue

        final_stamp = build_final_stamp(event)

        if processed_final_games.get(event_id) == final_stamp:
            log(f"[BOT] Skipping already processed final game: {event_id}")
            continue

        total_new_final_games += 1
        log(f"[BOT] Processing new final game: {event_id}")

        r = requests.get(espn_summary_url(event_id), timeout=30)
        r.raise_for_status()
        summary = r.json()

        away_info, home_info = extract_competitor_info(event)
        score = make_score_line(away_info, home_info)

        game_saves = 0
        game_blown = 0
        game_posted = 0
        blown_posted_teams = set()

        for team_info in [away_info, home_info]:
            team_name = team_info.get("team", {}).get("displayName", "Unknown Team")
            team_abbr = team_info.get("team", {}).get("abbreviation", "")

            save_pitcher, save_line = extract_save_pitcher(summary, team_name)
            if save_pitcher:
                total_saves_found += 1
                game_saves += 1
                event_key = f"save_{event_id}_{team_name}_{save_pitcher}"

                if event_key in posted_events:
                    log(f"[BOT] Skipping duplicate save: {save_pitcher} | {team_name}")
                else:
                    embed = build_save_embed(
                        team=team_name,
                        pitcher=save_pitcher,
                        stats=save_line or "No pitching line",
                        score=score,
                        team_abbr=team_abbr,
                    )
                    try:
                        await send_embed(channel, embed)
                        posted_events.add(event_key)
                        total_posted += 1
                        game_posted += 1
                        log(f"[BOT] SAVE: {save_pitcher} | {team_name}")
                        await asyncio.sleep(1.5)
                    except Exception as e:
                        log(f"[BOT] Discord send error on save: {e}")

            blown_pitchers = extract_blown_save_pitchers(summary, team_name)
            for blown_pitcher, blown_line in blown_pitchers:
                total_blown_found += 1
                game_blown += 1

                if team_name in blown_posted_teams:
                    log(f"[BOT] Skipping extra blown save for team in same game: {team_name}")
                    continue

                event_key = f"blown_team_{event_id}_{team_name}"

                if event_key in posted_events:
                    log(f"[BOT] Skipping duplicate blown save team alert: {team_name}")
                else:
                    embed = build_blown_embed(
                        team=team_name,
                        pitcher=blown_pitcher,
                        stats=blown_line or "No pitching line",
                        score=score,
                        team_abbr=team_abbr,
                    )
                    try:
                        await send_embed(channel, embed)
                        posted_events.add(event_key)
                        blown_posted_teams.add(team_name)
                        total_posted += 1
                        game_posted += 1
                        log(f"[BOT] BLOWN SAVE: {blown_pitcher} | {team_name}")
                        await asyncio.sleep(1.5)
                    except Exception as e:
                        log(f"[BOT] Discord send error on blown save: {e}")

        processed_final_games[event_id] = final_stamp

        log(
            f"[BOT] Game {event_id} complete | "
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


async def polling_loop() -> None:
    await client.wait_until_ready()

    log("[BOT] === CLOSER ALERT BOT STARTED ===")
    log(f"[BOT] Poll interval: {POLL_MINUTES} minutes")
    log(f"[BOT] State file: {STATE_FILE}")

    while not client.is_closed():
        current_et = now_et().strftime("%Y-%m-%d %I:%M:%S %p %Z")
        log(f"[BOT] Loop start | ET time: {current_et}")

        try:
            if in_quiet_hours():
                log("[BOT] Quiet hours active (2:00 AM ET - 1:00 PM ET). Skipping this loop.")
            else:
                await process_games()
        except Exception as e:
            log(f"[BOT] ERROR: {e}")

        log(f"[BOT] Sleeping {POLL_MINUTES} minutes")
        await asyncio.sleep(POLL_MINUTES * 60)


@client.event
async def on_ready():
    log(f"[BOT] Logged in as {client.user}")
    if not hasattr(client, "polling_task"):
        client.polling_task = asyncio.create_task(polling_loop())


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set")
    if not DISCORD_CHANNEL_ID:
        raise RuntimeError("DISCORD_CHANNEL_ID is not set")

    client.run(DISCORD_TOKEN)
