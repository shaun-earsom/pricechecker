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
       HOME_GUILD_ID              — your Discord server ID (restricts /pricecheckadd to this server)
  3. Run: python pricecheck_bot.py

Slash commands:
  /pricecheck item:Leather Scraps
  /pricecheckadd item:Cool Item price:15 silver note:Optional note here
  /pricecheckedit item:Cool Item newprice:20 silver
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
SHEET_RANGE     = "Sheet1!A2:C"       # Skip row 1 (headers), grab cols A-C
SHEET_APPEND    = "Sheet1!A:C"        # Range used for appending new rows
ALLOWED_ROLES   = {"merchant", "officers", "gm"}  # Roles allowed to use /pricecheckadd (case-insensitive)
HOME_GUILD_ID   = int(os.getenv("HOME_GUILD_ID", "0"))  # Only this server can use /pricecheckadd
# ──────────────────────────────────────────────────────────────────────────────


# ── Price formatting ──────────────────────────────────────────────────────────
# Maps full currency words to their abbreviations
CURRENCY_MAP = {
    'copper':   'c',
    'silver':   's',
    'gold':     'g',
    'platinum': 'p',
    'plat':     'p',
}

def format_price(price: str) -> str:
    """
    Normalizes currency words in a price string to abbreviated form.
    Examples:
      '15 silver'    -> '15s'
      '50-60 silver' -> '50-60s'
      '1 gold 50 silver' -> '1g 50s'
      '15 SILVER'    -> '15s'
    Any unrecognized text is left as-is.
    """
    def replace_currency(match):
        number = match.group(1)   # e.g. '50-60' or '15'
        word   = match.group(2)   # e.g. 'silver'
        abbrev = CURRENCY_MAP.get(word.lower(), word)
        return f"{number}{abbrev}"

    # Match a number (or range like 50-60) followed by optional space and a currency word
    pattern = r'([\d][\d\-]*)\s*(copper|silver|gold|platinum|plat)'
    return re.sub(pattern, replace_currency, price, flags=re.IGNORECASE).strip()
# ──────────────────────────────────────────────────────────────────────────────

# Currency conversion constants (all values in copper)
COPPER_VALUES = {
    'c': 1,
    's': 100,
    'g': 10000,
    'p': 1000000,
}

# Display order from largest to smallest
CURRENCY_ORDER = [('p', 1000000), ('g', 10000), ('s', 100), ('c', 1)]

STACK_SIZE = 20


def price_to_copper(price: str) -> int | None:
    """
    Converts a formatted price string to total copper value.
    Handles ranges by using the average (e.g. '50-60s' -> 55s -> 5500c).
    Returns None if the price cannot be parsed.
    Examples:
      '15s'      -> 1500
      '1g 50s'   -> 15000
      '50-60s'   -> 5500  (average of range)
    """
    total_copper = 0
    found_any = False

    pattern = r'([\d]+)(?:-([\d]+))?\s*([csgp])'
    for match in re.finditer(pattern, price, flags=re.IGNORECASE):
        low  = int(match.group(1))
        high = int(match.group(2)) if match.group(2) else low
        avg  = (low + high) / 2
        unit = match.group(3).lower()
        total_copper += avg * COPPER_VALUES.get(unit, 0)
        found_any = True

    return int(total_copper) if found_any else None


def copper_to_price(copper: int) -> str:
    """
    Converts a copper value back to a readable price string.
    Examples:
      1500    -> '15s'
      15000   -> '1g 50s'
      1000001 -> '1p 1c'
    """
    parts = []
    remaining = copper
    for symbol, value in CURRENCY_ORDER:
        if remaining >= value:
            amount = remaining // value
            remaining = remaining % value
            parts.append(f"{amount}{symbol}")
    return ' '.join(parts) if parts else '0c'


def stack_price(price: str, stack_size: int = STACK_SIZE) -> str | None:
    """
    Returns the formatted price for a full stack of stack_size units.
    Returns None if the price cannot be parsed.
    """
    copper = price_to_copper(price)
    if copper is None:
        return None
    return copper_to_price(copper * stack_size)



def get_service_account_token() -> str:
    """
    Loads the service account credentials from the env var and returns
    a fresh OAuth2 access token for the Sheets API.
    Raises clear errors if credentials are missing or malformed.
    """
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
            if resp.status == 400:
                raise ValueError("Bad request — check that the SPREADSHEET_ID and sheet range are correct.")
            if resp.status == 403:
                raise PermissionError("Access denied — make sure the sheet is shared publicly (viewer access).")
            if resp.status == 404:
                raise ValueError("Spreadsheet not found — check the SPREADSHEET_ID in the config.")
            resp.raise_for_status()
            data = await resp.json()
    return data.get("values", [])


