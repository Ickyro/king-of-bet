# -*- coding: utf-8 -*-
"""
run_sport.py — runner GENERIQUE multi-sports (hors World Cup qui a son orchestrateur dedie).

Demonstration : le MEME moteur de tickets (engine/tickets.py) tourne sur n'importe
quel sport implementant l'interface Sport, sans une ligne de code specifique ici.

Usage :  python run_sport.py tennis
         python run_sport.py <sport_key>
"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from engine import sport as sport_mod, tickets
import sports  # noqa: F401

KEY = sys.argv[1] if len(sys.argv) > 1 else "tennis"


def main():
    sp = sport_mod.get_sport(KEY, ROOT)
    sp.load()
    legs = sp.all_selections()          # selections normalisees, communes a tous les sports
    batch = tickets.build_tickets(legs, {"bankroll": 100.0, "n_variants": 3})

    out_dir = os.path.join(ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)
    payload = {"sport": sp.key, "sport_name": sp.name,
               "predictions": getattr(sp, "preds", []),
               "values": getattr(sp, "values", []),
               "ticket_batch": batch, "ticket_pool": legs}
    with open(os.path.join(out_dir, "%s_app_data.json" % sp.key), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print("=== %s | %d evenements | %d selections ==="
          % (sp.name, len(sp.events), len(legs)))
    for p in getattr(sp, "preds", [])[:12]:
        if sp.key == "tennis":
            print("  %s [%s] %-10s %2d%% vs %-10s %2d%%"
                  % (p["date"], p["surface"], p["p1_name"], round(p["p1"]),
                     p["p2_name"], round(p["p2"])))
    if getattr(sp, "values", []):
        print("--- VALUE (%s) ---" % sp.value_markets[0])
        for v in sorted(sp.values, key=lambda x: -x["edge"]):
            print("  %s [%s] cote %.2f | p %.0f%% | edge +%.1f%%"
                  % (v["match"], v["sel"], v["cote"], v["p_fin"], v["edge"]))
    print("--- TICKETS (memes profils que le football) ---")
    for prof in ("banker", "value", "jackpot", "fun"):
        for t in batch.get(prof, []):
            print("  [%s] %-20s cote %.2f | p %.1f%% | EV %+.1f%% | mise %.2f%% | %s"
                  % (prof, t["title"], t["cote"], t["p"], t["ev"], t["stake_pct"], t["risk"]))
            for l in t["legs"]:
                print("        - %s @ %.2f (%.0f%%)" % (l["label"], l["cote"], l["p"]))
    print("OK -> output/%s_app_data.json" % sp.key)


if __name__ == "__main__":
    main()
