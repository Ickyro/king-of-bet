# -*- coding: utf-8 -*-
"""
sports/nfl.py — plugin NFL (football américain). Sport à points, fort écart-type.
Modèle identique au basket (loi normale) avec paramètres NFL :
  - marge ~ écart de ratings + avantage terrain (~2 pts), σ marge ~13.5
  - total points ~ somme des attaques/défenses, σ total ~10
Marchés : Moneyline (is_core) + Total O/U + Handicap (spread). Réutilise engine.core.
Données démo : data_nfl/ (ppg/oppg). NB : juin = intersaison NFL → données illustratives.
"""
import os
import json
import math

from engine import core
from engine.sport import Sport, Event, register

CALIB = {"HOME_ADV": 2.0, "SIGMA_MARGIN": 13.5, "SIGMA_TOTAL": 10.0,
         "ALPHA": 0.35, "EDGE_MIN": 0.03, "EDGE_MAX": 0.15}


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


@register("nfl")
class NFLSport(Sport):
    key = "nfl"
    name = "NFL"
    value_markets = ("Moneyline",)

    def __init__(self, root, data_dir="data_nfl", calib=None):
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
            hp = (th.get("ppg", 22) + ta.get("oppg", 22)) / 2 + ha
            ap = (ta.get("ppg", 22) + th.get("oppg", 22)) / 2 - ha
            margin, total = hp - ap, hp + ap
            pwin_h = _ncdf(margin / c["SIGMA_MARGIN"]); pwin_a = 1 - pwin_h
            odds = m.get("odds") or {}
            ev = Event(m["id"], m["date"], m["away"] + " @ " + m["home"], m.get("competition", "NFL"), "nfl",
                       model={"pwin_home": round(pwin_h * 100, 1), "pwin_away": round(pwin_a * 100, 1),
                              "margin": round(margin, 1), "total": round(total, 1)}, market=odds or None)
            sels = []
            has_ml = bool(odds.get("ml_home") and odds.get("ml_away"))
            mk = core.devig_power([odds["ml_home"], odds["ml_away"]]) if has_ml else None
            for idx, (pm, who) in enumerate(((pwin_h, m["home"]), (pwin_a, m["away"]))):
                if has_ml:
                    co = odds["ml_home"] if idx == 0 else odds["ml_away"]
                    pf = core.blend(pm, mk[idx], co, c["ALPHA"]); est = bool(odds.get("est"))
                else:
                    co = round(1 / max(pm, 0.01), 2); pf = pm; est = True
                ed = core.edge(pf, co)
                sels.append({"event_id": m["id"], "group_id": m["id"], "date": m["date"], "sport": "nfl",
                             "competition": m.get("competition", "NFL"), "market": "Moneyline", "is_core": True,
                             "sel": who, "label": "%s gagne (%s @ %s)" % (who, m["away"], m["home"]),
                             "cote": co, "p": pf, "p_model": pm, "p_market": (mk[idx] if has_ml else None),
                             "edge": ed, "est": est, "team": who, "public": False})
                if has_ml and not est and c["EDGE_MIN"] < ed <= c["EDGE_MAX"] and pf >= 0.15:
                    self.values.append({"date": m["date"], "match": ev.label, "sel": who,
                                        "cote": co, "p_fin": pf * 100, "edge": ed * 100})
            tl = odds.get("total_line")
            if tl and odds.get("over"):
                pov = 1 - _ncdf((tl - total) / c["SIGMA_TOTAL"])
                for nm, co, pp in (("Over", odds["over"], pov), ("Under", odds.get("under"), 1 - pov)):
                    if co:
                        sels.append({"event_id": m["id"], "group_id": m["id"], "date": m["date"], "sport": "nfl",
                                     "competition": m.get("competition", "NFL"), "market": "Total", "is_core": False,
                                     "sel": "%s %s" % (nm, tl), "label": "%s %s pts (%s @ %s)" % (nm, tl, m["away"], m["home"]),
                                     "cote": co, "p": pp, "p_model": pp, "p_market": None,
                                     "edge": core.edge(pp, co), "est": bool(odds.get("est")), "team": None, "public": False})
            sp_line = odds.get("spread_home")  # ex -3.5 (home favori) ; cote spread_odds (memes 2 cotes)
            if sp_line is not None and odds.get("spread_odds"):
                pcov_h = 1 - _ncdf((-sp_line - margin) / c["SIGMA_MARGIN"])  # home couvre -sp si marge > -sp
                for who, line, pp in ((m["home"], sp_line, pcov_h), (m["away"], -sp_line, 1 - pcov_h)):
                    sels.append({"event_id": m["id"], "group_id": m["id"], "date": m["date"], "sport": "nfl",
                                 "competition": m.get("competition", "NFL"), "market": "Handicap", "is_core": False,
                                 "sel": "%s %+g" % (who, line), "label": "%s %+g (%s @ %s)" % (who, line, m["away"], m["home"]),
                                 "cote": odds["spread_odds"], "p": pp, "p_model": pp, "p_market": None,
                                 "edge": core.edge(pp, odds["spread_odds"]), "est": bool(odds.get("est")),
                                 "team": who, "public": False})
            ev.selections = sels
            self.events.append(ev)
            self.preds.append({"id": m["id"], "date": m["date"], "competition": m.get("competition", "NFL"),
                               "home": m["home"], "away": m["away"],
                               "pwin_home": round(pwin_h * 100, 1), "pwin_away": round(pwin_a * 100, 1),
                               "margin": round(margin, 1), "total": round(total, 1),
                               "fh": round(1 / pwin_h, 2), "fa": round(1 / pwin_a, 2), "mkt": (odds or None)})
        return self
