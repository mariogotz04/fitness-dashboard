#!/usr/bin/env python3
"""Wartet bis zum Ende der Satzpause und schickt dann die Mitteilung, falls der Timer noch gilt."""
import json, os, sys, tempfile, time, urllib.request
from pywebpush import webpush, WebPushException

url, key, token, tid = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_KEY"], os.environ["SYNC_TOKEN"], os.environ["TIMER_ID"]

def rpc(name, payload):
    req = urllib.request.Request(f"{url}/rest/v1/rpc/{name}", data=json.dumps(payload).encode(),
        headers={"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode()
        return json.loads(body) if body else None

deadline = time.time() + 16 * 60
while time.time() < deadline:
    st = rpc("rest_peek", {"token": token, "p_id": tid})
    if not st or not st.get("active"):
        print("Timer nicht mehr aktiv."); sys.exit(0)
    wait = float(st.get("wait") or 0)
    if wait <= 0.5:
        break
    time.sleep(min(wait, 20))

pem = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
pem.write(os.environ["VAPID_PRIVATE"]); pem.close()
sent = 0
for it in rpc("rest_claim", {"token": token, "p_id": tid}) or []:
    try:
        webpush(subscription_info={"endpoint": it["endpoint"], "keys": it["keys"]},
                data=json.dumps({"title": it["title"], "body": it["body"], "url": it["url"], "tag": it["tag"]}),
                vapid_private_key=pem.name, vapid_claims={"sub": "https://mariogotz04.github.io"}, ttl=120)
        sent += 1
    except WebPushException as e:
        if getattr(e.response, "status_code", None) in (404, 410):
            rpc("push_drop", {"token": token, "p_endpoint": it["endpoint"]})
os.unlink(pem.name)
print(f"verschickt: {sent}")
