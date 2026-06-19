# -*- coding: utf-8 -*-
"""
sports/hockey.py — plugin NHL (hockey sur glace). Sport à BUTS faibles → Poisson
(comme le foot mais base ~6 buts, prolongation au lieu du nul).
- lambda par équipe = moyenne (attaque GF de l'une, défense GA encaissée de l'autre) + avantage glace
- matrice de scores Poisson (via engine.core), P(victoire) = victoire en temps réglementaire
  + part du nul réattribuée en prolongation selon la force (lambda)
- Total buts O/U via la matrice. Marchés : Moneyline (incl. prolong.) + Total.
Réutilise engine.core (score_matrix, devig, blend, Kelly) et engine.tickets.
"""
import os
import json

from engine import core
from engine.sport import Sport, Event, register

CALIB = {"HOME_ADV": 0.20, "RHO": -0.05, "MAXG": 12, "ALPHA": 0.35,
         "EDGE_MIN": 0.03, "EDGE_MAX": 0.15}


@register("nhl")
class HockeySport(Sport):
    key = "nhl"
    name = "NHL (hockey)"
    value_markets = ("Moneyline",)

    def __init__(self, root, data_dir="data_nhl", calib=None):
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
            lh = (th.get("gf", 3.0) + ta.get("ga", 3.0)) / 2 + ha
            la = (ta.get("gf", 3.0) + th.get("ga", 3.0)) / 2 - ha
            lh = max(1.5, lh); la = max(1.5, la)
            Mx = core.score_matrix(lh, la, c["RHO"], c["MAXG"])
            mk = core.matrix_markets(Mx)
            p1, pn, p2 = mk["p1"], mk["pn"], mk["p2"]
            # Moneyline incluant la prolongation : le nul (temps réglementaire) part en OT,
            # réattribué selon la force relative (lambda).
            share_h = lh / (lh + la)
            pwin_h = p1 + pn * share_h
            pwin_a = 1 - pwin_h
            # total buts
            maxg = c["MAXG"]
            ptot = [0.0] * (2 * maxg)
            for i in range(maxg):
                for j in range(maxg):
                    ptot[i + j] += Mx[i][j]
            odds = m.get("odds") or {}
            ev = Event(m["id"], m["date"], m["away"] + " @ " + m["home"], m.get("competition", "NHL"), "nhl",
                       model={"pwin_home": round(pwin_h * 100, 1), "pwin_away": round(pwin_a * 100, 1),
                              "total": round(lh + la, 2)}, market=odds or None)
            sels = []
            has_ml = bool(odds.get("ml_home") and odds.get("ml_away"))
            mkt = core.devig_power([odds["ml_home"], odds["ml_away"]]) if has_ml else None
            for idx, (pm, who) in enumerate(((pwin_h, m["home"]), (pwin_a, m["away"]))):
                if has_ml:
                    co = odds["ml_home"] if idx == 0 else odds["ml_away"]
                    pf = core.blend(pm, mkt[idx], co, c["ALPHA"]); est = bool(odds.get("est"))
                else:
                    co = round(1 / max(pm, 0.01), 2); pf = pm; est = True
                ed = core.edge(pf, co)
                sels.append({"event_id": m["id"], "group_id": m["id"], "date": m["date"], "sport": "nhl",
                             "competition": m.get("competition", "NHL"), "market": "Moneyline", "is_core": True,
                             "sel": who, "label": "%s gagne (%s @ %s)" % (who, m["away"], m["home"]),
                             "cote": co, "p": pf, "p_model": pm, "p_market": (mkt[idx] if has_ml else None),
                             "edge": ed, "est": est, "team": who, "public": False})
                if has_ml and not est and c["EDGE_MIN"] < ed <= c["EDGE_MAX"] and pf >= 0.15:
                    self.values.append({"date": m["date"], "match": ev.label, "sel": who,
                                        "cote": co, "p_fin": pf * 100, "edge": ed * 100})
            tl = odds.get("total_line")
            if tl and odds.get("over"):
                line = int(tl) if float(tl) == int(tl) else tl
                pov = sum(ptot[k] for k in range(len(ptot)) if k > tl)
                pun = sum(ptot[k] for k in range(len(ptot)) if k < tl)
                for nm, co, pp in (("Over", odds["over"], pov), ("Under", odds.get("under"), pun)):
                    if co:
                        sels.append({"event_id": m["id"], "group_id": m["id"], "date": m["date"], "sport": "nhl",
                                     "competition": m.get("competition", "NHL"), "market": "Total", "is_core": False,
                                     "sel": "%s %s" % (nm, tl), "label": "%s %s buts (%s @ %s)" % (nm, tl, m["away"], m["home"]),
                                     "cote": co, "p": pp, "p_model": pp, "p_market": None,
                                     "edge": core.edge(pp, co), "est": bool(odds.get("est")), "team": None, "public": False})
            ev.selections = sels
            self.events.append(ev)
            self.preds.append({"id": m["id"], "date": m["date"], "competition": m.get("competition", "NHL"),
                               "home": m["home"], "away": m["away"],
                               "pwin_home": round(pwin_h * 100, 1), "pwin_away": round(pwin_a * 100, 1),
                               "total": round(lh + la, 2), "margin": round(lh - la, 2),
                               "fh": round(1 / pwin_h, 2), "fa": round(1 / pwin_a, 2), "mkt": (odds or None)})
        return self
