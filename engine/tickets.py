# -*- coding: utf-8 -*-
"""
engine/tickets.py — GENERATEUR DE TICKETS MULTI-PROFILS (sport-agnostique).

Prend un pool de selections normalisees (legs) et produit PLUSIEURS tickets par
generation, repartis sur 4 profils :
  - banker  : securite, proba maximale (single -> duo -> trio)
  - value   : meilleure esperance de gain (edge>0), risque modere
  - jackpot : gros gain, cotes cibles elevees (bandes 10 / 25 / 50)
  - fun     : buteurs & marches alternatifs (O/U, BTTS, score exact)

Contraintes : 1 leg max par `group_id` (anti-correlation), diversite entre
variantes, staking Kelly plafonne par profil, EV/payout/risque calcules.

Format d'un leg attendu :
  {event_id, group_id, date, sport, competition, market, sel, label,
   cote, p (=p_final), p_model, p_market, edge, est, team, public}
"""
from engine import core

# marches "principaux" (resultat du match) communs aux sports — le reste = props
CORE_MARKETS = ("1N2", "Vainqueur", "Moneyline")

PROFILE_META = {
    "banker":  {"emoji": "🟢", "name": "Banker",  "cap": 0.05, "kfrac": 0.30},
    "value":   {"emoji": "🟡", "name": "Value",   "cap": 0.03, "kfrac": 0.25},
    "jackpot": {"emoji": "🟣", "name": "Jackpot",  "cap": 0.01, "kfrac": 0.15},
    "fun":     {"emoji": "🔴", "name": "Fun",      "cap": 0.015, "kfrac": 0.10},
}
DEFAULT_OPTS = {
    "profiles": ["banker", "value", "jackpot", "fun"],
    "n_variants": 3,            # nb de tickets vises par profil
    "max_legs": 4,
    "min_leg_odds": 1.12,
    "max_leg_odds": 12.0,
    "min_leg_prob": 0.12,
    "jackpot_bands": [10, 25, 50],
    "markets": None,            # None = tous ; sinon set de marches autorises
    "avoid_public": False,
    "public_teams": ("France", "Brazil", "England", "USA", "Mexico", "Argentina"),
    "must_team": None,          # impose une equipe/joueur dans chaque ticket
    "bankroll": 100.0,
    "exclude_est": False,       # exclure les cotes estimees
}


# ---------------------------------------------------------------------------
# Outils internes
# ---------------------------------------------------------------------------
def _risk(p):
    if p >= 0.65: return "Faible"
    if p >= 0.40: return "Modéré"
    if p >= 0.20: return "Élevé"
    return "Très élevé"


def _filter_pool(legs, o, *, value_only=False, props_only=False, exclude_props=False):
    out = []
    for l in legs:
        if l["cote"] < o["min_leg_odds"] or l["cote"] > o["max_leg_odds"]:
            continue
        if l["p"] < o["min_leg_prob"]:
            continue
        if o.get("exclude_est") and l.get("est"):
            continue
        if o.get("markets") and l["market"] not in o["markets"]:
            continue
        if o.get("avoid_public") and l.get("team") in o.get("public_teams", ()):
            continue
        is_prop = not l.get("is_core", l["market"] in CORE_MARKETS)
        if props_only and not is_prop:
            continue
        if exclude_props and is_prop:
            continue
        if value_only and l.get("edge", 0) <= 0:
            continue
        out.append(l)
    return out


def _search(pool, max_legs, objective, target=None, must_group=None, top=26):
    """Recherche du meilleur combo (1 leg/group_id) maximisant `objective`.
    Si `target` (cote mini), on n'accepte que les combos atteignant la cible.
    `must_group` force l'inclusion d'un leg de ce group_id (equipe imposee)."""
    pool = sorted(pool, key=lambda c: -objective([c]))[:top]
    best = [None]
    best_obj = [-1e18]
    best_any = [None]
    best_any_odds = [-1.0]

    def consider(s):
        if not s:
            return
        oc = core.combo_odds(s)
        if oc > best_any_odds[0]:
            best_any_odds[0] = oc
            best_any[0] = list(s)
        ok = (target is None) or (oc >= target)
        ob = objective(s)
        if ok and ob > best_obj[0]:
            best_obj[0] = ob
            best[0] = list(s)

    def rec(start, s, used):
        if s:
            consider(s)
        if len(s) >= max_legs:
            return
        for i in range(start, len(pool)):
            c = pool[i]
            if c["group_id"] in used:
                continue
            used.add(c["group_id"])
            s.append(c)
            rec(i + 1, s, used)
            s.pop()
            used.discard(c["group_id"])

    if must_group is not None:
        forced = [c for c in pool if c["group_id"] == must_group]
        if forced:
            seed = sorted(forced, key=lambda c: -objective([c]))[0]
            rec_pool = [c for c in pool if c["group_id"] != must_group]
            def rec2(start, s, used):
                consider(s)
                if len(s) >= max_legs:
                    return
                for i in range(start, len(rec_pool)):
                    c = rec_pool[i]
                    if c["group_id"] in used:
                        continue
                    used.add(c["group_id"]); s.append(c)
                    rec2(i + 1, s, used)
                    s.pop(); used.discard(c["group_id"])
            rec2(0, [seed], {seed["group_id"]})
            return best[0] or best_any[0]
    rec(0, [], set())
    return best[0] or best_any[0]


