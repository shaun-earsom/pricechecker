"""
Discord Price Check Bot — Price Check (MnM)
Uses Google Sheets API v4 (read-only, API key auth) + discord.py slash commands.

Setup:
  1. pip install "discord.py>=2.3" aiohttp
  2. Fill in DISCORD_TOKEN and GOOGLE_API_KEY below (or use env vars).
  3. Run: python pricecheck_bot.py

Slash command usage in Discord:
  /pricecheck item:Leather Scraps
"""

import os
import aiohttp
import discord
from discord import app_commands

# ── Config ────────────────────────────────────────────────────────────────────
# You can hardcode these here or set them as environment variables.
DISCORD_TOKEN   = os.getenv("DISCORD_TOKEN",   "YOUR_DISCORD_BOT_TOKEN_HERE")
GOOGLE_API_KEY  = os.getenv("GOOGLE_API_KEY",  "YOUR_GOOGLE_API_KEY_HERE")

SPREADSHEET_ID  = "1OswS9O6njNTfkzGNsKlhqbSMa0uzUY6HNsd1cPlWfqY"
SHEET_RANGE     = "Sheet1!A2:C"   # Skip row 1 (headers), grab cols A-C
# ──────────────────────────────────────────────────────────────────────────────


async def fetch_sheet_data() -> list[list[str]]:
    """
    Pulls all rows from the sheet via Google Sheets API v4.
    Returns a list of rows; each row is a list of cell strings.
    Missing trailing cells (e.g. empty Column C) are simply absent.
    """
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}"
        f"/values/{SHEET_RANGE}?key={GOOGLE_API_KEY}"
    )
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
    return data.get("values", [])


def find_item(rows: list[list[str]], query: str) -> tuple[str, str] | None:
    """
    Case-insensitive search for `query` in Column A.
    Returns (price, note_or_empty) if found, or None if not found.
    """
    query_lower = query.strip().lower()
    for row in rows:
        if not row:
            continue
        item_name = row[0].strip()
        if item_name.lower() == query_lower:
            price = row[1].strip() if len(row) > 1 else "N/A"
            note  = row[2].strip() if len(row) > 2 else ""
            return price, note
    return None


# ── Bot setup ─────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
client  = discord.Client(intents=intents)
tree    = app_commands.CommandTree(client)


@tree.command(name="pricecheck", description="Look up the price of an item from the MnM price list.")
@app_commands.describe(item="The item name to look up (e.g. Leather Scraps)")
async def pricecheck(interaction: discord.Interaction, item: str):
    await interaction.response.defer()          # gives us time to call the API

    try:
        rows = await fetch_sheet_data()
    except Exception as e:
        await interaction.followup.send(f"❌ Couldn't reach the price sheet: `{e}`")
        return

    result = find_item(rows, item)

    if result is None:
        # Try a fuzzy partial match so small typos still help
        item_lower = item.strip().lower()
        close_matches = [
            (row[0], row[1] if len(row) > 1 else "N/A", row[2] if len(row) > 2 else "")
            for row in rows
            if row and item_lower in row[0].strip().lower()
        ]
        if close_matches:
            lines = "\n".join(
                f"• **{name}** — {price}" + (f"  *(Note: {note})*" if note else "")
                for name, price, note in close_matches
            )
            await interaction.followup.send(
                f"❓ No exact match for **{item}**. Did you mean one of these?\n{lines}"
            )
        else:
            await interaction.followup.send(
                f"❓ **{item}** was not found in the price list. "
                "Check your spelling or ask a guild officer to add it!"
            )
        return

    price, note = result
    msg = f"💰 **{item.strip()}** — {price} (per stack)"
    if note:
        msg += f"\n📝 Note: {note}"

    await interaction.followup.send(msg)


@client.event
async def on_ready():
    await tree.sync()   # registers slash commands globally (can take ~1 hr to propagate)
    print(f"✅ Logged in as {client.user} — slash commands synced.")


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if DISCORD_TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print("⚠️  Set your DISCORD_TOKEN before running!")
    elif GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY_HERE":
        print("⚠️  Set your GOOGLE_API_KEY before running!")
    else:
        client.run(DISCORD_TOKEN)

