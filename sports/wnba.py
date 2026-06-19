# -*- coding: utf-8 -*-
"""
sports/wnba.py — plugin WNBA (basket féminin).

Réutilise INTÉGRALEMENT le moteur points de BasketballSport (loi normale sur la
marge / le total + de-vig 2 voies + blend marché + Kelly via engine.tickets) ;
seule la calibration change : la WNBA marque moins (~80-90 pts/équipe contre ~112
en NBA) et les matchs sont un peu plus serrés → SIGMA plus faibles.

Données : data_wnba/teams.json (ppg/oppg réels 2026) + matches.json (cotes
Pinnacle réelles via The Odds API, sport_key basketball_wnba).
"""
from sports.basketball import BasketballSport
from engine.sport import register

# Calibration spécifique WNBA (scoring plus bas, écarts plus resserrés que la NBA)
WNBA_CALIB = {"HOME_ADV": 2.8, "SIGMA_MARGIN": 11.0, "SIGMA_TOTAL": 15.0,
              "ALPHA": 0.35, "EDGE_MIN": 0.03, "EDGE_MAX": 0.15}


@register("wnba")
class WNBASport(BasketballSport):
    key = "wnba"
    name = "WNBA (basket fém.)"
    value_markets = ("Moneyline",)

    def __init__(self, root, data_dir="data_wnba", calib=None):
        merged = dict(WNBA_CALIB)
        if calib:
            merged.update(calib)
        super().__init__(root, data_dir=data_dir, calib=merged)
