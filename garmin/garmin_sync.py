#!/usr/bin/env python3
"""Holt Marios Garmin-Daten (Schlaf, HRV, Ruhepuls, Body Battery, Schritte, Gewicht)
für das Fitness-Dashboard.

Einmalig anmelden (Passwort gibt nur Mario selbst ein):
    python3 garmin_sync.py --login

Daten der letzten Tage als JSON ausgeben (nutzt die gespeicherte Anmeldung):
    python3 garmin_sync.py --days 3
"""
import argparse
import datetime as dt
import getpass
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")

TOKENS = os.path.expanduser("~/.garminconnect")
if os.environ.get("GARMIN_TOKENS"):
    # In GitHub Actions: Sitzung kommt verschlüsselt als Secret (garth.dumps), nie als Datei im Repository.
    import tempfile
    import garth as _garth
    TOKENS = tempfile.mkdtemp()
    _c = _garth.Client()
    _c.loads(os.environ["GARMIN_TOKENS"])
    _c.dump(TOKENS)


def login():
    import garth
    email = input("Garmin-E-Mail: ").strip()
    password = getpass.getpass("Garmin-Passwort (wird nicht angezeigt): ")
    garth.login(email, password, prompt_mfa=lambda: input("Code aus der Garmin-Mail/App: ").strip())
    os.makedirs(TOKENS, exist_ok=True)
    garth.save(TOKENS)
    os.chmod(TOKENS, 0o700)
    print("Angemeldet. Die Anmeldung ist in ~/.garminconnect gespeichert.")


def hm(ms):
    """Garmins *Local-Zeitstempel sind Ortszeit, als UTC-Millisekunden kodiert."""
    if not ms:
        return None
    return dt.datetime.utcfromtimestamp(ms / 1000).strftime("%H:%M")


def safe(fn, *a):
    try:
        return fn(*a) or {}
    except Exception:
        return {}


def day(api, d):
    out = {"date": d}
    sl = safe(api.get_sleep_data, d).get("dailySleepDTO") or {}
    if sl.get("sleepTimeSeconds"):
        out["sleep"] = {
            "h": round(sl["sleepTimeSeconds"] / 3600, 1),
            "bed": hm(sl.get("sleepStartTimestampLocal")),
            "wake": hm(sl.get("sleepEndTimestampLocal")),
        }
        score = ((sl.get("sleepScores") or {}).get("overall") or {}).get("value")
        if score:
            out["sleep"]["score"] = int(score)
    hrv = (safe(api.get_hrv_data, d).get("hrvSummary") or {}).get("lastNightAvg")
    summ = safe(api.get_user_summary, d)
    rhr = summ.get("restingHeartRate")
    bb = summ.get("bodyBatteryAtWakeTime") or summ.get("bodyBatteryHighestValue")
    extra = {k: v for k, v in (("hrv", hrv), ("rhr", rhr), ("bb", bb)) if v}
    if extra:
        out.setdefault("sleep", {}).update({k: int(v) for k, v in extra.items()})
    if summ.get("totalSteps"):
        out["steps"] = int(summ["totalSteps"])
    weights = safe(api.get_body_composition, d).get("dateWeightList") or []
    if weights and weights[-1].get("weight"):
        out["weight"] = round(weights[-1]["weight"] / 1000, 1)
    return out


def fetch(days):
    from garminconnect import Garmin
    if not os.path.isdir(TOKENS):
        print(json.dumps({"error": "login_required"}))
        return 2
    api = Garmin()
    try:
        api.login(TOKENS)
    except Exception as e:
        print(json.dumps({"error": "login_failed", "detail": str(e)[:200]}))
        return 2
    today = dt.date.today()
    res = [day(api, (today - dt.timedelta(days=i)).isoformat()) for i in range(days - 1, -1, -1)]
    try:
        api.garth.dump(TOKENS)  # erneuerte Tokens sichern
    except Exception:
        pass
    print(json.dumps({"days": res}, ensure_ascii=False))
    return 0


CONFIG = os.path.expanduser("~/.fitness-dashboard/config.json")


def push(days):
    """Schickt die Garmin-Tage an die eigene Fitness-App (Supabase-Funktion garmin_sync)."""
    import io
    import contextlib
    import urllib.request
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fetch(days)
    payload = json.loads(buf.getvalue() or "{}")
    if code != 0 or "days" not in payload:
        print("Garmin-Abruf fehlgeschlagen:", payload.get("error", "unbekannt"))
        return 2
    if os.environ.get("SUPABASE_URL"):
        cfg = {"url": os.environ["SUPABASE_URL"], "key": os.environ["SUPABASE_KEY"], "token": os.environ["SYNC_TOKEN"]}
    else:
        cfg = json.load(open(CONFIG))
    req = urllib.request.Request(
        cfg["url"].rstrip("/") + "/rest/v1/rpc/garmin_sync",
        data=json.dumps({"token": cfg["token"], "days": payload["days"]}).encode(),
        headers={"apikey": cfg["key"], "Authorization": "Bearer " + cfg["key"], "Content-Type": "application/json"},
        method="POST",
    )
    import urllib.error
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print(dt.datetime.now().isoformat(timespec="seconds"), "übertragen:", r.read().decode())
    except urllib.error.HTTPError as e:
        msg = json.loads(e.read().decode() or "{}").get("message", "")
        print(dt.datetime.now().isoformat(timespec="seconds"), "Fehler:", e.code, msg[:120])
        return 1
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--login", action="store_true")
    p.add_argument("--push", action="store_true", help="direkt in die eigene Fitness-App schreiben")
    p.add_argument("--days", type=int, default=3)
    a = p.parse_args()
    if a.login:
        login()
    elif a.push:
        sys.exit(push(a.days))
    else:
        sys.exit(fetch(a.days))
