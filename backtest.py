# -*- coding: utf-8 -*-
"""
backtest.py — validation out-of-sample de la calibration.

- run_backtest        : approximation Elo-core pre-match (toujours dispo, repli).
- run_backtest_logged : Brier REEL a partir des probas pre-match snapshotees
                        (data/proba_log.json, alimente par run_worldcup.py).
- aggregate_clv       : CLV moyen du portefeuille (champ 'clv' des paris regles).
"""
from engine import core


def run_backtest(teams, played, calib):
    c = calib
    elo = {n: t["elo"] + t.get("host_bonus", 0) + t.get("adj", 0) for n, t in teams.items()}
    rows = []
    bs_model = 0.0
    bs_unif = 0.0
    for p in sorted(played, key=lambda x: x["date"]):
        h, a = p["home"], p["away"]; sh, sa = p["score"]
        if h not in elo or a not in elo:
            continue
        dr = elo[h] - elo[a]
        m_elo = max(-c["MARGIN_CAP"], min(c["MARGIN_CAP"], dr / c["ELO_PER_GOAL"]))
        Tt = c["BASE"]
        lh, la = (Tt + m_elo) / 2, (Tt - m_elo) / 2
        lh = max(0.15, lh); la = max(0.15, la)
        Mx = core.score_matrix(lh, la, c["RHO"], c["MAXG"])
        mk = core.matrix_markets(Mx)
        p1, pn, p2 = mk["p1"], mk["pn"], mk["p2"]
        o1 = 1.0 if sh > sa else 0.0
        on = 1.0 if sh == sa else 0.0
        o2 = 1.0 if sa > sh else 0.0
        bs_model += (p1 - o1) ** 2 + (pn - on) ** 2 + (p2 - o2) ** 2
        u = 1.0 / 3
        bs_unif += (u - o1) ** 2 + (u - on) ** 2 + (u - o2) ** 2
        outc = "1" if o1 else ("N" if on else "2")
        pick = "1" if max(p1, pn, p2) == p1 else ("N" if max(p1, pn, p2) == pn else "2")
        rows.append({"date": p["date"], "match": "%s %d-%d %s" % (h, sh, sa, a),
                     "p1": round(p1 * 100), "pn": round(pn * 100), "p2": round(p2 * 100),
                     "result": outc, "pick": pick, "hit": pick == outc})
        W = 1.0 if sh > sa else (0.0 if sh < sa else 0.5)
        nd = abs(sh - sa)
        G = 1.0 if nd <= 1 else (1.5 if nd == 2 else (11 + nd) / 8.0)
        delta = core.elo_delta(dr, W, k=c["K_ELO"], g=G)
        elo[h] += delta; elo[a] -= delta
    n = len(rows)
    return {
        "n": n,
        "brier_model": round(bs_model / n, 4) if n else None,
        "brier_uniform": round(bs_unif / n, 4) if n else None,
        "hit_rate": round(sum(r["hit"] for r in rows) / n * 100, 1) if n else None,
        "detail": rows,
        "note": "Pre-match Elo-core, hors marche. n faible = indicatif (forte variance)."
    }


def run_backtest_logged(played, proba_log):
    """Brier REEL : probas pre-match reellement snapshotees pour les matchs joues."""
    rows = []
    bs_model = 0.0
    bs_unif = 0.0
    for p in sorted(played, key=lambda x: x["date"]):
        key = p["home"] + " - " + p["away"]
        lg = proba_log.get(key)
        if not lg:
            continue
        sh, sa = p["score"]
        p1, pn, p2 = lg["p1"] / 100.0, lg["pn"] / 100.0, lg["p2"] / 100.0
        o1 = 1.0 if sh > sa else 0.0
        on = 1.0 if sh == sa else 0.0
        o2 = 1.0 if sa > sh else 0.0
        bs_model += (p1 - o1) ** 2 + (pn - on) ** 2 + (p2 - o2) ** 2
        u = 1.0 / 3
        bs_unif += (u - o1) ** 2 + (u - on) ** 2 + (u - o2) ** 2
        outc = "1" if o1 else ("N" if on else "2")
        mx = max(p1, pn, p2)
        pick = "1" if mx == p1 else ("N" if mx == pn else "2")
        rows.append({"date": lg.get("date", p["date"]),
                     "match": "%s %d-%d %s" % (p["home"], sh, sa, p["away"]),
                     "p1": round(p1 * 100), "pn": round(pn * 100), "p2": round(p2 * 100),
                     "result": outc, "pick": pick, "hit": pick == outc})
    n = len(rows)
    return {
        "n": n,
        "brier_model": round(bs_model / n, 4) if n else None,
        "brier_uniform": round(bs_unif / n, 4) if n else None,
        "hit_rate": round(sum(r["hit"] for r in rows) / n * 100, 1) if n else None,
        "detail": rows,
        "note": "Brier REEL (probas pre-match snapshotees). Le juge de paix du modele."
    }


def aggregate_clv(paper_bets):
    """CLV moyen du portefeuille a partir des paris regles ayant un champ 'clv'."""
    vals = [b["clv"] for b in paper_bets if isinstance(b.get("clv"), (int, float))]
    if not vals:
        return {"n": 0, "clv_avg": None}
    return {"n": len(vals), "clv_avg": round(sum(vals) / len(vals) * 100, 2)}
