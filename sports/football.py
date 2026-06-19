# -*- coding: utf-8 -*-
"""
sports/football.py — plugin FOOTBALL (sports a buts) pour le moteur generique.

Porte a l'identique la math du moteur WC v2.3 audite (Elo dynamique intra-tournoi,
shrinkage xG, marge=dElo/175, total couple a |marge|, Dixon-Coles, blend marche
amorti, matchups bornes ±15 Elo, buteurs Poisson aminci, Monte-Carlo qualif).

Toute la calibration est regroupee dans CALIB pour faciliter l'affinage.
"""
import json
import os
import math
import random
from collections import defaultdict

from engine import core
from engine.sport import Sport, Event, register

# === CALIBRATION (point unique pour affiner le moteur) =====================
CALIB = {
    "ELO_PER_GOAL": 175.0,   # 1 but ~ 175 pts Elo (cap marge a +/-2.5)
    "MARGIN_CAP": 2.5,
    "T_COUPLE": 0.30,        # total += 0.30 par but d'ecart attendu
    "W_ELO": 0.80,           # poids de la marge Elo vs marge att/def
    "SHRINK": 0.50,          # retrecissement des ratings att/def vers 1.0
    "BASE": 2.52,            # base buts/match (moyenne phase de groupes CdM)
    "RHO": -0.12,            # correction Dixon-Coles
    "MAXG": 10,
    "NS": 20000,             # simulations Monte-Carlo
    "ALPHA": 0.30,           # blend : 30% modele / 70% marche
    "EDGE_MIN": 0.03, "EDGE_MAX": 0.12, "EDGE_ANOM": 0.15,
    "KFRAC": 0.25, "KCAP": 0.02, "EXPO_MAX": 0.12,
    "K_ELO": 60, "XG_W": 0.6, "SHRINK_K": 7.0,
}

# Cartons : multiplicateur d'arbitrage par confederation (CONMEBOL tres carton-naire :
# ~5.8 cartons/match vs ~4 UEFA, cf. base de connaissances). ref_conf optionnel par match.
REF_FACTOR = {"CONMEBOL": 1.25, "UEFA": 0.95, "AFC": 1.0, "CAF": 1.05, "CONCACAF": 1.0, "OFC": 1.0}
BASE_CARDS = 4.6      # total cartons/match (base WC)
BASE_CORNERS = 10.0   # total corners/match (base WC)


