import os
import requests

API_KEY = os.getenv("TOKINARC_API_KEY", "")
BASE    = os.getenv("TOKINARC_EVAL_BASE", "http://localhost:8080")

queries = [
    ("nozzle cho sung MIG 350A he N",         "web_ajvglzb3"),
    ("Robot Yaskawa AR1440 dung sung han nao", "web_g2yxukdy"),
    ("Bao gia tip 1.2mm he N",                "web_otpwa3ii"),
    ("hay tu van them",                        "web_otpwa3ii"),
    ("giai phap nao tot hon",                  "web_otpwa3ii"),
    ("Toi mua 100 cai",                       "web_gby079fm"),
    ("Chup khi di cung",                      "web_079fm"),
    ("m la ai",                               "web_6qbiwgen"),
]

print("=" * 70)
for q, sid in queries:
    try:
        r = requests.post(BASE + "/api/v5/query",
            json={"query": q, "session_id": sid},
            headers={"X-API-Key": API_KEY},
            timeout=15)
        d = r.json()
        ok = "✅" if d.get("success") else "❌"
        print(f"{ok} [{sid}]")
        print(f"   Q: {q}")
        print(f"   Intent={d.get('intent')} | Band={d.get('band')}")
        print(f"   {d.get('text','')[:400]}")
    except Exception as e:
        print(f"❌ ERROR: {e}")
    print()
