# -*- coding: utf-8 -*-
"""
fetch_live.py — collecte LIVE multi-books + props + clôture (CLV), via The Odds API.

⚠️ Le runner Cowork n'a PAS de réseau Python direct : ces commandes consomment un
fichier JSON déjà récupéré par l'outil web_fetch (mode --from). Sur une machine avec
réseau, --url ferait l'appel directement (urllib) ; ici on passe par web_fetch.

Sous-commandes :
  odds  --data data_wnba --from f.json   → line shopping : meilleur prix par issue +
                                           ligne "sharp" (Pinnacle) pour le dé-vig.
  props --data data_wnba --from f.json   → enregistre les player props (points joueurs)
                                           dans data_wnba/props.json.
  close --data data_wnba --from f.json   → snapshot des cotes de CLÔTURE : pose
                                           cote_close + clv sur les paris pending de
                                           data/paper_multi.json (CLV = cote_prise/clôture−1).

Schéma odds enrichi (rétro-compatible) : ml_home/ml_away/total_line/over/under = MEILLEUR
prix dispo ; "sharp" = {ml_home,ml_away,total_line,over,under} (Pinnacle) ; "books" = nb ;
"shop" = {ml_home:book, ...} pour tracer où parier.
"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.abspath(__file__))
SHARP = "pinnacle"


def _norm(s):
    return " ".join(str(s).strip().lower().split())


def _load(path):
    raw = open(path, encoding="utf-8").read()
    i = raw.find("[")
    j = raw.find("{")
    if i < 0 or (0 <= j < i):
        i = j
    obj, _ = json.JSONDecoder().raw_decode(raw[i:])
    return obj


def _best_sharp(ev):
    home, away = ev["home_team"], ev["away_team"]
    ml = {}   # book -> {home, away}
    tot = {}  # book -> {point, over, under}
    for b in ev.get("bookmakers", []):
        bk = b["key"]
        for mk in b.get("markets", []):
            if mk["key"] == "h2h":
                d = {}
                for o in mk["outcomes"]:
                    if _norm(o["name"]) == _norm(home):
                        d["home"] = o["price"]
                    elif _norm(o["name"]) == _norm(away):
                        d["away"] = o["price"]
                if "home" in d and "away" in d:
                    ml[bk] = d
            elif mk["key"] == "totals":
                d = {}
                for o in mk["outcomes"]:
                    d["point"] = o.get("point")
                    if o["name"] == "Over":
                        d["over"] = o["price"]
                    elif o["name"] == "Under":
                        d["under"] = o["price"]
                if "over" in d and "under" in d:
                    tot[bk] = d
    od = {"est": False, "n_books": len(ev.get("bookmakers", [])), "shop": {}}
    if ml:
        hb = max(ml.items(), key=lambda kv: kv[1]["home"])
        ab = max(ml.items(), key=lambda kv: kv[1]["away"])
        od["ml_home"] = round(hb[1]["home"], 3)
        od["ml_away"] = round(ab[1]["away"], 3)
        od["shop"]["ml_home"] = hb[0]
        od["shop"]["ml_away"] = ab[0]
    sharp = {}
    if SHARP in ml:
        sharp["ml_home"] = ml[SHARP]["home"]
        sharp["ml_away"] = ml[SHARP]["away"]
    if SHARP in tot:
        line = tot[SHARP]["point"]
        sharp["total_line"] = line
        sharp["over"] = tot[SHARP]["over"]
        sharp["under"] = tot[SHARP]["under"]
        od["total_line"] = line
        ov = [(b, v["over"]) for b, v in tot.items() if v.get("point") == line]
        un = [(b, v["under"]) for b, v in tot.items() if v.get("point") == line]
        bo = max(ov, key=lambda x: x[1]); bu = max(un, key=lambda x: x[1])
        od["over"] = round(bo[1], 3); od["under"] = round(bu[1], 3)
        od["shop"]["over"] = bo[0]; od["shop"]["under"] = bu[0]
    elif tot:
        any_b = sorted(tot.items())[0][1]
        od["total_line"] = any_b["point"]; od["over"] = any_b["over"]; od["under"] = any_b["under"]
    if sharp:
        od["sharp"] = sharp
    return home, away, od


def cmd_odds(data_dir, frm):
    events = _load(frm)
    if isinstance(events, dict):
        events = [events]
    mp = os.path.join(ROOT, data_dir, "matches.json")
    M = json.load(open(mp, encoding="utf-8"))
    idx = {(_norm(m["home"]), _norm(m["away"])): m for m in M}
    n = 0; unmatched = []
    for ev in events:
        home, away, od = _best_sharp(ev)
        m = idx.get((_norm(home), _norm(away)))
        if not m:
            unmatched.append("%s vs %s" % (home, away)); continue
        if "ml_home" not in od:
            continue
        m["odds"] = od; n += 1
    json.dump(M, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("odds: %d matchs mis a jour dans %s" % (n, data_dir))
    if unmatched:
        print("  non modelises (a ajouter + noter ppg/oppg):", ", ".join(unmatched))


def cmd_props(data_dir, frm):
    ev = _load(frm)
    if isinstance(ev, list):
        ev = ev[0]
    home, away = ev["home_team"], ev["away_team"]
    players = {}
    for b in ev.get("bookmakers", []):
        for mk in b.get("markets", []):
            if mk["key"] != "player_points":
                continue
            for o in mk["outcomes"]:
                pl = o.get("description"); pt = o.get("point")
                if not pl:
                    continue
                e = players.setdefault(pl, {"player": pl, "line": pt})
                if o["name"] == "Over":
                    e["over"] = o["price"]
                elif o["name"] == "Under":
                    e["under"] = o["price"]
                e["line"] = pt
    pp = os.path.join(ROOT, data_dir, "props.json")
    DB = {}
    if os.path.exists(pp):
        try:
            DB = json.load(open(pp, encoding="utf-8"))
        except Exception:
            pass
    key = "%s @ %s" % (home, away)
    DB[key] = {"home": home, "away": away, "market": "player_points",
               "players": [p for p in players.values() if p.get("over") and p.get("under")]}
    json.dump(DB, open(pp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("props: %d joueurs pour %s" % (len(DB[key]["players"]), key))


def cmd_close(data_dir, frm):
    events = _load(frm)
    if isinstance(events, dict):
        events = [events]
    mp = os.path.join(ROOT, data_dir, "matches.json")
    M = json.load(open(mp, encoding="utf-8"))
    id2t = {m["id"]: (m["home"], m["away"]) for m in M}
    # cotes de cloture par (norm home, norm away)
    close = {}
    for ev in events:
        home, away, od = _best_sharp(ev)
        close[(_norm(home), _norm(away))] = od
    lp = os.path.join(ROOT, "data", "paper_multi.json")
    if not os.path.exists(lp):
        print("pas de paper_multi.json"); return
    L = json.load(open(lp, encoding="utf-8"))
    sport_key = os.path.basename(data_dir).replace("data_", "")
    n = 0
    for bet in L.get("bets", []):
        if bet.get("status") != "pending" or bet.get("sport") != sport_key:
            continue
        if bet.get("cote_close"):
            continue
        teams = id2t.get(bet.get("event_id"))
        if not teams:
            continue
        od = close.get((_norm(teams[0]), _norm(teams[1])))
        if not od:
            continue
        cc = None
        mkt = bet.get("market"); sel = bet.get("sel", "")
        if mkt == "Moneyline":
            if _norm(sel) == _norm(teams[0]):
                cc = od.get("ml_home")
            elif _norm(sel) == _norm(teams[1]):
                cc = od.get("ml_away")
        elif mkt == "Total":
            if sel.startswith("Over"):
                cc = od.get("over")
            elif sel.startswith("Under"):
                cc = od.get("under")
        if cc:
            bet["cote_close"] = cc
            bet["clv"] = round(bet["cote"] / cc - 1, 4)
            n += 1
    json.dump(L, open(lp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("close: %d paris %s horodates (CLV)" % (n, sport_key))


def main(argv):
    if len(argv) < 2:
        print("usage: fetch_live.py {odds|props|close} --data DIR --from FILE"); return
    cmd = argv[1]
    data_dir = "data_wnba"; frm = None
    i = 2
    while i < len(argv):
        if argv[i] == "--data":
            data_dir = argv[i + 1]; i += 2
        elif argv[i] == "--from":
            frm = argv[i + 1]; i += 2
        else:
            i += 1
    if not frm:
        print("--from requis"); return
    {"odds": cmd_odds, "props": cmd_props, "close": cmd_close}[cmd](data_dir, frm)


if __name__ == "__main__":
    main(sys.argv)
