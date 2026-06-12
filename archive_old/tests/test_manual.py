import requests

API_KEY = "dev-tokinarc-2026"
BASE    = "http://localhost:8000"

queries = [
    "toi muon mua 50 cai chup khi 500A ben ban co khong",
    "toi can mua bec han 1 ly 6",
    "toi can mua chup khi 500",
    "liet ke nhung sung han ben ban dang ban",
    "toi muon mua bec han 001001 di voi cach dien va chup khi nao",
    "ban co ban u2773b00 khong",
]

for i, q in enumerate(queries, 1):
    r = requests.post(BASE + "/api/v5/query", json={"query": q}, headers={"X-API-Key": API_KEY})
    d = r.json()
    print("=== Cau " + str(i) + " ===")
    print("Q: " + q)
    print("Intent: " + str(d.get("intent")) + " | Band: " + str(d.get("confidence_band")) + " | Found: " + str(d.get("success")))
    print("Answer: " + str(d.get("text")))
    print("")
