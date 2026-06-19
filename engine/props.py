# -*- coding: utf-8 -*-
"""
engine/props.py — modèle de PLAYER PROPS (points joueurs), sport-agnostique.

Marché très efficient et fortement vigé → on (1) dé-vigue la ligne Over/Under pour la
proba "juste" du marché, (2) si une projection joueur existe (PPG réel dans players.json),
on calcule une proba modèle (loi normale autour du PPG) et on BLEND vers le marché
(poids modèle faible), puis l'edge sur le meilleur côté. Sans projection → scanner seul
(on n'invente jamais un PPG : pas de projection = pas d'edge).
"""
import math


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _devig2(a, b):
    ia, ib = 1.0 / a, 1.0 / b
    s = ia + ib
    return ia / s, ib / s


def prop_sigma(ppg):
    # écart-type approx des points d'une joueuse WNBA sur un match (croît avec le volume)
    return max(3.5, 0.34 * ppg + 2.0)


def prop_edges(props_db, players, alpha=0.35, edge_min=0.04, edge_max=0.20):
    games = []
    for gk, g in props_db.items():
        if str(gk).startswith("_"):
            continue
        rows = []
        for p in g.get("players", []):
            ov, un, line = p.get("over"), p.get("under"), p.get("line")
            if not (ov and un and line is not None):
                continue
            mko, _mku = _devig2(ov, un)  # proba marché P(Over)
            row = {"player": p["player"], "line": line, "over": ov, "under": un,
                   "mkt_over": round(mko * 100, 1), "model_over": None,
                   "edge": None, "side": None, "cote": None}
            ppg = players.get(p["player"])
            if ppg is not None:
                sig = prop_sigma(ppg)
                pov = 1 - _ncdf((line - ppg) / sig)
                pf = alpha * pov + (1 - alpha) * mko
                eo, eu = pf * ov - 1, (1 - pf) * un - 1
                row["model_over"] = round(pf * 100, 1)
                if eo >= eu and edge_min < eo <= edge_max:
                    row.update({"edge": round(eo * 100, 1), "side": "Over", "cote": ov})
                elif edge_min < eu <= edge_max:
                    row.update({"edge": round(eu * 100, 1), "side": "Under", "cote": un})
            rows.append(row)
        if rows:
            games.append({"game": gk, "home": g.get("home"), "away": g.get("away"), "rows": rows})
    return games