def _make_ticket(profile, title, legs, o, ev_floor_stake=True):
    if not legs:
        return None
    cote = round(core.combo_odds(legs), 2)
    p = core.combo_prob(legs)
    ev = core.combo_ev(legs)
    meta = PROFILE_META[profile]
    kel = core.kelly_fraction(p, cote)
    pct = min(meta["cap"], meta["kfrac"] * kel)
    if ev_floor_stake and profile in ("jackpot", "fun"):
        pct = max(pct, 0.005)        # mise plaisir minimale meme si EV<0
    if profile in ("banker", "value"):
        pct = max(pct, 0.005)
    bk = o.get("bankroll", 100.0)
    stake = round(bk * pct, 2)
    return {
        "profile": profile,
        "title": title,
        "legs": [{
            "label": l["label"], "cote": l["cote"], "p": round(l["p"] * 100, 1),
            "edge": round(l.get("edge", 0) * 100, 1), "market": l["market"],
            "date": l.get("date"), "est": bool(l.get("est")),
            "event_id": l.get("event_id"),
        } for l in legs],
        "cote": cote,
        "p": round(p * 100, 1),
        "ev": round(ev * 100, 1),
        "stake_pct": round(pct * 100, 2),
        "stake": stake,
        "payout": round(stake * cote, 2),
        "risk": _risk(p),
        "n_legs": len(legs),
    }


def _key(t):
    return tuple(sorted(l["event_id"] for l in t["legs"])), tuple(l["label"] for l in t["legs"])


# ---------------------------------------------------------------------------
# Constructeurs par profil
# ---------------------------------------------------------------------------
def _banker(legs, o):
    pool = _filter_pool(legs, o, exclude_props=True)
    pool = [l for l in pool if l["p"] >= 0.60]
    pool.sort(key=lambda c: -c["p"])
    mg = o.get("_must_group")
    out = []
    for n in range(1, min(o["max_legs"], 3) + 1):
        if n == 1:
            best = _search(pool, 1, lambda s: core.combo_prob(s), must_group=mg)
            label = "Single"
        else:
            best = _search(pool, n, lambda s: core.combo_prob(s) if len(s) == n else -1,
                           must_group=mg)
            label = {2: "Duo", 3: "Trio"}[n]
        t = _make_ticket("banker", "Banker — " + label, best, o)
        if t:
            out.append(t)
    return out


def _value(legs, o):
    pool = _filter_pool(legs, o, value_only=True, exclude_props=True)
    if not pool:
        pool = _filter_pool(legs, o, exclude_props=True)   # repli : meilleurs blends
    mg = o.get("_must_group")
    out = []
    # single value, duo value, trio value -> maximise EV (proba * cote)
    for n in range(1, min(o["max_legs"], 3) + 1):
        best = _search(pool, n,
                       lambda s: (core.combo_prob(s) * core.combo_odds(s)) if len(s) == n else -1,
                       must_group=mg)
        lab = {1: "Single", 2: "Duo", 3: "Trio"}[n]
        t = _make_ticket("value", "Value — " + lab, best, o)
        if t:
            out.append(t)
    return out


def _jackpot(legs, o):
    pool = _filter_pool(legs, o)              # tous marches autorises
    mg = o.get("_must_group")
    out = []
    for band in o["jackpot_bands"]:
        best = _search(pool, o["max_legs"], lambda s: core.combo_prob(s),
                       target=band, must_group=mg)
        if best and core.combo_odds(best) >= band * 0.85:
            t = _make_ticket("jackpot", "Jackpot — cible x%d" % band, best, o)
            if t:
                out.append(t)
    return out


def _fun(legs, o):
    pool = _filter_pool(legs, o, props_only=True)
    mg = o.get("_must_group")
    out = []
    if pool:
        pool.sort(key=lambda c: -(c.get("edge", 0)))
        # single (meilleur edge), puis combo inter-events de 2-3 props
        best1 = _search(pool, 1, lambda s: sum(l.get("edge", 0) for l in s), must_group=mg)
        t = _make_ticket("fun", "Fun — Prop solo", best1, o)
        if t: out.append(t)
        for n in (2, 3):
            if n > o["max_legs"]:
                break
            best = _search(pool, n,
                           lambda s: (core.combo_prob(s) * core.combo_odds(s)) if len(s) == n else -1,
                           must_group=mg)
            t = _make_ticket("fun", "Fun — Combo x%d" % n, best, o)
            if t: out.append(t)
    return out


