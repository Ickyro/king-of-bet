# -*- coding: utf-8 -*-
"""
sports/basketball.py — plugin BASKET / NBA pour le moteur generique.

Sport SANS nul, a fort total : on modelise les POINTS (pas des buts Poisson).
- points attendus par equipe = moyenne (attaque de l'une, defense encaissee de l'autre) + avantage terrain
- P(victoire) = loi normale sur la marge (ecart-type ~12 pts)
- O/U total = loi normale sur le total (ecart-type ~17 pts)
Reutilise TEL QUEL engine.core (de-vig 2 voies, blend, Kelly) et engine.tickets.

Donnees : data_basketball/teams.json (ppg/oppg) + matches.json (cotes ml/total).
"""
import os
import json
import math

from engine import core
from engine.sport import Sport, Event, register

CALIB = {"HOME_ADV": 2.8, "SIGMA_MARGIN": 12.0, "SIGMA_TOTAL": 17.0,
         "ALPHA": 0.35, "EDGE_MIN": 0.03, "EDGE_MAX": 0.15}


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


@register("basketball")
class BasketballSport(Sport):
    key = "basketball"
    name = "Basket (NBA)"
    value_markets = ("Moneyline",)

    def __init__(self, root, data_dir="data_basketball", calib=None):
        super().__init__(root)
        self.data_dir = data_dir
        self.c = dict(CALIB)
        if calib:
            self.c.update(calib)
        self.preds = []
        self.values = []

    def _p(self, name):
        return os.path.join(self.root, self.data_dir, name)

    def load(self):
        c = self.c
        self.T = json.load(open(self._p("teams.json"), encoding="utf-8"))
        self.M = json.load(open(self._p("matches.json"), encoding="utf-8"))
        ha = c["HOME_ADV"] / 2.0
        for m in self.M:
            th, ta = self.T.get(m["home"], {}), self.T.get(m["away"], {})
            hp = (th.get("ppg", 112) + ta.get("oppg", 112)) / 2 + ha
            ap = (ta.get("ppg", 112) + th.get("oppg", 112)) / 2 - ha
            margin = hp - ap
            total = hp + ap
            pwin_h = _ncdf(margin / c["SIGMA_MARGIN"])
            pwin_a = 1 - pwin_h
            odds = m.get("odds") or {}
            ev = Event(m["id"], m["date"], m["home"] + " @ " + m["away"], m.get("competition", "NBA"), "basketball",
                       model={"pwin_home": round(pwin_h * 100, 1), "pwin_away": round(pwin_a * 100, 1),
                              "margin": round(margin, 1), "total": round(total, 1)}, market=odds or None)
            sels = []
            has_ml = bool(odds.get("ml_home") and odds.get("ml_away"))
            # Line shopping : on PARIE le meilleur prix (odds.ml_*) mais on DE-VIGUE
            # sur la ligne "sharp" (Pinnacle) si dispo → l'edge reflète best-price vs sharp.
            _ref = odds.get("sharp") or {}
            if not (_ref.get("ml_home") and _ref.get("ml_away")):
                _ref = odds
            mk = core.devig_power([_ref["ml_home"], _ref["ml_away"]]) if has_ml else None
            for idx, (pm, who) in enumerate(((pwin_h, m["home"]), (pwin_a, m["away"]))):
                if has_ml:
                    co = odds["ml_home"] if idx == 0 else odds["ml_away"]
                    pf = core.blend(pm, mk[idx], co, c["ALPHA"]); est = bool(odds.get("est"))
                else:
                    co = round(1 / max(pm, 0.01), 2); pf = pm; est = True
                ed = core.edge(pf, co)
                leg = {"event_id": m["id"], "group_id": m["id"], "date": m["date"], "sport": "basketball",
                       "competition": m.get("competition", "NBA"), "market": "Moneyline", "is_core": True,
                       "sel": who, "label": "%s gagne (%s @ %s)" % (who, m["home"], m["away"]),
                       "cote": co, "p": pf, "p_model": pm, "p_market": (mk[idx] if has_ml else None),
                       "edge": ed, "est": est, "team": who, "public": False}
                sels.append(leg)
                if has_ml and not est and c["EDGE_MIN"] < ed <= c["EDGE_MAX"] and pf >= 0.15:
                    self.values.append({"date": m["date"], "match": ev.label, "sel": who,
                                        "cote": co, "p_fin": pf * 100, "edge": ed * 100})
            # Total points O/U
            tl = odds.get("total_line")
            if tl and odds.get("over"):
                pov = 1 - _ncdf((tl - total) / c["SIGMA_TOTAL"])
                for nm, co, pp in (("Over", odds["over"], pov), ("Under", odds.get("under"), 1 - pov)):
                    if not co:
                        continue
                    sels.append({"event_id": m["id"], "group_id": m["id"], "date": m["date"], "sport": "basketball",
                                 "competition": m.get("competition", "NBA"), "market": "Total", "is_core": False,
                                 "sel": "%s %s" % (nm, tl), "label": "%s %s pts (%s @ %s)" % (nm, tl, m["home"], m["away"]),
                                 "cote": co, "p": pp, "p_model": pp, "p_market": None,
                                 "edge": core.edge(pp, co), "est": bool(odds.get("est")), "team": None, "public": False})
            ev.selections = sels
            self.events.append(ev)
            self.preds.append({"id": m["id"], "date": m["date"], "competition": m.get("competition", "NBA"),
                               "home": m["home"], "away": m["away"],
                               "pwin_home": round(pwin_h * 100, 1), "pwin_away": round(pwin_a * 100, 1),
                               "margin": round(margin, 1), "total": round(total, 1),
                               "fh": round(1 / pwin_h, 2), "fa": round(1 / pwin_a, 2), "mkt": (odds or None)})
        return self
