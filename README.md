# PriceCheck Bot (MnM)

A Discord bot that lets server members look up item prices from a Google Sheet using slash commands. Members with the **Merchant**, **Officers**, or **GM** roles can add new items directly from Discord. The add command is restricted to the home guild only.

---

## Table of Contents

- [Features](#features)
- [Project Files](#project-files)
- [Google Sheet Structure](#google-sheet-structure)
- [Setup](#setup)
  - [1. Discord Bot](#1-discord-bot)
  - [2. Google API Key (for reads)](#2-google-api-key-for-reads)
  - [3. Google Service Account (for writes)](#3-google-service-account-for-writes)
  - [4. Environment Variables](#4-environment-variables)
  - [5. Dependencies](#5-dependencies)
- [Running the Bot](#running-the-bot)
- [Usage](#usage)
- [Discord Permissions](#discord-permissions)
- [Notes](#notes)

---

## Features

- `/pricecheck` — Look up any item's price by name
- `/pricecheckadd` — Add a new item to the price list (Merchant, Officers, or GM role required — home server only)
- Fuzzy/partial matching — suggests close results if an exact match isn't found
- Automatic Title Case formatting on item names
- Notes support — displays optional notes from Column C when present
- Duplicate protection — warns if an item already exists before adding it

---

## Project Files

```
pricecheck_bot.py   — The bot
requirements.txt    — Python dependencies
Procfile            — (Legacy) Railway start hint; start command is set in Railway dashboard
README.md           — This file
```

---

## Google Sheet Structure

| Column A | Column B | Column C |
|----------|----------------|----------------------|
| Item | Price (in stacks) | Note (optional) |
| Leather Scraps | 50-60 silver | |
| Clouded Crystalized Magic | 15 silver | Currently 30s due to low supply |

- Row 1 is the header row and is skipped by the bot
- Column C is optional — only displayed when a note is present on that row

---

## Setup

### 1. Discord Bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Create a New Application → go to **Bot** → click **Reset Token** and save it
3. Enable **Message Content Intent** under the Bot settings
4. Go to **OAuth2 → URL Generator**, select scopes `bot` and `applications.commands`, permission `Send Messages`
5. Use the generated URL to invite the bot to your server

### 2. Google API Key (for reads)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project → enable the **Google Sheets API**
3. Go to **Credentials → Create Credentials → API Key**
4. Copy the key — this is your `GOOGLE_API_KEY`

### 3. Google Service Account (for writes)

1. In the same Google Cloud project, go to **Credentials → Create Credentials → Service Account**
2. Give it a name and finish creating it
3. Click the service account → **Keys** tab → **Add Key → Create New Key → JSON**
4. A `.json` file will download — open it and copy the `client_email` value
5. Share your Google Sheet with that email address, with **Editor** permissions
6. The full contents of this JSON file will be used as your `GOOGLE_CREDENTIALS_JSON` environment variable

### 4. Environment Variables

Set these three variables wherever you run the bot:

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Your Discord bot token |
| `GOOGLE_API_KEY` | Your Google API key (read-only sheet access) |
| `GOOGLE_CREDENTIALS_JSON` | Full contents of your service account JSON file (write access) |
| `HOME_GUILD_ID` | Your Discord server ID — restricts `/pricecheckadd` to this server only |

### 5. Dependencies

```bash
pip install "discord.py>=2.3" aiohttp google-auth
```

Or install from `requirements.txt`:

```bash
pip install -r requirements.txt
```

---

## Running the Bot

**Locally (Windows):**
```bash
set DISCORD_TOKEN=your-token
set GOOGLE_API_KEY=your-api-key
set GOOGLE_CREDENTIALS_JSON={"type":"service_account",...}
python pricecheck_bot.py
```

**Locally (Mac/Linux):**
```bash
DISCORD_TOKEN=your-token GOOGLE_API_KEY=your-api-key GOOGLE_CREDENTIALS_JSON='{"type":"service_account",...}' python pricecheck_bot.py
```

**On Railway (recommended for 24/7 hosting):**
1. Upload all project files to Railway
2. Set the four environment variables in the **Variables** tab (`DISCORD_TOKEN`, `GOOGLE_API_KEY`, `GOOGLE_CREDENTIALS_JSON`, `HOME_GUILD_ID`)
3. Set the start command to `python pricecheck_bot.py` in Railway's **Settings**
4. Deploy — Railway will install dependencies automatically via `requirements.txt`

---

## Usage

### Look up an item
```
/pricecheck item:Leather Scraps
```
**Response:**
```
💰 Leather Scraps — 50-60 silver (per stack)
```

### Look up an item with a note
```
/pricecheck item:Clouded Crystalized Magic
```
**Response:**
```
💰 Clouded Crystalized Magic — 15 silver (per stack)
📝 Note: Currently 30s due to low supply and broken nodes
```

### Partial match (typo or partial name)
```
/pricecheck item:crystal
```
**Response:**
```
❓ No exact match for Crystal. Did you mean one of these?
• Clouded Crystalized Magic — 15 silver
• Glinting Crystalized Magic — 25-30 silver
• Shining Crystalized Magic — 40 silver
```

### Add a new item (Merchant, Officers, or GM only)
```
/pricecheckadd item:Cool Item price:15 silver note:Optional note here
```
**Response:**
```
✅ Added Cool Item — 15 silver (per stack)
📝 Note: Optional note here
```

---

## Discord Permissions

- `/pricecheck` — available to all server members (channel restrictions can be set via **Server Settings → Integrations**)
- `/pricecheckadd` — restricted to members with the **Merchant**, **Officers**, or **GM** role on the home server (Bazaar Merchants); users without an allowed role, or users on other servers, receive a private error message only they can see

---

## Notes

- Item names are automatically formatted to Title Case regardless of how they are typed
- To add or remove roles that can use `/pricecheckadd`, update the `ALLOWED_ROLES` set near the top of `pricecheck_bot.py`
- New items added via `/pricecheckadd` are appended to the bottom of the sheet
- To update or delete an existing item, edit the Google Sheet directly
- Slash commands may take up to 1 hour to appear in Discord after first deployment
- Keep your `DISCORD_TOKEN` and service account JSON private — never commit them to a public repository
