# -*- coding: utf-8 -*-
"""
fetch_results.py — recupere les RESULTATS via API-Football (api-sports.io) et
met a jour data/matches.json (deplace les matchs termines de "remaining" vers
"played" avec le score). Fiabilise la collecte des scores (vs recherche web).

Cle d'API : data/api_config.json -> "apifootball_key" (+ apifootball_host,
apifootball_league=1 (World Cup), apifootball_season=2026). NO-OP propre sans cle.

Deux modes :
  python fetch_results.py              # appel reseau direct (urllib)
  python fetch_results.py --from f.json # parse un JSON deja recupere (agent via web_fetch)
"""
import os
import sys
import json
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
try:
    from fetch_odds import _norm
except Exception:
    def _norm(n):
        return (n or "").strip()

FINISHED = {"FT", "AET", "PEN"}


def parse_fixtures(payload, matches):
    """payload = reponse API-Football (/fixtures). Retourne (moves, infos).
    moves = liste de matchs termines a basculer en played : {home,away,score,date}."""
    resp = payload.get("response", payload) if isinstance(payload, dict) else payload
    rem = {(_norm(m["home"]), _norm(m["away"])): m for m in matches["remaining"]}
    played_keys = {(_norm(p["home"]), _norm(p["away"])) for p in matches["played"]}
    moves = []
    for fx in resp:
        try:
            short = fx["fixture"]["status"]["short"]
            h = _norm(fx["teams"]["home"]["name"]); a = _norm(fx["teams"]["away"]["name"])
            gh, ga = fx["goals"]["home"], fx["goals"]["away"]
            date = fx["fixture"]["date"][:10]
        except (KeyError, TypeError):
            continue
        if short not in FINISHED or gh is None or ga is None:
            continue
        if (h, a) in played_keys or (a, h) in played_keys:
            continue  # idempotent
        mt = rem.get((h, a)) or rem.get((a, h))
        if not mt:
            continue
        # respecter l'ordre home/away de NOTRE fixture
        if (_norm(mt["home"]), _norm(mt["away"])) == (h, a):
            score = [gh, ga]
        else:
            score = [ga, gh]
        moves.append({"id": mt["id"], "home": mt["home"], "away": mt["away"],
                      "group": mt.get("group"), "date": date, "score": score})
    return moves


def apply_moves(matches, moves):
    by_id = {m["id"]: m for m in matches["remaining"]}
    for mv in moves:
        mt = by_id.get(mv["id"])
        if not mt:
            continue
        matches["remaining"] = [m for m in matches["remaining"] if m["id"] != mv["id"]]
        entry = {"group": mt.get("group"), "home": mt["home"], "away": mt["away"],
                 "score": mv["score"], "date": mv["date"]}
        if mt.get("stage"):
            entry["stage"] = mt["stage"]
        matches["played"].append(entry)
    return matches


def main():
    cfg = {}
    cfgp = os.path.join(ROOT, "data", "api_config.json")
    if os.path.exists(cfgp):
        cfg = json.load(open(cfgp, encoding="utf-8"))
    mp = os.path.join(ROOT, "data", "matches.json")
    matches = json.load(open(mp, encoding="utf-8"))

    if "--from" in sys.argv:
        payload = json.load(open(sys.argv[sys.argv.index("--from") + 1], encoding="utf-8"))
    else:
        key = os.environ.get("APIFOOTBALL_KEY") or cfg.get("apifootball_key")
        if not key:
            print("Pas de cle API-Football (apifootball_key dans data/api_config.json) -> rien a faire.")
            return
        host = cfg.get("apifootball_host", "v3.football.api-sports.io")
        league = cfg.get("apifootball_league", 1)
        season = cfg.get("apifootball_season", 2026)
        url = "https://%s/fixtures?league=%s&season=%s" % (host, league, season)
        headers = ({"x-rapidapi-key": key, "x-rapidapi-host": host}
                   if "rapidapi" in host else {"x-apisports-key": key})
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                payload = json.loads(r.read().decode())
        except Exception as e:
            print("Echec appel API-Football : %s" % e)
            sys.exit(1)

    moves = parse_fixtures(payload, matches)
    if not moves:
        print("Aucun nouveau match terminé à intégrer (ou aucun correspondant).")
        return
    matches = apply_moves(matches, moves)
    json.dump(matches, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for mv in moves:
        print("  + %s %d-%d %s (%s)" % (mv["home"], mv["score"][0], mv["score"][1], mv["away"], mv["date"]))
    print("OK : %d match(s) intégré(s). Règle les paris puis relance : python safe_update.py" % len(moves))


if __name__ == "__main__":
    main()
