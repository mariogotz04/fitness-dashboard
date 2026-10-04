#!/usr/bin/env python3
"""Verschickt offene Mitteilungen (Supplement-Erinnerungen) per Web-Push. Gibt keine Inhalte oder Schlüssel aus."""
import json, os, tempfile, urllib.request
from pywebpush import webpush, WebPushException

url, key, token = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_KEY"], os.environ["SYNC_TOKEN"]

def rpc(name, payload):
    req = urllib.request.Request(f"{url}/rest/v1/rpc/{name}", data=json.dumps(payload).encode(),
        headers={"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode()
        return json.loads(body) if body else None

pem = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
pem.write(os.environ["VAPID_PRIVATE"]); pem.close()

items = rpc("push_take", {"token": token}) or []
sent = failed = 0
for it in items:
    try:
        webpush(subscription_info={"endpoint": it["endpoint"], "keys": it["keys"]},
                data=json.dumps({"title": it["title"], "body": it["body"], "url": it["url"], "tag": it["tag"]}),
                vapid_private_key=pem.name, vapid_claims={"sub": "https://mariogotz04.github.io"}, ttl=3600)
        sent += 1
    except WebPushException as e:
        failed += 1
        code = getattr(e.response, "status_code", None)
        if code in (404, 410):
            rpc("push_drop", {"token": token, "p_endpoint": it["endpoint"]})
os.unlink(pem.name)
print(f"verschickt: {sent}, fehlgeschlagen: {failed}")
