# Crisis Wire Bot

Polls news sources, classifies with Claude, drafts X posts, sends to Telegram for human approval, posts approved drafts to @CrisisWireHQ.

## Architecture

```
GitHub Actions cron (every 5 min)
   ↓
1. Check Telegram for pending button presses → post any approved drafts to X
2. Poll RSS feeds (USGS, GDACS, WHO, BBC, Al Jazeera, etc.)
3. New items → Claude Haiku classifier → if relevant → Claude Sonnet drafter → Telegram message with buttons
   ↓
You tap ✅ Approve or ❌ Reject on your phone
   ↓
Next cron run picks up the approval and posts
```

Max ~5 min from "event in RSS" → "post live on X" (human approval bound).

## Setup

### 1. Make this repo PUBLIC (important)

GitHub Actions free tier gives **unlimited minutes for public repos** and only 2,000/month for private. A 5-min cron uses ~8,000 min/month, so the repo must be public. Secrets are still safe — they live in GitHub Secrets, not the code.

In repo settings → General → Danger Zone → Change visibility → Public.

### 2. Add GitHub Secrets

Repo Settings → Secrets and variables → Actions → New repository secret. Add all 8:

| Secret name | Value |
|---|---|
| `X_API_KEY` | from X developer portal |
| `X_API_SECRET` | from X developer portal |
| `X_ACCESS_TOKEN` | from X developer portal |
| `X_ACCESS_TOKEN_SECRET` | from X developer portal |
| `X_BEARER_TOKEN` | from X developer portal |
| `ANTHROPIC_API_KEY` | from console.anthropic.com |
| `TELEGRAM_BOT_TOKEN` | from @BotFather |
| `TELEGRAM_CHAT_ID` | your numeric chat ID from @userinfobot |

### 3. First run (manual)

Repo → Actions tab → "Crisis Wire Bot" → "Run workflow" button. Watch the run; verify it polls feeds and sends a Telegram message.

Once verified, the `cron: '*/5 * * * *'` schedule takes over automatically.

## Local testing

```powershell
cd C:\Users\estab\OneDrive\Desktop\crisiswire-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# fill in .env with your real values (never commit)
python -m src.main
```

## Tuning

- `DRAFTS_PER_RUN` env var (default 3): max drafts sent to Telegram per run
- Edit `src/sources.py` to add/remove RSS feeds
- Edit `src/classifier.py` SYSTEM prompt to tune what counts as "relevant"
- Edit `src/drafter.py` SYSTEM prompt to tune the post style

## Rate limits

- X Free tier: 500 posts/month (~16/day). The bot drafts at most 3/run × 288 runs/day = 864, but human approval is the actual throttle.
- Anthropic: ~$0.50-3/month at this volume

## Stop the bot

Repo → Actions → "Crisis Wire Bot" → "..." menu → Disable workflow.
