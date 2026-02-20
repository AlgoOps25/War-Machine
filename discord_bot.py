"""
discord_bot.py — Reserved for future Discord bot integration.

Currently War Machine sends all alerts via discord_helpers.py using
a simple outbound webhook (no bot token required).  This file is
intentionally a stub and is NOT imported by any other module.

Future use cases:
  - Two-way Discord commands (e.g. "!status", "!positions", "!pause")
  - Interactive signal confirmations via slash commands
  - Role-based alert routing

When implemented, this module will require a Discord bot token set as
the DISCORD_BOT_TOKEN environment variable on Railway.
"""