@register("football")
class FootballSport(Sport):
    key = "football"
    name = "Football"
    value_markets = ("1N2",)

    def __init__(self, root, calib=None, data_dir="data"):
        super().__init__(root)
        self.data_dir = data_dir
        self.c = dict(CALIB)
        if calib:
            self.c.update(calib)
        random.seed(42)
        self.preds = []
        self.values = []
        self.anomalies = []
        self.scorers = []
        self.factors_out = {}
        self.profils = {}
        self.played = []
        self.qualification = []
        self.signals = {}

    # -- chargement + probabilites -----------------------------------------
    def _p(self, name):
        return os.path.join(self.root, self.data_dir, name)

    def load(self):
        c = self.c
        T = json.load(open(self._p("teams.json"), encoding="utf-8"))
        T = {k: v for k, v in T.items() if not str(k).startswith("_")}  # ignorer _meta
        M = json.load(open(self._p("matches.json"), encoding="utf-8"))
        O = json.load(open(self._p("odds.json"), encoding="utf-8"))
        SC = json.load(open(self._p("scorers.json"), encoding="utf-8"))
        FACT = (json.load(open(self._p("factors.json"), encoding="utf-8"))
                if os.path.exists(self._p("factors.json")) else {})
        DESK = (json.load(open(self._p("desk.json"), encoding="utf-8"))
                if os.path.exists(self._p("desk.json")) else {})
        self.T, self.M, self.O, self.SC, self.FACT = T, M, O, SC, FACT
        self.DESK = DESK
        self.profils = FACT
        self.played = M["played"]

        # --- Elo dynamique intra-tournoi + shrinkage xG sur att/def ---
        K_ELO, XG_W, SHRINK_K = c["K_ELO"], c["XG_W"], c["SHRINK_K"]
        mc = {}
        for p in sorted(M["played"], key=lambda x: x["date"]):
            h, a = p["home"], p["away"]; sh, sa = p["score"]
            d = (T[h]["elo"] + T[h].get("host_bonus", 0)) - (T[a]["elo"] + T[a].get("host_bonus", 0))
            W = 1.0 if sh > sa else (0.0 if sh < sa else 0.5)
            nd = abs(sh - sa)
            G = 1.0 if nd <= 1 else (1.5 if nd == 2 else (11 + nd) / 8.0)
            delta = core.elo_delta(d, W, k=K_ELO, g=G)
            T[h]["elo"] += delta; T[a]["elo"] -= delta
            xg = p.get("xg")
            for team, gf, ga, i in ((h, sh, sa, 0), (a, sa, sh, 1)):
                gfe = XG_W * xg[i] + (1 - XG_W) * gf if xg else gf
                gae = XG_W * xg[1 - i] + (1 - XG_W) * ga if xg else ga
                mc[team] = mc.get(team, 0) + 1
                w = 1.0 / (mc[team] + SHRINK_K)
                T[team]["att"] += w * (gfe / 1.3 - T[team]["att"])
                T[team]["def"] += w * (gae / 1.3 - T[team]["def"])
        am = sum(t["att"] for t in T.values()) / len(T)
        dm = sum(t["def"] for t in T.values()) / len(T)
        SHRINK = c["SHRINK"]
        for t in T.values():
            t["att_n"] = 1 + SHRINK * (t["att"] / am - 1)
            t["def_n"] = 1 + SHRINK * (t["def"] / dm - 1)

        # --- matchups (facteurs : postes, style, mental, chaleur, banc) ---
        self.FADJ = {mt["id"]: self._matchup(mt["home"], mt["away"], mt.get("hot", False))
                     for mt in M["remaining"]}
        self.factors_out = {str(k): {"adj": round(v[0], 1), "adv": v[1]}
                            for k, v in self.FADJ.items()}

        # --- probabilites par match + value/anomalies ---
        self.lamc = {mt["id"]: self._mlam(mt) for mt in M["remaining"]}
        self.minfo = {mt["id"]: mt for mt in M["remaining"]}
        for mt in M["remaining"]:
            self._eval_match(mt)
        self._scorers()
        self._build_events()
        return self

    # -- helpers math (identiques v2.3) ------------------------------------
    def _eelo(self, n, pen=0):
        t = self.T[n]
        return t["elo"] + t["adj"] + t.get("host_bonus", 0) + pen

    def _lambdas(self, h, a, ph=0, pa=0):
        c = self.c
        th, ta = self.T[h], self.T[a]
        dr = self._eelo(h, ph) - self._eelo(a, pa)
        m_elo = max(-c["MARGIN_CAP"], min(c["MARGIN_CAP"], dr / c["ELO_PER_GOAL"]))
        lh0 = c["BASE"] / 2 * th["att_n"] * ta["def_n"]
        la0 = c["BASE"] / 2 * ta["att_n"] * th["def_n"]
        m = c["W_ELO"] * m_elo + (1 - c["W_ELO"]) * (lh0 - la0)
        Tt = max(1.9, min(4.2, lh0 + la0 + c["T_COUPLE"] * abs(m_elo)))
        lh, la = (Tt + m) / 2, (Tt - m) / 2
        if la < 0.15: la = 0.15; lh = Tt - 0.15
        if lh < 0.15: lh = 0.15; la = Tt - 0.15
        return lh, la

    def _mlam(self, mt):
        return self._lambdas(mt["home"], mt["away"],
                             mt.get("penalty_home", 0) + self.FADJ[mt["id"]][0],
                             mt.get("penalty_away", 0))

    def _matchup(self, h, a, hot=False):
        fh, fa = self.FACT.get(h), self.FACT.get(a)
        if not fh or not fa:
            return 0.0, []
        adv = []; score = 0.0
        duels = [
            (fh["ailes"] - fa["lateraux"], 0.50, "Ailes %s vs lateraux %s" % (h, a)),
            (fa["ailes"] - fh["lateraux"], -0.50, "Ailes %s vs lateraux %s" % (a, h)),
            (fh["attaque"] - fa["def_centrale"], 0.60, "Attaque %s vs charniere %s" % (h, a)),
            (fa["attaque"] - fh["def_centrale"], -0.60, "Attaque %s vs charniere %s" % (a, h)),
        ]
        for d, w, lab in duels:
            if d >= 2:
                score += abs(w) * d * (1 if w > 0 else -1)
                adv.append(lab + " (+%d)" % d)
        dm = fh["milieu"] - fa["milieu"]
        if abs(dm) >= 2:
            score += 0.8 * dm; adv.append("Bataille du milieu : %s (+%d)" % (h if dm > 0 else a, abs(dm)))
        dmen = fh["mental"] - fa["mental"]
        if abs(dmen) >= 2:
            score += 0.4 * dmen; adv.append("Mental/vecu : %s (+%d)" % (h if dmen > 0 else a, abs(dmen)))
        dg = fh["gardien"] - fa["gardien"]
        if abs(dg) >= 3:
            score += 0.3 * dg; adv.append("Gardien : %s (+%d)" % (h if dg > 0 else a, abs(dg)))
        db = fh["profondeur_banc"] - fa["profondeur_banc"]
        if abs(db) >= 3:
            score += 0.2 * db; adv.append("Profondeur de banc : %s" % (h if db > 0 else a))
        if hot:
            dc_ = fh["chaleur"] - fa["chaleur"]
            if abs(dc_) >= 2:
                score += 0.6 * dc_; adv.append("Chaleur/conditions : %s (+%d)" % (h if dc_ > 0 else a, abs(dc_)))
        if fh["style"] == "pressing" and fa["milieu"] <= 5:
            score += 0.8; adv.append("Pressing %s vs relance faible %s" % (h, a))
        if fa["style"] == "pressing" and fh["milieu"] <= 5:
            score -= 0.8; adv.append("Pressing %s vs relance faible %s" % (a, h))
        if fa["style"] == "bloc_bas" and fh["attaque"] <= 5 and fh["ailes"] <= 6:
            adv.append("Bloc bas %s vs attaque limitee %s : nul possible" % (a, h))
        if fh["style"] == "bloc_bas" and fa["attaque"] <= 5 and fa["ailes"] <= 6:
            adv.append("Bloc bas %s vs attaque limitee %s : nul possible" % (h, a))
        fadj = max(-15.0, min(15.0, score * 4.0))
        return fadj, adv

    def _eval_match(self, mt):
        c = self.c
        mid = str(mt["id"]); mkt = self.O.get(mid)
        lh, la = self.lamc[mt["id"]]
        Mx = core.score_matrix(lh, la, c["RHO"], c["MAXG"])
        mk = core.matrix_markets(Mx)
        p1, pn, p2 = mk["p1"], mk["pn"], mk["p2"]
        edges_out = []
        if mkt:
            mp = core.pool_probs(mkt)
            for i, (pm, co, lab) in enumerate(((p1, mkt["h"], "1"), (pn, mkt["d"], "N"), (p2, mkt["a"], "2"))):
                pf = core.blend(pm, mp[i], co, c["ALPHA"])
                ed = core.edge(pf, co)
                stake = core.stake_fraction(pf, co, c["KFRAC"], c["KCAP"])
                edges_out.append({"sel": lab, "cote": co, "pm": round(pm * 100, 1),
                                  "pmkt": round(mp[i] * 100, 1), "pf": round(pf * 100, 1),
                                  "edge": round(ed * 100, 1), "stake": round(stake * 100, 2)})
                d = {"date": mt["date"], "match": mt["home"] + " - " + mt["away"], "sel": lab,
                     "cote": co, "p_model": pm * 100, "p_mkt": mp[i] * 100, "p_fin": pf * 100,
                     "edge": ed * 100, "stake": stake * 100, "est": mkt.get("est", False)}
                if ed > c["EDGE_ANOM"]:
                    self.anomalies.append(d)
                elif c["EDGE_MIN"] < ed <= c["EDGE_MAX"] and pf >= 0.15 and not mkt.get("est", False):
                    self.values.append(d)
        ko = mt.get("stage") == "ko" or mt.get("group") in (None, "KO")
        pqh = pqa = None
        if ko and (p1 + p2) > 0:
            pqh = round((p1 + pn * p1 / (p1 + p2)) * 100, 1)   # se qualifie = victoire + part du nul (prolong./tab) selon force
            pqa = round((p2 + pn * p2 / (p1 + p2)) * 100, 1)
        self.preds.append({
            "id": mt["id"], "date": mt["date"], "grp": mt.get("group", mt.get("round", "KO")),
            "home": mt["home"], "away": mt["away"], "ko": ko, "pqh": pqh, "pqa": pqa,
            "desk": self.DESK.get(mt["home"] + " - " + mt["away"]),
            "disc": self._disc(mt, lh, la),
            "p1": round(p1 * 100, 1), "pn": round(pn * 100, 1), "p2": round(p2 * 100, 1),
            "f1": round(1 / p1, 2), "fn": round(1 / pn, 2), "f2": round(1 / p2, 2),
            "o25": round(mk["o25"] * 100, 1), "btts": round(mk["btts"] * 100, 1),
            "xgh": round(lh, 2), "xga": round(la, 2),
            "scores": [[i, j, round(pv * 100, 1)] for i, j, pv in mk["top"]],
            "mkt": ({"h": mkt["h"], "d": mkt["d"], "a": mkt["a"], "o25": mkt.get("o25"),
                     "btts": mkt.get("btts"), "est": mkt.get("est", False)} if mkt else None),
            "edges": edges_out})

    def _pover(self, lam, line_int):
        """P(total > line_int) pour une loi de Poisson (ligne 4.5 -> line_int=4)."""
        cdf = sum(core.poisson(lam, k) for k in range(0, line_int + 1))
        return max(0.0, min(1.0, 1 - cdf))

    def _disc(self, mt, lh, la):
        """Cartons & corners attendus (modele heuristique borne) + P(over) lignes par defaut.
        Cartons = base x arbitre x serrage (match serre = plus de cartons).
        Corners = base x domination offensive (match ouvert = plus de corners)."""
        m = abs(lh - la)
        close = 1 + 0.15 * (1 - min(1.0, m / 2.0))
        ref = REF_FACTOR.get(mt.get("ref_conf"), 1.0)
        cards = BASE_CARDS * ref * close
        corners = max(7.0, min(13.0, BASE_CORNERS * (1 + 0.10 * ((lh + la) - 2.5))))
        out = {"ref_conf": mt.get("ref_conf"),
               "cards_exp": round(cards, 1), "p_over_cards45": round(self._pover(cards, 4) * 100, 1),
               "corners_exp": round(corners, 1), "p_over_corners95": round(self._pover(corners, 9) * 100, 1)}
        mk = self.O.get(str(mt["id"])) or {}
        for key, lam, dl in (("cards", cards, 4.5), ("corners", corners, 9.5)):
            od = mk.get(key)
            if od and od.get("over"):
                line = od.get("line", dl)
                pov = self._pover(lam, int(line))   # ligne X.5 -> floor entier
                out[key + "_odds"] = {"line": line, "over": od["over"], "under": od.get("under"),
                                      "p_over": round(pov * 100, 1),
                                      "edge_over": round(pov * od["over"] - 1, 3),
                                      "est": bool(od.get("est"))}
        return out

    def _scorers(self):
        sc = []
        for s in self.SC:
            mt = self.minfo.get(s["mid"])
            if not mt:
                continue
            lh, la = self.lamc[s["mid"]]
            lam = lh if s["team"] == mt["home"] else la
            p = 1 - math.exp(-lam * s["s"] * s["mins"])
            ed = p * s["cote"] - 1
            sc.append({"player": s["player"], "team": s["team"], "match": mt["home"] + " - " + mt["away"],
                       "date": mt["date"], "cote": s["cote"], "p": round(p * 100, 1), "edge": round(ed * 100, 1)})
        sc.sort(key=lambda x: -x["edge"])
        self.scorers = sc

    def _build_events(self):
        """Remplit self.events (interface Sport) — utile pour un usage generique."""
        for p in self.preds:
            self.events.append(Event(p["id"], p["date"], p["home"] + " - " + p["away"],
                                     "World Cup", "football", model=p, market=p.get("mkt")))

    # -- portefeuille de value (cap d'exposition) ---------------------------
    def cap_values(self):
        c = self.c
        stakes = [v["stake"] for v in self.values]
        capped = core.cap_portfolio([s / 100 for s in stakes], c["EXPO_MAX"])
        for v, s in zip(self.values, capped):
            v["stake"] = s * 100
        return self.values

    # -- Monte-Carlo qualification -----------------------------------------
    def simulate(self, ns=None):
        c = self.c
        NS = ns or c["NS"]; MAXG = c["MAXG"]
        grem = [mt for mt in self.M["remaining"] if mt.get("group") and mt.get("stage") != "ko"]
        if not grem:
            self.qualification = []
            return []   # plus de matchs de poule -> phase a elimination directe, Monte-Carlo qualif N/A
        flat = {}
        for mt in grem:
            lh, la = self.lamc[mt["id"]]
            Mx = core.score_matrix(lh, la, c["RHO"], MAXG)
            flat[mt["id"]] = ([(i, j) for i in range(MAXG) for j in range(MAXG)],
                              [Mx[i][j] for i in range(MAXG) for j in range(MAXG)])
        groups = defaultdict(list)
        for nm, t in self.T.items():
            groups[t["group"]].append(nm)
        c1 = defaultdict(int); c2 = defaultdict(int); c3 = defaultdict(int); cq = defaultdict(int)

        def rank_group(tl, pts, gd, gf, h2h):
            def key(t): return (pts[t], gd[t], gf[t])
            order = sorted(tl, key=lambda t: (key(t), random.random()), reverse=True)
            out = []; i = 0
            while i < len(order):
                tied = [x for x in order if key(x) == key(order[i]) and x not in out]
                if len(tied) > 1:
                    hp = defaultdict(int)
                    for (a, b), (sa, sb) in h2h.items():
                        if a in tied and b in tied:
                            hp[a] += 3 if sa > sb else (1 if sa == sb else 0)
                            hp[b] += 3 if sb > sa else (1 if sa == sb else 0)
                    tied.sort(key=lambda t: (hp[t], random.random()), reverse=True)
                out.extend(tied); i = len(out)
            return out

        for _ in range(NS):
            pts = defaultdict(int); gd = defaultdict(int); gf = defaultdict(int); h2h = {}

            def app(h, a, sh, sa):
                gd[h] += sh - sa; gd[a] += sa - sh; gf[h] += sh; gf[a] += sa; h2h[(h, a)] = (sh, sa)
                pts[h] += 3 if sh > sa else (1 if sh == sa else 0)
                pts[a] += 3 if sa > sh else (1 if sh == sa else 0)
            for p in self.M["played"]:
                if not p.get("group"):
                    continue
                app(p["home"], p["away"], p["score"][0], p["score"][1])
            for mt in grem:
                sc_, w = flat[mt["id"]]; i, j = random.choices(sc_, weights=w)[0]
                app(mt["home"], mt["away"], i, j)
            thirds = []
            for g, tl in groups.items():
                o = rank_group(tl, pts, gd, gf, h2h)
                c1[o[0]] += 1; c2[o[1]] += 1; cq[o[0]] += 1; cq[o[1]] += 1; thirds.append(o[2])
            thirds.sort(key=lambda t: (pts[t], gd[t], gf[t], random.random()), reverse=True)
            for t in thirds[:8]:
                c3[t] += 1; cq[t] += 1
        qual = []
        for g in sorted(groups):
            for t in sorted(groups[g], key=lambda t: -cq[t]):
                qual.append({"grp": g, "team": t, "p1": round(c1[t] / NS * 100, 1),
                             "p2": round(c2[t] / NS * 100, 1), "p3q": round(c3[t] / NS * 100, 1),
                             "pq": round(cq[t] / NS * 100, 1)})
        self.qualification = qual
        return qual

    # -- signaux WC speciaux (dead rubber, match chaud, equipe publique) ----
    PUBLIC = {"France", "Brazil", "England", "USA", "Mexico", "Argentina"}

    def compute_signals(self):
        qpr = {q["team"]: q["pq"] for q in self.qualification}
        sig = {}
        for mt in self.M["remaining"]:
            s = []
            h, a = mt["home"], mt["away"]
            if mt.get("hot"):
                s.append({"type": "under", "txt": "Match chaud (midi) -> lean Under 2.5 buts"})
            if mt.get("ref_conf") == "CONMEBOL":
                s.append({"type": "cartons", "txt": "Arbitre CONMEBOL -> lean Over cartons (~5.8/match vs ~4 UEFA)"})
            for team in (h, a):
                if team in self.PUBLIC:
                    s.append({"type": "public", "txt": "%s = equipe publique : cote rognee, eviter en sec (nul/outsider = value possible)" % team})
            if mt["date"] >= "2026-06-24":   # fenetre J3
                for team in (h, a):
                    pq = qpr.get(team)
                    if pq is not None and (pq >= 97 or pq <= 3):
                        etat = "deja qualifiee" if pq >= 97 else "deja eliminee"
                        s.append({"type": "deadrubber", "txt": "%s %s (qualif %s%%) -> dead rubber : rotation/nul possible, lean Under" % (team, etat, pq)})
            if s:
                sig[str(mt["id"])] = s
        self.signals = sig
        return sig


@register("football_clubs")
class FootballClubsSport(FootballSport):
    """Reutilise TOUTE la math football sur d'autres competitions de clubs
    (L1, Premier League, Ligue des Champions...). Seules les donnees changent
    (dossier data_football_clubs/). Demonstration que le moteur foot est generique."""
    key = "football_clubs"
    name = "Foot clubs"

    def __init__(self, root, calib=None):
        super().__init__(root, calib=calib, data_dir="data_football_clubs")
