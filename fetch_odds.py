# -*- coding: utf-8 -*-
"""
fetch_odds.py — recupere les cotes reelles via The Odds API (the-odds-api.com)
et les ecrit dans data/odds.json (line shopping = meilleure cote multi-books),
en est:false (donc pariables/value). NO-OP propre si aucune cle n'est fournie.

Cle d'API : soit variable d'env ODDS_API_KEY, soit data/api_config.json :
   {"odds_api_key": "xxxx", "odds_sport": "soccer_fifa_world_cup",
    "regions": "eu,uk", "markets": "h2h,totals"}

Marches : h2h (1N2) + totals (O/U 2.5). NB : cartons/corners ne sont PAS couverts
par les marches standard de The Odds API (h2h/spreads/totals) -> rester sur une
autre source pour ceux-la. Lancer : python fetch_odds.py
"""
import os
import sys
import json
import urllib.request
import urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))


def _norm(n):
    """Normalise un nom d'equipe pour le matching (The Odds API <-> nos cles)."""
    al = {
        "cabo verde": "Cape Verde", "korea republic": "South Korea",
        "south korea": "South Korea", "ir iran": "Iran", "iran": "Iran",
        "bosnia & herzegovina": "Bosnia", "bosnia and herzegovina": "Bosnia", "bosnia": "Bosnia",
        "curacao": "Curacao", "curaçao": "Curacao",
        "turkiye": "Turkey", "turkey": "Turkey", "cote d'ivoire": "Ivory Coast",
        "côte d'ivoire": "Ivory Coast", "ivory coast": "Ivory Coast",
        "congo dr": "DR Congo", "dr congo": "DR Congo", "usa": "USA",
        "united states": "USA", "czech republic": "Czechia", "czechia": "Czechia",
    }
    k = n.strip().lower()
    return al.get(k, n.strip())


def _best(prices):
    return round(max(prices), 2) if prices else None


def parse_payload(events, matches):
    """events = reponse JSON The Odds API. matches = data/matches.json.
    Retourne {mid(str): {h,d,a,o25,o25_under,est:False,sources,api}}."""
    idx = {}
    for m in matches["remaining"]:
        idx[(_norm(m["home"]), _norm(m["away"]))] = m["id"]
    out = {}
    for ev in events:
        h, a = _norm(ev.get("home_team", "")), _norm(ev.get("away_team", ""))
        mid = idx.get((h, a)) or idx.get((a, h))
        if not mid:
            continue
        hp, dp, ap, ov, un = [], [], [], [], []
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk["key"] == "h2h":
                    for o in mk["outcomes"]:
                        nm = _norm(o["name"])
                        if nm == h: hp.append(o["price"])
                        elif nm == a: ap.append(o["price"])
                        elif o["name"].lower() in ("draw", "tie"): dp.append(o["price"])
                elif mk["key"] == "totals":
                    for o in mk["outcomes"]:
                        if abs(o.get("point", 0) - 2.5) < 0.01:
                            (ov if o["name"].lower() == "over" else un).append(o["price"])
        rec = {"est": False, "api": "the-odds-api", "n_books": len(ev.get("bookmakers", []))}
        if hp and ap:
            rec["h"], rec["a"] = _best(hp), _best(ap)
            if dp: rec["d"] = _best(dp)
        if ov: rec["o25"] = _best(ov)
        if un: rec["o25_under"] = _best(un)
        if "h" in rec or "o25" in rec:
            out[str(mid)] = rec
    return out


def main():
    cfg = {}
    cfgp = os.path.join(ROOT, "data", "api_config.json")
    if os.path.exists(cfgp):
        cfg = json.load(open(cfgp, encoding="utf-8"))
    # Mode --from <fichier> : parse un JSON deja recupere (par l'agent via web_fetch), sans reseau
    if "--from" in sys.argv:
        src = sys.argv[sys.argv.index("--from") + 1]
        events = json.load(open(src, encoding="utf-8"))
        matches = json.load(open(os.path.join(ROOT, "data", "matches.json"), encoding="utf-8"))
        new = parse_payload(events, matches)
        op = os.path.join(ROOT, "data", "odds.json")
        O = json.load(open(op, encoding="utf-8")) if os.path.exists(op) else {}
        for mid, rec in new.items():
            O.setdefault(mid, {}).update(rec)
        json.dump(O, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("OK (--from) : %d matchs mis a jour (cotes reelles est:false)." % len(new))
        return
    key = os.environ.get("ODDS_API_KEY") or cfg.get("odds_api_key")
    if not key:
        print("Pas de cle API (ODDS_API_KEY ou data/api_config.json) -> rien a faire.")
        print("Cree data/api_config.json : {\"odds_api_key\": \"TA_CLE\"} (gratuit sur the-odds-api.com).")
        return
    sport = cfg.get("odds_sport", "soccer_fifa_world_cup")
    params = urllib.parse.urlencode({"apiKey": key, "regions": cfg.get("regions", "eu,uk"),
                                     "markets": cfg.get("markets", "h2h,totals"),
                                     "oddsFormat": "decimal"})
    url = "https://api.the-odds-api.com/v4/sports/%s/odds?%s" % (sport, params)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            events = json.loads(r.read().decode())
            remaining = r.headers.get("x-requests-remaining")
    except Exception as e:
        print("Echec appel API : %s" % e)
        sys.exit(1)
    matches = json.load(open(os.path.join(ROOT, "data", "matches.json"), encoding="utf-8"))
    new = parse_payload(events, matches)
    if not new:
        print("Aucun match correspondant (verifier sport/noms). Events recus : %d" % len(events))
        return
    op = os.path.join(ROOT, "data", "odds.json")
    O = json.load(open(op, encoding="utf-8")) if os.path.exists(op) else {}
    for mid, rec in new.items():
        O.setdefault(mid, {}).update(rec)
    json.dump(O, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("OK : %d matchs mis a jour (cotes reelles est:false). Credits restants : %s" % (len(new), remaining))
    print("-> relance le moteur : python safe_update.py")


if __name__ == "__main__":
    main()
