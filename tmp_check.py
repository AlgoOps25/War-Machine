import sys
from pathlib import Path
sys.path.insert(0, str(Path(r'C:\Dev\War-Machine')))
from dotenv import load_dotenv
load_dotenv(Path(r'C:\Dev\War-Machine\.env'))
import os, requests
key = os.getenv('EODHD_API_KEY')
print(f'Key: {repr(key)}')
url = f'https://eodhd.com/api/intraday/IWM.US?api_token={key}&interval=5m&fmt=json'
print(f'URL: {url}')
resp = requests.get(url, timeout=30)
print(f'Status: {resp.status_code}')
print(f'Body: {resp.text[:500]}')
