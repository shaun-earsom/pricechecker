# PriceCheck Bot (MnM)

A Discord bot for looking up item prices from a Google Sheet using slash commands. Members with the **Merchant**, **Officers**, or **GM** roles can add and edit items directly from Discord. Write commands are restricted to the home server only.

A read-only copy of the price data can be found [here](https://docs.google.com/spreadsheets/d/1OswS9O6njNTfkzGNsKlhqbSMa0uzUY6HNsd1cPlWfqY/edit?usp=sharing).

---

## 0. Overview

### Slash Commands

- `/pricecheck` — Look up any item's price by name (all members)
- `/pricecheckadd` — Add a new item to the price list (Merchant, Officers, GM only)
- `/pricecheckedit` — Edit the price and/or note of an existing item (Merchant, Officers, GM only)

### Features

- Fuzzy/partial matching — suggests close results if an exact match isn't found
- Automatic Title Case formatting on item names
- Automatic price formatting — currency words are converted to abbreviations on both display and write e.g. `15 silver` → `15s`, `50-60 silver` → `50-60s`, `1 gold 50 silver` → `1g 50s`
- Notes support — displays optional notes from Column C when present on the same row
- Duplicate protection — warns if an item already exists before adding it

---

## 1. Setup & Configuration

### Prerequisites

- A Discord account and server where you have Owner permissions
- A Google Cloud project with the **Google Sheets API** enabled
- Python 3.11+
- A Railway account (or other hosting) for 24/7 uptime

### Google Sheet Structure

The bot reads from a sheet with the following layout:

| Column A | Column B          | Column C         |
|----------|-------------------|------------------|
| Item     | Price (in stacks) | Note (optional)  |

Row 1 is the header row and is skipped automatically. Column C is optional and only displayed when a note is present on the same row as the queried item.

### Environment Variables

Set these four variables wherever you run the bot:

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Your Discord bot token |
| `GOOGLE_API_KEY` | Your Google API key (read-only sheet access) |
| `GOOGLE_CREDENTIALS_JSON` | Full contents of your service account JSON file (write access) |
| `HOME_GUILD_ID` | Your Discord server ID — restricts `/pricecheckadd` and `/pricecheckedit` to this server only |

### Installation

```bash
pip install -r requirements.txt
```

Or manually:

```bash
pip install "discord.py>=2.3" aiohttp google-auth requests
```

---

## 2. Discord Bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Create a New Application → go to **Bot** → click **Reset Token** and save it
3. Enable **Message Content Intent** under the Bot settings
4. Go to **OAuth2 → URL Generator**, select scopes `bot` and `applications.commands`, permission `Send Messages`
5. Use the generated URL to invite the bot to your server
6. To get your server ID: go to **User Settings → Advanced → Enable Developer Mode**, then right-click your server name and click **Copy Server ID**

---

## 3. Google API Credentials

### API Key (for reads)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project → enable the **Google Sheets API**
3. Go to **Credentials → Create Credentials → API Key**
4. Copy the key — this is your `GOOGLE_API_KEY`

### Service Account (for writes)

1. In the same project, go to **Credentials → Create Credentials → Service Account**
2. Give it a name and finish creating it
3. Click the service account → **Keys** tab → **Add Key → Create New Key → JSON**
4. A `.json` file will download — open it and copy the `client_email` value
5. Share your Google Sheet with that email address, with **Editor** permissions
6. The full contents of this JSON file will be used as your `GOOGLE_CREDENTIALS_JSON` environment variable

---

## 4. Deployment

### Locally (Windows)

```bash
set DISCORD_TOKEN=your-token
set GOOGLE_API_KEY=your-api-key
set GOOGLE_CREDENTIALS_JSON={"type":"service_account",...}
set HOME_GUILD_ID=your-server-id
python pricecheck_bot.py
```

### Locally (Mac/Linux)

```bash
DISCORD_TOKEN=your-token GOOGLE_API_KEY=your-api-key HOME_GUILD_ID=your-server-id GOOGLE_CREDENTIALS_JSON='{"type":"service_account",...}' python pricecheck_bot.py
```

### Railway (recommended for 24/7 hosting)

1. Upload all project files to Railway
2. Set the four environment variables in the **Variables** tab
3. Set the start command to `python pricecheck_bot.py` in Railway's **Settings**
4. Deploy — Railway will install dependencies automatically via `requirements.txt`

> ⚠️ Slash commands may take up to 1 hour to appear in Discord after first deployment.

---

## 5. Usage

### Look up an item

```
/pricecheck item:Leather Scraps
```
```
💰 Leather Scraps — 50-60s (per stack)
```

### Look up an item with a note

```
/pricecheck item:Clouded Crystalized Magic
```
```
💰 Clouded Crystalized Magic — 15s (per stack)
📝 Note: Currently 30s due to low supply and broken nodes
```

### Partial match

```
/pricecheck item:crystal
```
```
❓ No exact match for Crystal. Did you mean one of these?
• Clouded Crystalized Magic — 15s
• Glinting Crystalized Magic — 25-30s
• Shining Crystalized Magic — 40s
```

### Add a new item *(Merchant, Officers, GM only)*

```
/pricecheckadd item:Cool Item price:15 silver note:Optional note here
```
```
✅ Added Cool Item — 15s (per stack)
📝 Note: Optional note here
```

### Edit an existing item *(Merchant, Officers, GM only)*

Update price only — note is preserved:

```
/pricecheckedit item:Leather Scraps newprice:45 silver
```
```
✏️ Updated Leather Scraps — ~~50-60s~~ → 45s (per stack)
```

Update price and note:

```
/pricecheckedit item:Leather Scraps newprice:45 silver note:Price dropped after patch
```
```
✏️ Updated Leather Scraps — ~~50-60s~~ → 45s (per stack)
📝 Note: Price dropped after patch
```

---

## 6. Permissions & Security

- `/pricecheck` — available to all server members. Channel restrictions can be set via **Server Settings → Integrations**
- `/pricecheckadd` and `/pricecheckedit` — restricted to members with the **Merchant**, **Officers**, or **GM** role on the Bazaar Merchants server. Users without an allowed role, or users on other servers, receive a private error only they can see
- To add or remove allowed roles, update the `ALLOWED_ROLES` set near the top of `pricecheck_bot.py`
- Keep your `DISCORD_TOKEN` and service account JSON private — never commit them to a public repository

---

## 7. Notes

- New items added via `/pricecheckadd` are appended to the bottom of the sheet
- To update an item's price or note, use `/pricecheckedit` or edit the Google Sheet directly
- To delete an item, edit the Google Sheet directly
