# -*- coding: utf-8 -*-
"""
Worldcup King of Bet — moteur generique multi-sports (v3.0)
============================================================
Ce package contient toute la math SPORT-AGNOSTIQUE :
  - core.py    : probabilites, de-vig, blend marche, Kelly, value, Monte-Carlo
  - sport.py   : interface abstraite `Sport` + registre des sports
  - tickets.py : generateur de tickets multi-profils (Banker / Value / Jackpot / Fun)

Un sport (football, tennis, basket...) implemente la classe `Sport` et fournit
ses probabilites par evenement. Le reste du pipeline (value, tickets, paper
trading, export app) est commun a tous les sports.
"""
__version__ = "3.0"
