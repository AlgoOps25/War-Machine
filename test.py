import requests, os

key = os.getenv("EODHD_API_KEY")

url = f"https://eodhd.com/api/unicornbay/options/SPY.US?api_token={key}&fmt=json"

r = requests.get(url)

print("STATUS:", r.status_code)
print(r.text[:800])
