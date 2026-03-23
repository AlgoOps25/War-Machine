import psycopg2
conn = psycopg2.connect("postgresql://postgres:HhWlQRArNFTIldguAUmHAdRNNXonIGPS@interchange.proxy.rlwy.net:29188/railway")
cur = conn.cursor()
cur.execute("SELECT MIN(datetime), MAX(datetime), COUNT(*) FROM intraday_bars WHERE ticker='IWM'")
print(cur.fetchone())
conn.close()
