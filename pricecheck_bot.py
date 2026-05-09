"""
Discord Price Check Bot — Price Check (MnM)
Uses Google Sheets API v4 + discord.py slash commands.

Read  → API key (no auth needed for public sheet)
Write → Google Service Account (JSON stored in GOOGLE_CREDENTIALS_JSON env var)

Setup:
  1. pip install "discord.py>=2.3" aiohttp google-auth requests
  2. Set environment variables:
       DISCORD_TOKEN              — your Discord bot token
       GOOGLE_API_KEY             — your Google API key (for reads)
       GOOGLE_CREDENTIALS_JSON    — full contents of your service account JSON (for writes)
       HOME_GUILD_ID              — your Discord server ID (restricts write commands to this server)
  3. Run: python pricecheck_bot.py

Slash commands:
  /pricecheck item:Leather Scraps
  /pricecheckadd item:Cool Item price:15 silver note:Optional note here
  /pricecheckedit item:Cool Item newprice:20 silver note:Optional updated note
"""

import os
import re
import json
import asyncio
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
SHEET_RANGE     = "Sheet1!A2:C"
SHEET_APPEND    = "Sheet1!A:C"
ALLOWED_ROLES   = {"merchant", "officers", "gm"}
HOME_GUILD_ID   = int(os.getenv("HOME_GUILD_ID", "0"))
STACK_SIZE       = 20
ARROW_STACK_SIZE = 1000
# ──────────────────────────────────────────────────────────────────────────────


# ── Price formatting ──────────────────────────────────────────────────────────
CURRENCY_MAP = {
    'copper':   'c',
    'silver':   's',
    'gold':     'g',
    'platinum': 'p',
    'plat':     'p',
}

COPPER_VALUES  = {'c': 1, 's': 100, 'g': 10000, 'p': 1000000}
CURRENCY_ORDER = [('p', 1000000), ('g', 10000), ('s', 100), ('c', 1)]


def format_price(price: str) -> str:
    """Normalizes currency words to abbreviated form e.g. '15 silver' -> '15s'."""
    def replace_currency(match):
        number = match.group(1)
        word   = match.group(2)
        abbrev = CURRENCY_MAP.get(word.lower(), word)
        return f"{number}{abbrev}"
    pattern = r'([\d][\d\-]*)\s*(copper|silver|gold|platinum|plat)'
    return re.sub(pattern, replace_currency, price, flags=re.IGNORECASE).strip()


def price_to_copper(price: str) -> int | None:
    """
    Converts a formatted price string to total copper value.
    Handles ranges by averaging e.g. '50-60s' -> 5500c.
    Returns None if the price cannot be parsed.
    """
    total_copper = 0
    found_any    = False
    pattern = r'(\d+)(?:-(\d+))?\s*([csgp])'
    for match in re.finditer(pattern, price, flags=re.IGNORECASE):
        low  = int(match.group(1))
        high = int(match.group(2)) if match.group(2) else low
        avg  = (low + high) / 2
        unit = match.group(3).lower()
        total_copper += avg * COPPER_VALUES.get(unit, 0)
        found_any = True
    return int(total_copper) if found_any else None


def copper_to_price(copper: int) -> str:
    """Converts a copper value to a readable price string e.g. 15000 -> '1g 50s'."""
    parts     = []
    remaining = copper
    for symbol, value in CURRENCY_ORDER:
        if remaining >= value:
            amount    = remaining // value
            remaining = remaining % value
            parts.append(f"{amount}{symbol}")
    return ' '.join(parts) if parts else '0c'


def stack_price(price: str, stack_size: int = STACK_SIZE) -> str | None:
    """Returns the formatted price for a full stack. Returns None if unparseable."""
    copper = price_to_copper(price)
    if copper is None:
        return None
    return copper_to_price(copper * stack_size)
# ──────────────────────────────────────────────────────────────────────────────


# ── Google API helpers ────────────────────────────────────────────────────────
def get_service_account_token() -> str:
    """Returns a fresh OAuth2 access token from the service account credentials."""
    if not GOOGLE_CREDENTIALS_JSON:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable is not set.")
    try:
        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
    except json.JSONDecodeError as e:
        raise ValueError(f"GOOGLE_CREDENTIALS_JSON is not valid JSON: {e}")
    try:
        creds = service_account.Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        creds.refresh(Request())
    except Exception as e:
        raise ValueError(f"Failed to authenticate with Google service account: {e}")
    return creds.token


async def fetch_sheet_data() -> list[list[str]]:
    """Fetches all data rows from the sheet (read, API key)."""
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}"
        f"/values/{SHEET_RANGE}?key={GOOGLE_API_KEY}"
    )
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 400:
                raise ValueError("Bad request — check SPREADSHEET_ID and sheet range.")
            if resp.status == 403:
                raise PermissionError("Access denied — make sure the sheet is shared publicly.")
            if resp.status == 404:
                raise ValueError("Spreadsheet not found — check the SPREADSHEET_ID in the config.")
            resp.raise_for_status()
            data = await resp.json()
    return data.get("values", [])


