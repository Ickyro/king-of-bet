# -*- coding: utf-8 -*-
"""
engine/sport.py — contrat que chaque sport doit remplir + registre.

Pour ajouter un sport (tennis, NBA, L1...) il suffit de creer une sous-classe de
`Sport` qui sait :
  1. charger ses donnees (events a venir, cotes, eventuels 'props'/buteurs),
  2. produire pour chaque event un dict de probabilites modele (1N2, totaux...),
  3. (optionnel) simuler une competition (Monte-Carlo classement/qualif),
  4. (optionnel) fournir des marches 'props' (buteurs, points joueurs...).

Le pipeline commun (value, blend, tickets, paper trading, export app) ne connait
QUE cette interface : il est donc identique pour tous les sports.
"""
from engine import core

_REGISTRY = {}


def register(key):
    """Decorateur d'enregistrement d'un sport : @register('football')."""
    def deco(cls):
        _REGISTRY[key] = cls
        cls.key = key
        return cls
    return deco


def get_sport(key, root):
    if key not in _REGISTRY:
        raise KeyError("Sport inconnu '%s'. Disponibles : %s"
                       % (key, ", ".join(_REGISTRY) or "(aucun)"))
    return _REGISTRY[key](root)


def available():
    return sorted(_REGISTRY)


class Event:
    """Un evenement parie-able, normalise pour tous les sports.
    `selections` est une liste de dicts :
      {market, sel, label, cote, p_model, p_market, p_final, edge, est, group_id, meta}
    `group_id` sert l'anti-correlation : 1 leg max par group_id dans un ticket.
    """
    def __init__(self, eid, date, label, competition, sport,
                 model=None, market=None, meta=None):
        self.id = eid
        self.date = date
        self.label = label            # "France - Bresil"
        self.competition = competition
        self.sport = sport
        self.model = model or {}      # probas modele brutes (p1/pn/p2, o25, btts...)
        self.market = market          # cotes book (peut etre None)
        self.meta = meta or {}        # infos sport-specifiques (xG, profils...)
        self.selections = []          # rempli par build_selections()


class Sport:
    """Interface abstraite. Les sous-classes redefinissent les hooks ci-dessous."""
    key = "abstract"
    name = "Sport abstrait"
    # marches consideres "value" pour le paper trading (les autres = info/fun)
    value_markets = ("1N2",)

    def __init__(self, root):
        self.root = root
        self.events = []      # list[Event]
        self.props = []       # marches joueurs (buteurs...) — optionnel

    # --- a implementer par chaque sport -------------------------------------
    def load(self):
        """Charge donnees + cotes ; remplit self.events (probas modele) et self.props."""
        raise NotImplementedError

    def simulate(self, ns=20000):
        """Optionnel : Monte-Carlo competition. Retourne une structure exportable
        ou None si non pertinent pour ce sport."""
        return None

    # --- commun : recapitule toutes les selections pari-ables ---------------
    def all_selections(self):
        out = []
        for ev in self.events:
            out.extend(ev.selections)
        out.extend(self.props)
        return out
