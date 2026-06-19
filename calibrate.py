# -*- coding: utf-8 -*-
"""
calibrate.py — diagnostic de CALIBRATION du modèle (offline).

Joint les probas pré-match archivées (data/proba_log.json, snapshotées par le moteur)
avec les résultats réels (data/matches.json "played"), et calcule :
  - Brier multinomial du modèle vs baseline uniforme (1/3),
  - log-loss,
  - hit-rate (l'issue la + probable est-elle sortie ?),
  - COURBE DE FIABILITÉ : on regroupe toutes les probas d'issue prédites en tranches
    et on compare proba moyenne prédite vs fréquence empirique (diagonale = parfait).
Écrit data/calibration.json (consommé par le hub, onglet 📈 Perf).

Le même squelette sert aux sports à points (basket/wnba/nhl) dès qu'un historique de
résultats existe ; pour l'instant ils n'ont pas assez de matchs réglés → section "sports".
"""
import os
import json
import math

ROOT = os.path.dirname(os.path.abspath(__file__))


def _outcome(score):
    h, a = score[0], score[1]
    return "1" if h > a else ("2" if a > h else "N")


def reliability(points, nbins=5):
    """points = [(p_pred, hit01), ...] ; renvoie bins non vides."""
    bins = []
    for b in range(nbins):
        lo, hi = b / nbins, (b + 1) / nbins
        sel = [(p, h) for p, h in points if (lo <= p < hi or (b == nbins - 1 and p == 1.0))]
        if not sel:
            continue
        pp = sum(p for p, _ in sel) / len(sel)
        pe = sum(h for _, h in sel) / len(sel)
        bins.append({"lo": round(lo, 2), "hi": round(hi, 2),
                     "p_pred": round(pp * 100, 1), "p_emp": round(pe * 100, 1), "n": len(sel)})
    return bins


def main():
    plog_p = os.path.join(ROOT, "data", "proba_log.json")
    mp = os.path.join(ROOT, "data", "matches.json")
    out = {"n": 0, "brier_model": None, "brier_uniform": None, "logloss": None,
           "hit_rate": None, "reliability": [], "note": "WC (foot) — proba_log ∩ résultats"}
    if not (os.path.exists(plog_p) and os.path.exists(mp)):
        json.dump(out, open(os.path.join(ROOT, "data", "calibration.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("calibration: sources absentes"); return
    PL = json.load(open(plog_p, encoding="utf-8"))
    M = json.load(open(mp, encoding="utf-8"))
    played = M.get("played", []) if isinstance(M, dict) else []
    rel_pts = []           # (p_pred_issue, hit)
    bm = bu = ll = 0.0
    hits = 0
    n = 0
    for m in played:
        if "score" not in m:
            continue
        k = "%s - %s" % (m.get("home"), m.get("away"))
        pe = PL.get(k)
        if not pe:
            continue
        probs = {"1": (pe.get("p1") or 0) / 100.0, "N": (pe.get("pn") or 0) / 100.0,
                 "2": (pe.get("p2") or 0) / 100.0}
        s = sum(probs.values()) or 1.0
        probs = {k2: v / s for k2, v in probs.items()}
        act = _outcome(m["score"])
        n += 1
        # Brier multinomial + log-loss + reliability
        for o in ("1", "N", "2"):
            ind = 1.0 if o == act else 0.0
            bm += (probs[o] - ind) ** 2
            bu += (1 / 3.0 - ind) ** 2
            rel_pts.append((probs[o], ind))
        ll += -math.log(max(probs[act], 1e-9))
        if max(probs, key=probs.get) == act:
            hits += 1
    if n:
        out.update({"n": n, "brier_model": round(bm / n, 4), "brier_uniform": round(bu / n, 4),
                    "logloss": round(ll / n, 4), "hit_rate": round(hits / n * 100, 1),
                    "reliability": reliability(rel_pts, 5)})
    json.dump(out, open(os.path.join(ROOT, "data", "calibration.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("calibration: n=%d Brier=%s (uniforme %s) logloss=%s hit=%s%% bins=%d"
          % (out["n"], out["brier_model"], out["brier_uniform"], out["logloss"],
             out["hit_rate"], len(out["reliability"])))


if __name__ == "__main__":
    main()