async def append_row_to_sheet(item: str, price: str, note: str) -> None:
    """Appends a new row to the sheet (write, service account)."""
    try:
        token = await asyncio.to_thread(get_service_account_token)
    except ValueError as e:
        raise ValueError(str(e))

    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}"
        f"/values/{SHEET_APPEND}:append"
        f"?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"
    )
    payload = {"values": [[item.strip(), format_price(price), note.strip()]]}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}) as resp:
            if resp.status == 403:
                raise PermissionError("The service account does not have Editor access to the sheet.")
            if resp.status == 404:
                raise ValueError("Spreadsheet not found — check the SPREADSHEET_ID in the config.")
            if resp.status == 401:
                raise PermissionError("Google authentication failed — check your GOOGLE_CREDENTIALS_JSON.")
            resp.raise_for_status()


async def update_row_in_sheet(row_index: int, new_price: str, new_note: str | None = None) -> None:
    """
    Updates the price (Column B) of an existing row.
    If new_note is provided, also updates Column C.
    If new_note is None, Column C is left untouched.
    """
    try:
        token = await asyncio.to_thread(get_service_account_token)
    except ValueError as e:
        raise ValueError(str(e))

    sheet_row = row_index + 2  # +2 for header row and 1-based indexing

    if new_note is not None:
        update_range = f"Sheet1!B{sheet_row}:C{sheet_row}"
        payload = {"values": [[new_price.strip(), new_note.strip()]]}
    else:
        update_range = f"Sheet1!B{sheet_row}"
        payload = {"values": [[new_price.strip()]]}

    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}"
        f"/values/{update_range}?valueInputOption=USER_ENTERED"
    )

    async with aiohttp.ClientSession() as session:
        async with session.put(url, json=payload, headers={"Authorization": f"Bearer {token}"}) as resp:
            if resp.status == 403:
                raise PermissionError("The service account does not have Editor access to the sheet.")
            if resp.status == 404:
                raise ValueError("Spreadsheet not found — check the SPREADSHEET_ID in the config.")
            if resp.status == 401:
                raise PermissionError("Google authentication failed — check your GOOGLE_CREDENTIALS_JSON.")
            resp.raise_for_status()
# ──────────────────────────────────────────────────────────────────────────────


# ── Data helpers ──────────────────────────────────────────────────────────────
def find_item(rows: list[list[str]], query: str) -> tuple[int, str, str] | None:
    """
    Case-insensitive search for query in Column A.
    Returns (row_index, price, note) if found, or None if not found.
    row_index is 0-based from the data rows.
    """
    query_lower = query.strip().lower()
    for i, row in enumerate(rows):
        if not row:
            continue
        if row[0].strip().lower() == query_lower:
            price = row[1].strip() if len(row) > 1 else "N/A"
            note  = row[2].strip() if len(row) > 2 else ""
            return i, price, note
    return None


def has_allowed_role(interaction: discord.Interaction) -> bool:
    """Returns True if the user is in the home guild AND has an allowed role."""
    if not interaction.guild:
        return False
    if HOME_GUILD_ID and interaction.guild.id != HOME_GUILD_ID:
        return False
    return any(role.name.lower() in ALLOWED_ROLES for role in interaction.user.roles)
# ──────────────────────────────────────────────────────────────────────────────


# ── Bot setup ─────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
client  = discord.Client(intents=intents)
tree    = app_commands.CommandTree(client)


@tree.command(name="pricecheck", description="Look up the price of an item from the MnM price list.")
@app_commands.describe(item="The item name to look up (e.g. Leather Scraps)")
async def pricecheck(interaction: discord.Interaction, item: str):
    item = item.strip().title()
    await interaction.response.defer()

    try:
        rows = await fetch_sheet_data()
    except PermissionError as e:
        await interaction.followup.send(f"❌ Permission error: {e}")
        return
    except ValueError as e:
        await interaction.followup.send(f"❌ Configuration error: {e}")
        return
    except Exception as e:
        await interaction.followup.send(f"❌ Couldn't reach the price sheet: `{e}`")
        return

    result = find_item(rows, item)

    if result is None:
        item_lower    = item.lower()
        close_matches = [
            (row[0], row[1] if len(row) > 1 else "N/A", row[2] if len(row) > 2 else "")
            for row in rows
            if row and item_lower in row[0].strip().lower()
        ]
        if close_matches:
            def match_line(name, price, note):
                formatted   = format_price(price)
                item_stack  = ARROW_STACK_SIZE if "arrow" in name.lower() else STACK_SIZE
                stack       = stack_price(formatted, item_stack)
                line        = f"• **{name}** — {formatted}"
                if stack:
                    line += f" (stack of {item_stack}: {stack})"
                if note:
                    line += f"  *(Note: {note})*"
                return line
            lines = "\n".join(match_line(name, price, note) for name, price, note in close_matches)
            await interaction.followup.send(
                f"🔍 Showing results for **{item}**:\n{lines}"
            )
        else:
            await interaction.followup.send(
                f"❓ **{item}** was not found in the price list. "
                "Check your spelling or ask a Merchant to add it!"
            )
        return

    _, price, note = result
    formatted  = format_price(price)
    item_stack = ARROW_STACK_SIZE if "arrow" in item.lower() else STACK_SIZE
    stack      = stack_price(formatted, item_stack)
    msg        = f"💰 **{item}** — {formatted}"
    if stack:
        msg += f" (stack of {item_stack}: {stack})"
    if note:
        msg += f"\n📝 Note: {note}"
    await interaction.followup.send(msg)


