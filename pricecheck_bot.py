"""
Discord Price Check Bot — Price Check (MnM)
Uses Google Sheets API v4 + discord.py slash commands.

Read  → API key (no auth needed for public sheet)
Write → Google Service Account (JSON stored in GOOGLE_CREDENTIALS_JSON env var)

Setup:
  1. pip install "discord.py>=2.3" aiohttp google-auth
  2. Set environment variables:
       DISCORD_TOKEN              — your Discord bot token
       GOOGLE_API_KEY             — your Google API key (for reads)
       GOOGLE_CREDENTIALS_JSON    — full contents of your service account JSON (for writes)
  3. Run: python pricecheck_bot.py

Slash commands:
  /pricecheck item:Leather Scraps
  /pricecheckadd item:Cool Item price:15 silver note:Optional note here
"""

import os
import json
import aiohttp
import discord
from discord import app_commands
from google.oauth2 import service_account
from google.auth.transport.requests import Request

# ── Config ────────────────────────────────────────────────────────────────────
DISCORD_TOKEN            = os.getenv("DISCORD_TOKEN",           "YOUR_DISCORD_BOT_TOKEN_HERE")
GOOGLE_API_KEY           = os.getenv("GOOGLE_API_KEY",          "YOUR_GOOGLE_API_KEY_HERE")
GOOGLE_CREDENTIALS_JSON  = os.getenv("GOOGLE_CREDENTIALS_JSON", "")

SPREADSHEET_ID  = "1OswS9O6njNTfkzGNsKlhqbSMa0uzUY6HNsd1cPlWfqY"
SHEET_RANGE     = "Sheet1!A2:C"       # Skip row 1 (headers), grab cols A-C
SHEET_APPEND    = "Sheet1!A:C"        # Range used for appending new rows
ALLOWED_ROLES   = {"merchant", "officers", "gm"}  # Roles allowed to use /pricecheckadd (case-insensitive)
HOME_GUILD_ID   = int(os.getenv("HOME_GUILD_ID", "0"))  # Only this server can use /pricecheckadd
# ──────────────────────────────────────────────────────────────────────────────


def get_service_account_token() -> str:
    """
    Loads the service account credentials from the env var and returns
    a fresh OAuth2 access token for the Sheets API.
    """
    creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    creds.refresh(Request())
    return creds.token


async def fetch_sheet_data() -> list[list[str]]:
    """
    Pulls all rows from the sheet via Google Sheets API v4 (read, API key).
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


async def append_row_to_sheet(item: str, price: str, note: str) -> None:
    """
    Appends a new row to the sheet via Google Sheets API v4 (write, service account).
    """
    token = get_service_account_token()
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}"
        f"/values/{SHEET_APPEND}:append"
        f"?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"
    )
    row = [item.strip(), price.strip(), note.strip()]
    payload = {"values": [row]}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"}
        ) as resp:
            resp.raise_for_status()


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


def has_allowed_role(interaction: discord.Interaction) -> bool:
    """Returns True if the user is in the home guild AND has an allowed role."""
    if not interaction.guild:
        return False  # DMs not allowed
    if HOME_GUILD_ID and interaction.guild.id != HOME_GUILD_ID:
        return False  # Wrong server
    return any(
        role.name.lower() in ALLOWED_ROLES
        for role in interaction.user.roles
    )


# ── Bot setup ─────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
client  = discord.Client(intents=intents)
tree    = app_commands.CommandTree(client)


@tree.command(name="pricecheck", description="Look up the price of an item from the MnM price list.")
@app_commands.describe(item="The item name to look up (e.g. Leather Scraps)")
async def pricecheck(interaction: discord.Interaction, item: str):
    item = item.strip().title()   # normalize to Title Case
    await interaction.response.defer()

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
                "Check your spelling or ask a Merchant to add it!"
            )
        return

    price, note = result
    msg = f"💰 **{item.strip()}** — {price} (per stack)"
    if note:
        msg += f"\n📝 Note: {note}"

    await interaction.followup.send(msg)


@tree.command(name="pricecheckadd", description="Add a new item to the MnM price list. (Merchants only)")
@app_commands.describe(
    item="The item name (e.g. Cool Item)",
    price="The price (e.g. 15 silver)",
    note="Optional note about the item"
)
async def pricecheckadd(interaction: discord.Interaction, item: str, price: str, note: str = ""):
    item = item.strip().title()   # normalize to Title Case
    # Role check — Merchants only
    if not has_allowed_role(interaction):
        await interaction.response.send_message(
            "❌ You need the **Merchants** role to add items to the price list.",
            ephemeral=True   # only the user sees this message
        )
        return

    await interaction.response.defer()

    # Check if item already exists
    try:
        rows = await fetch_sheet_data()
    except Exception as e:
        await interaction.followup.send(f"❌ Couldn't reach the price sheet: `{e}`")
        return

    if find_item(rows, item) is not None:
        await interaction.followup.send(
            f"⚠️ **{item.strip()}** already exists in the price list. "
            "If you need to update it, edit the sheet directly."
        )
        return

    # Append the new row
    try:
        await append_row_to_sheet(item, price, note)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to add item to the sheet: `{e}`")
        return

    msg = f"✅ Added **{item.strip()}** — {price.strip()} (per stack)"
    if note:
        msg += f"\n📝 Note: {note.strip()}"
    await interaction.followup.send(msg)


@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user} — slash commands synced.")


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if DISCORD_TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print("⚠️  Set your DISCORD_TOKEN before running!")
    elif GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY_HERE":
        print("⚠️  Set your GOOGLE_API_KEY before running!")
    elif not GOOGLE_CREDENTIALS_JSON:
        print("⚠️  Set your GOOGLE_CREDENTIALS_JSON before running!")
    else:
        client.run(DISCORD_TOKEN)

  
