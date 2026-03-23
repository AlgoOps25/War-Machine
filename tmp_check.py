import sys
from pathlib import Path
sys.path.insert(0, str(Path(r'C:\Dev\War-Machine')))
from dotenv import load_dotenv
load_dotenv(Path(r'C:\Dev\War-Machine\.env'), override=True)
import os, requests
key = os.getenv('EODHD_API_KEY')
print(f'Key: {repr(key)}')