_BUILDERS = {"banker": _banker, "value": _value, "jackpot": _jackpot, "fun": _fun}


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def build_tickets(legs, opts=None):
    """Genere un batch de tickets sur tous les profils demandes.
    Retourne {profile: [ticket, ...], ...} + cle '_meta'."""
    o = dict(DEFAULT_OPTS)
    if opts:
        o.update(opts)

    # filtre date global
    if o.get("date") and o["date"] != "all":
        legs = [l for l in legs if l.get("date") == o["date"]]

    # equipe/joueur impose -> group_id a forcer
    if o.get("must_team"):
        t = o["must_team"].lower()
        forced = [l for l in legs
                  if t in (l.get("team", "") or "").lower() or t in l["label"].lower()]
        o["_must_group"] = forced[0]["group_id"] if forced else None
    else:
        o["_must_group"] = None

    result = {"_meta": {"n_legs_pool": len(legs), "opts": {k: v for k, v in o.items()
                                                           if not k.startswith("_")}}}
    for prof in o["profiles"]:
        builder = _BUILDERS.get(prof)
        if not builder:
            continue
        raw = builder(legs, o)
        # diversite : retirer doublons exacts
        seen = set(); uniq = []
        for t in raw:
            k = _key(t)
            if k in seen:
                continue
            seen.add(k); uniq.append(t)
        result[prof] = uniq[:o["n_variants"]]
    # identifiants stables
    i = 0
    for prof in o["profiles"]:
        for t in result.get(prof, []):
            t["id"] = "%s-%d" % (prof, i); i += 1
    return result


def selections_from_predictions(predictions, scorers=None, factors=None,
                                competition="World Cup", sport="football"):
    """Convertit les `predictions` du moteur foot en pool de legs normalisees,
    pret pour build_tickets. Reutilisable comme modele pour les futurs sports."""
    legs = []
    for p in predictions:
        mkt = p.get("mkt")
        if not mkt or not p.get("edges"):
            continue
        for e in p["edges"]:
            if e["sel"] == "1":
                team = p["home"]; lab = "%s gagne (%s–%s)" % (p["home"], p["home"], p["away"])
            elif e["sel"] == "2":
                team = p["away"]; lab = "%s gagne (%s–%s)" % (p["away"], p["home"], p["away"])
            else:
                team = None; lab = "Nul %s–%s" % (p["home"], p["away"])
            legs.append({
                "event_id": p["id"], "group_id": p["id"], "date": p["date"],
                "sport": sport, "competition": competition, "market": "1N2",
                "sel": e["sel"], "label": lab, "cote": e["cote"],
                "p": e["pf"] / 100.0, "p_model": e["pm"] / 100.0,
                "p_market": e["pmkt"] / 100.0, "edge": e["edge"] / 100.0,
                "est": bool(mkt.get("est")), "team": team, "public": False, "is_core": True,
            })
    for s in (scorers or []):
        pid = None
        for p in predictions:
            if p["home"] + " - " + p["away"] == s["match"]:
                pid = p["id"]; break
        if pid is None:
            continue
        legs.append({
            "event_id": pid, "group_id": pid, "date": s["date"],
            "sport": sport, "competition": competition, "market": "buteur",
            "sel": s["player"], "label": "%s buteur (%s)" % (s["player"], s["match"]),
            "cote": s["cote"], "p": s["p"] / 100.0, "p_model": s["p"] / 100.0,
            "p_market": None, "edge": s["edge"] / 100.0, "est": False,
            "team": s["team"], "public": False, "is_core": False,
        })
    for p in predictions:
        disc = p.get("disc") or {}
        for mkey, lab, mname in (("cards", "cartons", "Cartons"), ("corners", "corners", "Corners")):
            od = disc.get(mkey + "_odds")
            if not od or not od.get("over"):
                continue
            legs.append({
                "event_id": p["id"], "group_id": p["id"], "date": p["date"],
                "sport": sport, "competition": competition, "market": mname, "is_core": False,
                "sel": "Over %s %s" % (od["line"], lab),
                "label": "+%s %s (%s–%s)" % (od["line"], lab, p["home"], p["away"]),
                "cote": od["over"], "p": od["p_over"] / 100.0, "p_model": od["p_over"] / 100.0,
                "p_market": None, "edge": od.get("edge_over", 0), "est": bool(od.get("est")),
                "team": None, "public": False,
            })
    return legs
