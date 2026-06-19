import requests

API_KEY = "dev-tokinarc-2026"
BASE    = "http://localhost:8000"

queries = [
    "huong dan lap bec han tip vao sung han nhu the nao",
    "quy trinh lap rap sung han he N 350A gom nhung buoc gi",
    "sung han bi ban toe nhieu day han cap khong deu phai lam sao",
    "sung TK-308RR bi ro khi can kiem tra thay the linh kien nao",
    "sung han bi hong can sua",
]

for i, q in enumerate(queries, 1):
    r = requests.post(BASE + "/api/v5/query",
        json={"query": q},
        headers={"X-API-Key": API_KEY})
    d = r.json()
    print("=== T" + str(i) + " ===")
    print("Intent: " + str(d.get("intent")) + " | Found: " + str(d.get("success")))
    print(d.get("text", ""))
    print("")