async def append_row_to_sheet(item: str, price: str, note: str) -> None:
    """
    Appends a new row to the sheet via Google Sheets API v4 (write, service account).
    Raises clear errors for common failure cases.
    """
    # get_service_account_token is blocking — run it in a thread to avoid blocking the event loop
    try:
        token = await asyncio.to_thread(get_service_account_token)
    except ValueError as e:
        raise ValueError(str(e))

    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}"
        f"/values/{SHEET_APPEND}:append"
        f"?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"
    )
    row = [item.strip(), format_price(price), note.strip()]
    payload = {"values": [row]}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"}
        ) as resp:
            if resp.status == 403:
                raise PermissionError(
                    "The service account does not have Editor access to the sheet. "
                    "Check that the sheet is shared with the service account email."
                )
            if resp.status == 404:
                raise ValueError("Spreadsheet not found — check the SPREADSHEET_ID in the config.")
            if resp.status == 401:
                raise PermissionError("Google authentication failed — check your GOOGLE_CREDENTIALS_JSON.")
            resp.raise_for_status()


async def update_row_in_sheet(row_index: int, new_price: str, new_note: str | None = None) -> None:
    """
    Updates the price (Column B) of an existing row in the sheet.
    If new_note is provided, also updates Column C.
    If new_note is None, Column C is left untouched.
    row_index is 0-based from the data rows (add 2 to account for header + 1-based sheets indexing).
    Raises clear errors for common failure cases.
    """
    try:
        token = await asyncio.to_thread(get_service_account_token)
    except ValueError as e:
        raise ValueError(str(e))

    # +2 because row 1 is the header and Sheets rows are 1-based
    sheet_row = row_index + 2

    if new_note is not None:
        # Update both price and note (B and C)
        update_range = f"Sheet1!B{sheet_row}:C{sheet_row}"
        payload = {"values": [[new_price.strip(), new_note.strip()]]}
    else:
        # Update price only (B)
        update_range = f"Sheet1!B{sheet_row}"
        payload = {"values": [[new_price.strip()]]}

    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}"
        f"/values/{update_range}?valueInputOption=USER_ENTERED"
    )

    async with aiohttp.ClientSession() as session:
        async with session.put(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"}
        ) as resp:
            if resp.status == 403:
                raise PermissionError(
                    "The service account does not have Editor access to the sheet. "
                    "Check that the sheet is shared with the service account email."
                )
            if resp.status == 404:
                raise ValueError("Spreadsheet not found — check the SPREADSHEET_ID in the config.")
            if resp.status == 401:
                raise PermissionError("Google authentication failed — check your GOOGLE_CREDENTIALS_JSON.")
            resp.raise_for_status()


def find_item(rows: list[list[str]], query: str) -> tuple[int, str, str] | None:
    """
    Case-insensitive search for `query` in Column A.
    Returns (row_index, price, note_or_empty) if found, or None if not found.
    row_index is 0-based from the data rows.
    """
    query_lower = query.strip().lower()
    for i, row in enumerate(rows):
        if not row:
            continue
        item_name = row[0].strip()
        if item_name.lower() == query_lower:
            price = row[1].strip() if len(row) > 1 else "N/A"
            note  = row[2].strip() if len(row) > 2 else ""
            return i, price, note
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
    msg = f"💰 **{item.strip()}** — {format_price(price)}"
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
    item = item.strip().title()   # normalize to Title Case

    # Role + server check
    if not has_allowed_role(interaction):
        await interaction.response.send_message(
            "❌ You need the **Merchant**, **Officers**, or **GM** role on the Bazaar Merchants server to add items.",
            ephemeral=True   # only the user sees this message
        )
        return

    await interaction.response.defer(ephemeral=False)

    # Check if item already exists
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

    # Append the new row
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
    note="Optional: update the note too. Leave blank to keep the existing note."
)
async def pricecheckedit(interaction: discord.Interaction, item: str, newprice: str, note: str = ""):
    item = item.strip().title()   # normalize to Title Case

    # Role + server check
    if not has_allowed_role(interaction):
        await interaction.response.send_message(
            "❌ You need the **Merchant**, **Officers**, or **GM** role on the Bazaar Merchants server to edit prices.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=False)

    # Fetch sheet and find the item
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

    # Update the price
    try:
        await update_row_in_sheet(row_index, format_price(newprice), note if note.strip() else None)
    except PermissionError as e:
        await interaction.followup.send(f"❌ Permission error writing to the sheet: {e}")
        return
    except ValueError as e:
        await interaction.followup.send(f"❌ Configuration error: {e}")
        return
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to update item in the sheet: `{e}`")
        return

    msg = f"✏️ Updated **{item}** — ~~{format_price(old_price)}~~ → {format_price(newprice)}"
    if note:
        msg += f"\n📝 Note: {note}"
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

  
