import psycopg2
import os
import requests
from datetime import date

db_url = os.getenv('DATABASE_URL')
webhook = os.getenv('DISCORD_WEBHOOK_URL')

db = psycopg2.connect(db_url)
cursor = db.cursor()

# Get today's stats
cursor.execute("""
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
        ROUND(SUM(CASE WHEN outcome IS NOT NULL THEN profit_pct END), 2) as total_profit
    FROM signal_outcomes
    WHERE DATE(signal_time) = CURRENT_DATE
""")

total, wins, losses, profit = cursor.fetchone()
win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

print(f' Today Stats:')
print(f'   Total: {total}')
print(f'   Wins: {wins}')
print(f'   Losses: {losses}')
print(f'   Win Rate: {win_rate:.1f}%')
print(f'   Total P&L: {profit}%')
print()

# Send to Discord
message = f' **WAR MACHINE EOD** - {date.today()}\n\n Trades: {total} | W/L: {wins}/{losses} ({win_rate:.0f}% WR)\n Total P&L: {profit:+.2f}%'

response = requests.post(webhook, json={'content': message})
print(f'Discord: {" Sent" if response.status_code == 204 else " Failed"} ({response.status_code})')

db.close()
