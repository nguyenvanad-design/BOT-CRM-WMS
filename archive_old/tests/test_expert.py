import requests
API_KEY = "dev-tokinarc-2026"
BASE = "http://localhost:8000"
queries = [
    "002001 thong so ky thuat day du",
    "ACC-308RR kich thuoc goc do",
    "YMSA-308R robot tuong thich gi",
    "bec N lap vao sung D duoc khong",
    "bec han he N day 1.2",
    "sung han bi ban toe nhieu",
]
for q in queries:
    r = requests.post(BASE+"/api/v5/query", json={"query":q}, headers={"X-API-Key":API_KEY})
    d = r.json()
    print(f"Q: {q}")
    print(f"Intent: {d.get('intent')}")
    print(d.get('text',''))
    print()
