# Server Deploy

## Target path

`/opt/call_bot`

## What this setup does

- creates `/opt/call_bot`
- copies `bot.py`, `requirements.txt`, `.env.example`
- optionally copies `calls_history.jsonl`
- creates `.venv`
- installs Python dependencies
- installs `systemd` service `call_bot`
- enables autostart

## Quick start on the server

Copy the project to the server and run:

```bash
cd /path/to/CallBot
sudo bash deploy/install_server.sh
```

Then open:

```bash
sudo nano /opt/call_bot/.env
```

Set:

```env
TELEGRAM_BOT_TOKEN=your_real_token_here
```

Then start:

```bash
sudo systemctl start call_bot
sudo systemctl status call_bot
```

Logs:

```bash
sudo journalctl -u call_bot -f
```

After bot code updates:

```bash
cd /path/to/CallBot
sudo bash deploy/install_server.sh
sudo systemctl restart call_bot
```
