# -*- coding: utf-8 -*-
"""
run_worldcup.py — ORCHESTRATEUR (entree principale, v3.0).

ROOT auto-detecte. Lance le sport (football par defaut) via le moteur generique,
ecrit les CSV, app/app_data.js (ticket_batch + ticket_pool + backtest), archive
les probas pre-match (proba_log.json), et gere le paper trading de l'agent.

Usage :  python run_worldcup.py            # football (World Cup)
"""
import os
import sys
import json
import csv
import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from engine import sport as sport_mod, tickets
import sports  # noqa: F401  enregistre les sports
from backtest import run_backtest, run_backtest_logged, aggregate_clv

SPORT_KEY = sys.argv[1] if len(sys.argv) > 1 else "football"
GEN_DATE = datetime.date.today().isoformat()
VERSION = "v3.0"


def main():
    sp = sport_mod.get_sport(SPORT_KEY, ROOT)
    sp.load()
    sp.cap_values()
    qual = sp.simulate()
    sp.compute_signals()

    legs = tickets.selections_from_predictions(sp.preds, sp.scorers)
    batch = tickets.build_tickets(legs, {"bankroll": 100.0, "n_variants": 3})

    # --- archivage des probas PRE-MATCH (snapshot avant que le match soit joue) ---
    plog_path = os.path.join(ROOT, "data", "proba_log.json")
    plog = json.load(open(plog_path, encoding="utf-8")) if os.path.exists(plog_path) else {}
    for p in sp.preds:  # sp.preds = matchs RESTANTS => probas genuinement pre-match
        plog[p["home"] + " - " + p["away"]] = {"date": p["date"], "p1": p["p1"],
                                               "pn": p["pn"], "p2": p["p2"], "logged": GEN_DATE}
    json.dump(plog, open(plog_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # --- snapshot des cotes 1N2 (pour le CLV auto au reglement) ---
    clos_path = os.path.join(ROOT, "data", "closing_odds.json")
    clos = json.load(open(clos_path, encoding="utf-8")) if os.path.exists(clos_path) else {}
    for p in sp.preds:
        if p.get("mkt"):
            clos[p["home"] + " - " + p["away"]] = {"h": p["mkt"]["h"], "d": p["mkt"]["d"], "a": p["mkt"]["a"]}
    json.dump(clos, open(clos_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # --- backtests : reel (probas loggees) prioritaire, repli Elo-core ---
    bt_logged = run_backtest_logged(sp.played, plog)
    bt_elo = run_backtest(sp.T, sp.played, sp.c)
    bt = dict(bt_logged if bt_logged["n"] >= 5 else bt_elo)
    bt["source"] = "logged" if bt_logged["n"] >= 5 else "elo_core"
    bt["logged"] = bt_logged
    bt["elo_core"] = bt_elo
    # Allègement app_data.js : ces sous-objets (per-match) ne sont PAS lus par l'app
    # (la carte Calibration ne lit que n/brier/hit/source/clv). Gain ~10 Ko.
    for _k in ("logged", "elo_core", "detail"):
        bt.pop(_k, None)

    out_dir = os.path.join(ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "predictions.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Date", "Grp", "Match", "P1 %", "PN %", "P2 %", "Cote juste 1", "N", "2",
                    "Over2.5 %", "BTTS %", "xG dom", "xG ext", "Scores probables"])
        for p in sp.preds:
            w.writerow([p["date"], p["grp"], p["home"] + " - " + p["away"],
                        "%.1f" % p["p1"], "%.1f" % p["pn"], "%.1f" % p["p2"],
                        "%.2f" % p["f1"], "%.2f" % p["fn"], "%.2f" % p["f2"],
                        "%.1f" % p["o25"], "%.1f" % p["btts"], "%.2f" % p["xgh"], "%.2f" % p["xga"],
                        " / ".join("%d-%d %.0f%%" % (s[0], s[1], s[2]) for s in p["scores"])])
    with open(os.path.join(out_dir, "qualification.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Groupe", "Equipe", "P(1er)%", "P(2e)%", "P(3e repeche)%", "P(qualif)%"])
        for q in qual:
            w.writerow([q["grp"], q["team"], q["p1"], q["p2"], q["p3q"], q["pq"]])

    app_data = {
        "generated": GEN_DATE, "version": VERSION, "sport": sp.key, "sport_name": sp.name,
        "played": sp.played, "predictions": sp.preds, "qualification": qual,
        "values": sp.values, "anomalies": sp.anomalies, "scorers": sp.scorers,
        "ticket_batch": batch, "ticket_pool": legs,
        "factors": sp.factors_out, "profils": sp.profils, "backtest": bt,
        "signals": sp.signals,
    }

    bkcfg = json.load(open(os.path.join(ROOT, "data", "bankroll.json"), encoding="utf-8"))
    pb_path = os.path.join(ROOT, "data", "paper_bets.json")
    if os.path.exists(pb_path):
        PB = json.load(open(pb_path, encoding="utf-8"))
    else:
        PB = {"bankroll_start": bkcfg["bankroll_initiale"], "bankroll": bkcfg["bankroll_initiale"], "bets": []}

    played_idx = {(p["home"], p["away"]): p["score"] for p in sp.played}
    for b in PB["bets"]:
        if b["status"] != "pending" or b["market"] != "1N2":
            continue
        key = tuple(b["match"].split(" - "))
        if key in played_idx:
            sh, sa = played_idx[key]
            out = "1" if sh > sa else ("2" if sa > sh else "N")
            if out == b["sel"]:
                b["status"] = "won"; b["pl"] = round(b["stake"] * (b["cote"] - 1), 2)
            else:
                b["status"] = "lost"; b["pl"] = -b["stake"]
            PB["bankroll"] = round(PB["bankroll"] + b["pl"], 2)
            co = clos.get(b["match"])
            if co and "clv" not in b:
                cl = {"1": co["h"], "N": co["d"], "2": co["a"]}.get(b["sel"])
                if cl:
                    b["cote_close"] = cl
                    b["clv"] = round(b["cote"] / cl - 1, 4)

    def already(mid, sel, market):
        return any(b for b in PB["bets"] if b.get("mid") == mid and b["sel"] == sel and b["market"] == market)

    expo_pending = sum(b["stake"] for b in PB["bets"] if b["status"] == "pending")
    budget = max(0.0, PB["bankroll"] * bkcfg["expo_max"] - expo_pending)
    conf_min = bkcfg.get("confiance_min_desk", 3)
    conf = {pp["home"] + " - " + pp["away"]: (pp.get("desk") or {}).get("confiance") for pp in sp.preds}
    new_bets = []
    for v in sorted(sp.values, key=lambda x: -x["edge"]):
        mid_v = next((p["id"] for p in sp.preds if p["home"] + " - " + p["away"] == v["match"]), None)
        if already(mid_v, v["sel"], "1N2"):
            continue
        cfv = conf.get(v["match"])
        if cfv is not None and cfv < conf_min:   # gate de confiance du desk
            continue
        stake = round(min(PB["bankroll"] * v["stake"] / 100, budget), 2)
        if stake < 0.5:
            continue
        budget -= stake
        new_bets.append({"id": len(PB["bets"]) + len(new_bets) + 1, "placed": GEN_DATE, "mid": mid_v,
                         "match": v["match"], "market": "1N2", "sel": v["sel"], "cote": v["cote"],
                         "stake": stake, "edge": round(v["edge"], 1), "status": "pending", "pl": 0})
    for s in sp.scorers:
        if s["edge"] < 5:
            continue
        mid_s = next((p["id"] for p in sp.preds if p["home"] + " - " + p["away"] == s["match"]), None)
        if already(mid_s, s["player"], "buteur"):
            continue
        cfs = conf.get(s["match"])
        if cfs is not None and cfs < conf_min:   # gate de confiance du desk
            continue
        stake = round(min(PB["bankroll"] * 0.015, budget), 2)
        if stake < 0.5:
            continue
        budget -= stake
        new_bets.append({"id": len(PB["bets"]) + len(new_bets) + 1, "placed": GEN_DATE, "mid": mid_s,
                         "match": s["match"], "market": "buteur", "sel": s["player"], "cote": s["cote"],
                         "stake": stake, "edge": s["edge"], "status": "pending", "pl": 0})
    PB["bets"].extend(new_bets)
    json.dump(PB, open(pb_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    bt["clv"] = aggregate_clv(PB["bets"])
    app_data["paper"] = PB

    with open(os.path.join(ROOT, "app", "app_data.js"), "w", encoding="utf-8") as f:
        f.write("const APP_DATA = " + json.dumps(app_data, ensure_ascii=False) + ";")

    n_pending = sum(1 for b in PB["bets"] if b["status"] == "pending")
    print("=== %s | sport=%s | %s ===" % (VERSION, sp.key, GEN_DATE))
    print("Matchs a venir: %d | value 1N2: %d | anomalies: %d | buteurs: %d"
          % (len(sp.preds), len(sp.values), len(sp.anomalies), len(sp.scorers)))
    print("Backtest [%s] n=%s: Brier modele %s vs uniforme %s | hit %s%% | CLV %s"
          % (bt["source"], bt["n"], bt["brier_model"], bt["brier_uniform"], bt["hit_rate"],
             (str(bt["clv"]["clv_avg"]) + "%") if bt["clv"]["n"] else "n/d"))
    print("Tickets: " + " ".join("%s=%d" % (k, len(batch.get(k, []))) for k in ("banker", "value", "jackpot", "fun")))
    print("Bankroll agent: %.2f EUR | ouverts: %d | nouveaux: %d" % (PB["bankroll"], n_pending, len(new_bets)))
    print("OK -> output/*.csv + app/app_data.js + data/proba_log.json")


if __name__ == "__main__":
    main()
