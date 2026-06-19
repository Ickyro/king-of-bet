# -*- coding: utf-8 -*-
"""
run_all.py — RUNNER UNIFIE MULTI-SPORTS.

Pour chaque sport enregistré disposant de données, charge le plugin, construit
les tickets (meme moteur engine.tickets) et NORMALISE les pronostics en lignes
uniformes. Ecrit app/multisport_data.js = const MULTISPORT = {...}; consommé par
le hub multi-sports (app/MultiSport.html).

Football reste géré par run_worldcup.py pour l'app WC dédiée ; ici on en produit
une vue compacte normalisée (sans le Monte-Carlo, inutile pour le hub).
"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from engine import sport as sport_mod, tickets
import sports  # noqa: F401


def _rows_football(sp):
    rows = []
    for p in sp.preds[:24]:
        note = "O2.5 %s%% · BTTS %s%%" % (p["o25"], p["btts"])
        if p.get("desk"):
            note += " · 🧠 " + p["desk"].get("lean", "")
        rows.append({"id": p["id"], "date": p["date"], "title": p["home"] + " – " + p["away"],
                     "probs": [[p["home"], p["p1"]], ["Nul", p["pn"]], [p["away"], p["p2"]]], "note": note,
                     "rat": [[p["home"], round(sp.T.get(p["home"], {}).get("elo", 0))],
                             [p["away"], round(sp.T.get(p["away"], {}).get("elo", 0))]], "rlab": "Elo"})
    return rows


def _rows_tennis(sp):
    return [{"id": p["id"], "date": p["date"], "title": p["p1_name"] + " vs " + p["p2_name"],
             "probs": [[p["p1_name"], p["p1"]], [p["p2_name"], p["p2"]]],
             "note": "%s · %s" % (p.get("surface", ""), p.get("tournament", "")),
             "rat": [[p["p1_name"], round(sp._elo(p["p1_name"], p.get("surface", "hard")))],
                     [p["p2_name"], round(sp._elo(p["p2_name"], p.get("surface", "hard")))]], "rlab": "Elo"} for p in sp.preds]


def _rows_basket(sp):
    return [{"id": p["id"], "date": p["date"], "title": p["home"] + " @ " + p["away"],
             "probs": [[p["home"], p["pwin_home"]], [p["away"], p["pwin_away"]]],
             "note": "total %s · marge %+.1f" % (p["total"], p["margin"]),
             "rat": [[p["home"], round(sp.T.get(p["home"], {}).get("ppg", 0) - sp.T.get(p["home"], {}).get("oppg", 0), 1)],
                     [p["away"], round(sp.T.get(p["away"], {}).get("ppg", 0) - sp.T.get(p["away"], {}).get("oppg", 0), 1)]],
             "rlab": "Net pts"} for p in sp.preds]


def _rows_nhl(sp):
    return [{"id": p["id"], "date": p["date"], "title": p["away"] + " @ " + p["home"],
             "probs": [[p["home"], p["pwin_home"]], [p["away"], p["pwin_away"]]],
             "note": "total %s buts · %s" % (p["total"], p.get("competition", "NHL")),
             "rat": [[p["home"], round(sp.T.get(p["home"], {}).get("gf", 0) - sp.T.get(p["home"], {}).get("ga", 0), 2)],
                     [p["away"], round(sp.T.get(p["away"], {}).get("gf", 0) - sp.T.get(p["away"], {}).get("ga", 0), 2)]],
             "rlab": "Diff buts/match"} for p in sp.preds]


BUILDERS = {"football": _rows_football, "football_clubs": _rows_football, "tennis": _rows_tennis, "basketball": _rows_basket, "wnba": _rows_basket, "nfl": _rows_basket, "nhl": _rows_nhl}


def build_sport(key):
    sp = sport_mod.get_sport(key, ROOT)
    sp.load()
    if key in ("football", "football_clubs"):
        legs = tickets.selections_from_predictions(sp.preds, sp.scorers)
    else:
        legs = sp.all_selections()
    batch = tickets.build_tickets(legs, {"bankroll": 100.0, "n_variants": 2})
    rows = BUILDERS[key](sp)
    top = sorted([l for l in legs if 0 < (l.get("edge") or 0) <= 0.20], key=lambda l: -(l.get("edge") or 0))[:8]
    top = [{"label": l["label"], "market": l["market"], "cote": l["cote"],
            "p": round(l["p"] * 100, 1), "edge": round((l.get("edge") or 0) * 100, 1),
            "est": bool(l.get("est")), "date": l.get("date"), "event_id": l.get("event_id")} for l in top]
    # legs de VALUE disciplinés (cotes réelles uniquement) → ledger multi-sports
    vlegs = [{"sport": key, "date": l.get("date"), "event_id": l.get("event_id"),
              "market": l.get("market"), "sel": l.get("sel"), "label": l.get("label"),
              "cote": l.get("cote"), "p": round(l.get("p") or 0, 4), "edge": round(l.get("edge") or 0, 4)}
             for l in legs if (not l.get("est")) and 0.03 < (l.get("edge") or 0) <= 0.15 and (l.get("p") or 0) >= 0.15]
    # Player props (points joueurs) si un fichier props.json existe pour ce sport
    props = []
    try:
        ddir = getattr(sp, "data_dir", None)
        if ddir and os.path.exists(os.path.join(ROOT, ddir, "props.json")):
            from engine import props as _propmod
            pdb = json.load(open(os.path.join(ROOT, ddir, "props.json"), encoding="utf-8"))
            plp = os.path.join(ROOT, ddir, "players.json")
            players = json.load(open(plp, encoding="utf-8")) if os.path.exists(plp) else {}
            players = {k: v for k, v in players.items() if not str(k).startswith("_")}
            props = _propmod.prop_edges(pdb, players)
    except Exception:
        props = []
    live = any(not l.get("est") for l in legs)
    return {"key": key, "name": sp.name, "n_events": len(sp.preds), "rows": rows,
            "tickets": batch, "top": top, "n_values": len(getattr(sp, "values", [])),
            "value_legs": vlegs, "live": live, "props": props}


def update_multi_ledger(out):
    """Ledger virtuel multi-sports (data/paper_multi.json).

    Place automatiquement les value bets disciplinés des sports à COTES RÉELLES,
    SAUF 'football' (déjà suivi par run_worldcup.py / data/paper_bets.json — on
    évite le double comptage). Mise quart-de-Kelly plafonnée à 5% de bankroll.
    Le règlement (won/lost + cote_close + clv) est fait par les tâches planifiées
    après les matchs ; ici on (ré)calcule la performance à partir du réglé.
    """
    import datetime
    path = os.path.join(ROOT, "data", "paper_multi.json")
    L = {"bankroll": 100.0, "start": 100.0, "bets": [], "next_id": 1}
    if os.path.exists(path):
        try:
            L = json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    L.setdefault("start", 100.0); L.setdefault("bets", [])
    L.setdefault("next_id", max([b.get("id", 0) for b in L["bets"]], default=0) + 1)
    placed = {(b["sport"], b["date"], b.get("event_id"), b["market"], b["sel"]) for b in L["bets"]}
    today = datetime.date.today().isoformat()
    settled_pl = sum(b.get("pl", 0) for b in L["bets"] if b.get("status") in ("won", "lost"))
    bk = round(L["start"] + settled_pl, 2)
    for key, sp in out.items():
        if key == "football":
            continue
        for v in sp.get("value_legs", []):
            k = (v["sport"], v["date"], v.get("event_id"), v["market"], v["sel"])
            if k in placed:
                continue
            cote = v.get("cote") or 0
            if cote <= 1:
                continue
            kelly = max(0.0, v.get("edge", 0) / (cote - 1))
            stake = round(max(0.5, min(bk * 0.05, bk * 0.25 * kelly)), 2)
            L["bets"].append({"id": L["next_id"], "sport": v["sport"], "date": v["date"],
                              "event_id": v.get("event_id"), "match": v.get("label"),
                              "market": v["market"], "sel": v["sel"], "cote": cote,
                              "p": v["p"], "edge": v["edge"], "stake": stake, "status": "pending",
                              "placed": today, "line_open": cote, "cote_close": None, "clv": None, "pl": 0})
            L["next_id"] += 1; placed.add(k)
    json.dump(L, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    done = [b for b in L["bets"] if b.get("status") in ("won", "lost")]
    done.sort(key=lambda b: (b.get("placed", ""), b.get("id", 0)))
    pts = []; cum = 0.0; st = 0.0
    for b in done:
        cum += b.get("pl", 0); st += b.get("stake", 0); pts.append(round(cum, 2))
    clvs = [b["clv"] for b in L["bets"] if b.get("clv") is not None]
    blist = [{"sport": b["sport"], "market": b["market"], "sel": b["sel"], "cote": b["cote"],
              "clv": (round(b["clv"] * 100, 1) if b.get("clv") is not None else None),
              "status": b.get("status")} for b in L["bets"][-12:]]
    return {"points": pts, "staked": round(st, 2), "pl": round(cum, 2),
            "roi": round(cum / st * 100, 1) if st else 0, "n": len(done),
            "pending": sum(1 for b in L["bets"] if b.get("status") == "pending"),
            "bankroll": round(L["start"] + cum, 2),
            "clv": round(sum(clvs) / len(clvs) * 100, 1) if clvs else None,
            "clv_n": len(clvs), "bets": blist}


def main():
    out = {}
    for key in ("football", "football_clubs", "tennis", "basketball", "wnba", "nfl", "nhl"):
        try:
            out[key] = build_sport(key)
            print("  %-11s OK : %d events, %d value(s)" % (key, out[key]["n_events"], out[key]["n_values"]))
        except Exception as e:
            print("  %-11s SKIP (%s)" % (key, str(e)[:70]))
    import datetime
    perf = {"points": [], "staked": 0, "pl": 0, "roi": 0, "n": 0, "bankroll": None}
    pbp = os.path.join(ROOT, "data", "paper_bets.json")
    if os.path.exists(pbp):
        PB = json.load(open(pbp, encoding="utf-8"))
        done = [b for b in PB.get("bets", []) if b.get("status") in ("won", "lost")]
        done.sort(key=lambda b: (b.get("placed", ""), b.get("id", 0)))
        cum = 0.0; st = 0.0
        for b in done:
            cum += b.get("pl", 0); st += b.get("stake", 0)
            perf["points"].append(round(cum, 2))
        perf.update({"staked": round(st, 2), "pl": round(cum, 2),
                     "roi": round(cum / st * 100, 1) if st else 0, "n": len(done),
                     "bankroll": PB.get("bankroll")})
    perf_multi = update_multi_ledger(out)
    calib = None
    _cp = os.path.join(ROOT, "data", "calibration.json")
    if os.path.exists(_cp):
        try:
            calib = json.load(open(_cp, encoding="utf-8"))
        except Exception:
            calib = None
    payload = {"generated": datetime.date.today().isoformat(), "sports": out, "perf": perf,
               "perf_multi": perf_multi, "calib": calib,
               "order": [k for k in ("football", "football_clubs", "tennis", "basketball", "wnba", "nfl", "nhl") if k in out]}
    with open(os.path.join(ROOT, "app", "multisport_data.js"), "w", encoding="utf-8") as f:
        f.write("const MULTISPORT = " + json.dumps(payload, ensure_ascii=False) + ";")
    print("OK -> app/multisport_data.js (%d sports)" % len(out))


if __name__ == "__main__":
    main()