@tree.command(name="pricecheckadd", description="Add a new item to the MnM price list. (Merchant/Officers/GM only)")
@app_commands.describe(
    item="The item name (e.g. Cool Item)",
    price="The price (e.g. 15 silver)",
    note="Optional note about the item"
)
async def pricecheckadd(interaction: discord.Interaction, item: str, price: str, note: str = ""):
    item = item.strip().title()

    if not has_allowed_role(interaction):
        await interaction.response.send_message(
            "❌ You need the **Merchant**, **Officers**, or **GM** role on the Bazaar Merchants server to add items.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    try:
        rows = await fetch_sheet_data()
    except PermissionError as e:
        await interaction.followup.send(f"❌ Permission error reading the sheet: {e}")
        return
    except ValueError as e:
        await interaction.followup.send(f"❌ Configuration error: {e}")
        return
    except Exception as e:
        await interaction.followup.send(f"❌ Couldn't reach the price sheet: `{e}`")
        return

    if find_item(rows, item) is not None:
        await interaction.followup.send(
            f"⚠️ **{item}** already exists in the price list. "
            "Use /pricecheckedit to update its price instead."
        )
        return

    try:
        await append_row_to_sheet(item, price, note)
    except PermissionError as e:
        await interaction.followup.send(f"❌ Permission error writing to the sheet: {e}")
        return
    except ValueError as e:
        await interaction.followup.send(f"❌ Configuration error: {e}")
        return
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to add item to the sheet: `{e}`")
        return

    msg = f"✅ Added **{item}** — {format_price(price)}"
    if note:
        msg += f"\n📝 Note: {note.strip()}"
    await interaction.followup.send(msg)


@tree.command(name="pricecheckedit", description="Edit the price (and optionally note) of an existing item. (Merchant/Officers/GM only)")
@app_commands.describe(
    item="The existing item name to update (e.g. Cool Item)",
    newprice="The new price to set (e.g. 20 silver)",
    note="Optional: update the note. Leave blank to keep the existing note."
)
async def pricecheckedit(interaction: discord.Interaction, item: str, newprice: str, note: str = ""):
    item = item.strip().title()

    if not has_allowed_role(interaction):
        await interaction.response.send_message(
            "❌ You need the **Merchant**, **Officers**, or **GM** role on the Bazaar Merchants server to edit prices.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    try:
        rows = await fetch_sheet_data()
    except PermissionError as e:
        await interaction.followup.send(f"❌ Permission error reading the sheet: {e}")
        return
    except ValueError as e:
        await interaction.followup.send(f"❌ Configuration error: {e}")
        return
    except Exception as e:
        await interaction.followup.send(f"❌ Couldn't reach the price sheet: `{e}`")
        return

    result = find_item(rows, item)
    if result is None:
        await interaction.followup.send(
            f"❓ **{item}** was not found in the price list. "
            "Check your spelling or use /pricecheckadd to add it as a new item."
        )
        return

    row_index, old_price, old_note = result

    try:
        await update_row_in_sheet(row_index, format_price(newprice), note.strip() if note.strip() else None)
    except PermissionError as e:
        await interaction.followup.send(f"❌ Permission error writing to the sheet: {e}")
        return
    except ValueError as e:
        await interaction.followup.send(f"❌ Configuration error: {e}")
        return
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to update item in the sheet: `{e}`")
        return

    msg          = f"✏️ Updated **{item}** — ~~{format_price(old_price)}~~ → {format_price(newprice)}"
    display_note = note.strip() if note.strip() else old_note
    if display_note:
        msg += f"\n📝 Note: {display_note}"
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
    elif not HOME_GUILD_ID:
        print("⚠️  Set your HOME_GUILD_ID before running!")
    else:
        client.run(DISCORD_TOKEN)

  
