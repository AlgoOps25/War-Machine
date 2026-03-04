"""
EOD Discord Report - Automated Daily Funnel Summary

Sends comprehensive end-of-day report to Discord:
  - Signal funnel conversion rates
  - Top rejection reasons
  - A/B test results
  - Grade distribution
  - Multiplier impact

Scheduling:
  Call send_eod_report() at 4:15 PM ET daily

Usage:
  from app.analytics.eod_discord_report import send_eod_report
  
  # In main loop or cron
  if current_time == "16:15:00":
      await send_eod_report()
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
import discord
from discord.ext import commands
from app.analytics.funnel_analytics import funnel_tracker
from app.analytics.ab_test_framework import ab_test
from app.signals.signal_analytics import signal_tracker
from utils import config

ET = ZoneInfo("America/New_York")


async def send_eod_report(
    channel_id: Optional[int] = None,
    session_date: Optional[str] = None
):
    """
    Send end-of-day funnel report to Discord.
    
    Args:
        channel_id: Discord channel ID (uses config.DISCORD_CHANNEL_ID if not provided)
        session_date: Session date to report on (defaults to today)
    """
    try:
        # Get Discord bot
        intents = discord.Intents.default()
        intents.message_content = True
        bot = commands.Bot(command_prefix="!", intents=intents)
        
        @bot.event
        async def on_ready():
            channel = bot.get_channel(channel_id or config.DISCORD_CHANNEL_ID)
            if not channel:
                print(f"[DISCORD] Channel not found: {channel_id or config.DISCORD_CHANNEL_ID}")
                await bot.close()
                return
            
            # Generate report components
            session = session_date or datetime.now(ET).strftime("%Y-%m-%d")
            
            # 1. Funnel Analytics
            funnel_report = funnel_tracker.get_daily_report(session)
            
            # 2. Signal Analytics (from existing system)
            signal_summary = signal_tracker.get_daily_summary(session)
            
            # 3. A/B Test Results
            ab_test_report = ab_test.get_ab_test_report(days_back=30)
            
            # Build Discord embed
            embed = discord.Embed(
                title="📊 EOD REPORT - War Machine",
                description=f"Session: {session}",
                color=discord.Color.blue(),
                timestamp=datetime.now(ET)
            )
            
            # Add funnel field
            embed.add_field(
                name="🔍 Signal Funnel",
                value=f"```\n{_format_funnel_summary(session)}\n```",
                inline=False
            )
            
            # Add rejection reasons
            rejections = funnel_tracker.get_rejection_reasons(session, limit=5)
            if rejections:
                rejection_text = "\n".join([f"{i+1}. {reason}: {count}x" 
                                           for i, (reason, count) in enumerate(rejections)])
                embed.add_field(
                    name="❌ Top Rejections",
                    value=f"```\n{rejection_text}\n```",
                    inline=False
                )
            
            # Add A/B test winners (if any)
            winners = ab_test.check_winners(days_back=30)
            if winners:
                winner_text = "\n".join([
                    f"{param}: {data['winner']}={data['winner_value']} "
                    f"({data['winner_win_rate']:.1f}% vs {data['loser_win_rate']:.1f}%)"
                    for param, data in winners.items()
                ])
                embed.add_field(
                    name="🏆 A/B Test Winners",
                    value=f"```\n{winner_text}\n```",
                    inline=False
                )
            
            # Send embed
            await channel.send(embed=embed)
            
            # Send full reports as code blocks (if requested)
            # await channel.send(f"```\n{signal_summary}\n```")
            # await channel.send(f"```\n{ab_test_report}\n```")
            
            print(f"[DISCORD] EOD report sent to channel {channel.name}")
            await bot.close()
        
        # Run bot
        await bot.start(config.DISCORD_BOT_TOKEN)
    
    except Exception as e:
        print(f"[DISCORD] Error sending EOD report: {e}")


def _format_funnel_summary(session: str) -> str:
    """
    Format funnel summary for Discord embed.
    
    Returns:
        Compact funnel visualization
    """
    lines = []
    
    prev_passed = None
    for stage in funnel_tracker.STAGES:
        stats = funnel_tracker.get_stage_conversion(stage, session)
        
        if stats['total'] == 0:
            continue
        
        if prev_passed is not None and prev_passed > 0:
            from_prev_pct = (stats['passed'] / prev_passed * 100)
            lines.append(f"{stage:<12} {stats['passed']:>3}  ({from_prev_pct:>5.1f}%)")
        else:
            lines.append(f"{stage:<12} {stats['passed']:>3}")
        
        prev_passed = stats['passed']
    
    return "\n".join(lines) if lines else "No signals today"


# Scheduling helper
def should_send_eod_report() -> bool:
    """
    Check if it's time to send EOD report (4:15 PM ET).
    
    Returns:
        True if current time is 16:15 ET
    """
    now = datetime.now(ET)
    return now.hour == 16 and now.minute == 15


if __name__ == "__main__":
    import asyncio
    
    print("Testing EOD Discord report...\n")
    print("Note: This requires:")
    print("  - DISCORD_BOT_TOKEN in config")
    print("  - DISCORD_CHANNEL_ID in config")
    print("  - Bot must have permission to send messages\n")
    
    # Test report generation
    session = datetime.now(ET).strftime("%Y-%m-%d")
    funnel_report = funnel_tracker.get_daily_report(session)
    print(funnel_report)
    
    # Uncomment to test actual Discord send
    # asyncio.run(send_eod_report())
