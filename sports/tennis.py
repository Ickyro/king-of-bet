# -*- coding: utf-8 -*-
"""
sports/tennis.py — plugin TENNIS (marche a 2 issues) pour le moteur generique.

Demonstration que l'architecture multi-sports tient : un sport totalement
different du football (pas de buts, pas de nul, Elo par surface) reutilise
TEL QUEL engine/core.py (Elo, de-vig, blend, Kelly) et engine/tickets.py
(generateur multi-profils). Seule la logique de probabilite est specifique.

Donnees : data_tennis/players.json (Elo par surface) + matches.json (cotes).
"""
import json
import os

from engine import core
from engine.sport import Sport, Event, register

CALIB = {
    "ALPHA": 0.35,        # blend 35% modele / 65% marche (marche tennis tres sharp)
    "EDGE_MIN": 0.03, "EDGE_MAX": 0.15,
    "KFRAC": 0.25, "KCAP": 0.02,
    "ELO_DEFAULT": 1900,
}


@register("tennis")
class TennisSport(Sport):
    key = "tennis"
    name = "Tennis"
    value_markets = ("Vainqueur",)

    def __init__(self, root, data_dir="data_tennis", calib=None):
        super().__init__(root)
        self.data_dir = data_dir
        self.c = dict(CALIB)
        if calib:
            self.c.update(calib)
        self.preds = []
        self.values = []

    def _p(self, name):
        return os.path.join(self.root, self.data_dir, name)

    def _elo(self, player, surface):
        pl = self.P.get(player, {})
        e = pl.get("elo", {})
        return e.get(surface, pl.get("elo_base", self.c["ELO_DEFAULT"]))

    def load(self):
        c = self.c
        self.P = json.load(open(self._p("players.json"), encoding="utf-8"))
        self.M = json.load(open(self._p("matches.json"), encoding="utf-8"))
        for m in self.M:
            surf = m.get("surface", "hard")
            e1, e2 = self._elo(m["p1"], surf), self._elo(m["p2"], surf)
            pm1 = core.elo_we(e1 - e2)
            pm2 = 1 - pm1
            odds = m.get("odds") or {}
            ev = Event(m["id"], m["date"], m["p1"] + " vs " + m["p2"],
                       m.get("tournament", ""), "tennis",
                       model={"p1": round(pm1 * 100, 1), "p2": round(pm2 * 100, 1), "surface": surf},
                       market=odds or None)
            sels = []
            has_odds = bool(odds.get("p1") and odds.get("p2"))
            if has_odds:
                mk = core.devig_power([odds["p1"], odds["p2"]])
            for idx, (pm, who, mkt_key) in enumerate(((pm1, m["p1"], 0), (pm2, m["p2"], 1))):
                if has_odds:
                    co = odds["p1"] if idx == 0 else odds["p2"]
                    pmkt = mk[mkt_key]
                    pf = core.blend(pm, pmkt, co, c["ALPHA"])
                    est = bool(odds.get("est"))
                else:
                    co = round(1 / max(pm, 0.01), 2)   # cote juste si pas de marche
                    pmkt = None; pf = pm; est = True
                ed = core.edge(pf, co)
                leg = {
                    "event_id": m["id"], "group_id": m["id"], "date": m["date"],
                    "sport": "tennis", "competition": m.get("tournament", ""),
                    "market": "Vainqueur", "is_core": True, "sel": who,
                    "label": "%s gagne (%s vs %s)" % (who, m["p1"], m["p2"]),
                    "cote": co, "p": pf, "p_model": pm, "p_market": pmkt,
                    "edge": ed, "est": est, "team": who, "public": False,
                }
                sels.append(leg)
                if has_odds and not est and c["EDGE_MIN"] < ed <= c["EDGE_MAX"] and pf >= 0.15:
                    self.values.append({"date": m["date"], "match": ev.label, "sel": who,
                                        "cote": co, "p_fin": pf * 100, "edge": ed * 100})
            ev.selections = sels
            self.events.append(ev)
            self.preds.append({
                "id": m["id"], "date": m["date"], "tournament": m.get("tournament", ""),
                "surface": surf, "p1_name": m["p1"], "p2_name": m["p2"],
                "p1": round(pm1 * 100, 1), "p2": round(pm2 * 100, 1),
                "f1": round(1 / pm1, 2), "f2": round(1 / pm2, 2),
                "mkt": (odds or None),
            })
        return self
