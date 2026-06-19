# -*- coding: utf-8 -*-
"""
WORLDCUP KING OF BET - Moteur de probabilites v1.0
==================================================
Pipeline : Elo (+bonus hote, +ajustements qualitatifs blessures/psychologie)
  -> marge de buts attendue (logistique Elo)
  -> lambdas Poisson par equipe (blend Elo 55% / ratings att-def 45%)
  -> matrice de scores Dixon-Coles (correction petits scores)
  -> probas 1N2, O/U 2.5, BTTS, scores exacts, cotes justes
  -> comparaison aux cotes marche de-vigees -> edge + mise quart-Kelly
  -> Monte-Carlo 20 000 tournois : qualification (1er/2e/3e repeche parmi 8)
"""
import json, math, random, csv, os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
random.seed(42)

# ---------- Parametres calibres (v1.1) ----------
HOST_BONUS   = 75     # Elo : avantage du pays hote (joue chez lui)
K1, K3       = 1.10, 1.60  # marge non-lineaire : m = K1*x + K3*x^3, x = 2We-1
W_ELO        = 0.80   # poids de la marge Elo vs marge stats att/def
SHRINK       = 0.50   # retrecissement des ratings att/def vers 1.0 (biais qualifs)
BASE_GOALS   = 2.62   # total de buts moyen attendu (phase de groupes CdM)
RHO_DC       = -0.10  # correction Dixon-Coles
MAXG         = 9      # taille matrice de scores
N_SIMS       = 20000  # simulations Monte-Carlo
KELLY_FRAC   = 0.25   # quart de Kelly
KELLY_CAP    = 0.03   # mise max 3% de bankroll
ALPHA_MODEL  = 0.65   # blend final : 65% modele / 35% marche (le marche est sharp)

teams   = json.load(open(os.path.join(ROOT, "data", "teams.json"), encoding="utf-8"))
matches = json.load(open(os.path.join(ROOT, "data", "matches.json"), encoding="utf-8"))
odds    = json.load(open(os.path.join(ROOT, "data", "odds.json"), encoding="utf-8"))

# normalisation des ratings att/def autour de 1.0
n = len(teams)
att_m = sum(t["att"] for t in teams.values()) / n
def_m = sum(t["def"] for t in teams.values()) / n
for t in teams.values():
    t["att_n"] = 1 + SHRINK * (t["att"] / att_m - 1)
    t["def_n"] = 1 + SHRINK * (t["def"] / def_m - 1)

def eff_elo(name, pen=0):
    t = teams[name]
    return t["elo"] + t["adj"] + (HOST_BONUS if t["host"] else 0) + pen

def lambdas(home, away, ph=0, pa=0):
    th, ta = teams[home], teams[away]
    dr  = eff_elo(home, ph) - eff_elo(away, pa)
    we  = 1.0 / (1.0 + 10 ** (-dr / 400.0))
    x   = 2 * we - 1
    m_elo = K1 * x + K3 * x ** 3
    lh0 = BASE_GOALS / 2 * th["att_n"] * ta["def_n"]
    la0 = BASE_GOALS / 2 * ta["att_n"] * th["def_n"]
    m_stat = lh0 - la0
    T = max(1.9, min(3.6, lh0 + la0))
    m = W_ELO * m_elo + (1 - W_ELO) * m_stat
    lh = max(0.12, (T + m) / 2)
    la = max(0.12, (T - m) / 2)
    return lh, la

def pois(l, k):
    return math.exp(-l) * l ** k / math.factorial(k)

def dc_tau(x, y, lh, la, rho):
    if x == 0 and y == 0: return 1 - lh * la * rho
    if x == 0 and y == 1: return 1 + lh * rho
    if x == 1 and y == 0: return 1 + la * rho
    if x == 1 and y == 1: return 1 - rho
    return 1.0

def score_matrix(lh, la):
    M = [[pois(lh, i) * pois(la, j) * dc_tau(i, j, lh, la, RHO_DC)
          for j in range(MAXG)] for i in range(MAXG)]
    s = sum(sum(r) for r in M)
    return [[v / s for v in row] for row in M]

def market_probs(o):
    inv = [1/o["h"], 1/o["d"], 1/o["a"]]
    s = sum(inv)
    return [v/s for v in inv]

def analyse(home, away, ph=0, pa=0, mkt=None):
    lh, la = lambdas(home, away, ph, pa)
    M = score_matrix(lh, la)
    p1 = sum(M[i][j] for i in range(MAXG) for j in range(MAXG) if i > j)
    pn = sum(M[i][i] for i in range(MAXG))
    p2 = 1 - p1 - pn
    o25 = sum(M[i][j] for i in range(MAXG) for j in range(MAXG) if i + j >= 3)
    btts = sum(M[i][j] for i in range(1, MAXG) for j in range(1, MAXG))
    scores = sorted(((i, j, M[i][j]) for i in range(MAXG) for j in range(MAXG)),
                    key=lambda x: -x[2])[:3]
    res = {"home": home, "away": away, "lh": lh, "la": la,
           "p1": p1, "pn": pn, "p2": p2, "o25": o25, "btts": btts,
           "fair": (1/p1, 1/pn, 1/p2), "top_scores": scores,
           "edges": None}
    if mkt:
        mp = market_probs(mkt)
        edges = []
        for i, (prob, cote, lab) in enumerate(((p1, mkt["h"], "1"), (pn, mkt["d"], "N"), (p2, mkt["a"], "2"))):
            p_fin = ALPHA_MODEL * prob + (1 - ALPHA_MODEL) * mp[i]  # blend modele/marche
            edge = p_fin * cote - 1
            b = cote - 1
            kelly = max(0.0, (p_fin * b - (1 - p_fin)) / b) if b > 0 else 0
            stake = min(KELLY_CAP, KELLY_FRAC * kelly)
            edges.append({"sel": lab, "cote": cote, "p_model": prob, "p_final": p_fin,
                          "p_marche": mp[i], "edge": edge, "mise_pct": stake * 100})
        res["edges"] = edges
    return res

# ---------- Analyse de tous les matchs restants ----------
rows, value_bets = [], []
for m in matches["remaining"]:
    mkt = odds.get(str(m["id"]))
    r = analyse(m["home"], m["away"], m.get("penalty_home", 0), m.get("penalty_away", 0), mkt)
    ts = " / ".join(f"{i}-{j} {p*100:.0f}%" for i, j, p in r["top_scores"])
    rows.append([m["date"], m["group"], f'{m["home"]} - {m["away"]}',
                 f'{r["p1"]*100:.1f}', f'{r["pn"]*100:.1f}', f'{r["p2"]*100:.1f}',
                 f'{r["fair"][0]:.2f}', f'{r["fair"][1]:.2f}', f'{r["fair"][2]:.2f}',
                 f'{r["o25"]*100:.1f}', f'{r["btts"]*100:.1f}', f'{r["lh"]:.2f}', f'{r["la"]:.2f}', ts])
    if r["edges"]:
        for e in r["edges"]:
            # filtre credibilite : edge 4-50%, proba finale >= 15%, cotes reelles uniquement
            if 0.04 < e["edge"] < 0.50 and e["p_final"] >= 0.15:
                value_bets.append({"date": m["date"], "match": f'{m["home"]} - {m["away"]}',
                                   "sel": e["sel"], "cote": e["cote"],
                                   "p_model": e["p_model"]*100, "p_final": e["p_final"]*100,
                                   "p_marche": e["p_marche"]*100,
                                   "edge": e["edge"]*100, "mise": e["mise_pct"],
                                   "est": odds[str(m["id"])].get("est", False)})

os.makedirs(os.path.join(ROOT, "output"), exist_ok=True)
with open(os.path.join(ROOT, "output", "predictions.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["Date","Grp","Match","P1 %","PN %","P2 %","Cote juste 1","Cote juste N","Cote juste 2",
                "Over2.5 %","BTTS %","xG dom","xG ext","Scores les + probables"])
    w.writerows(rows)

# ---------- Monte-Carlo qualification ----------
def sim_match(lh, la):
    def draw(l):
        x, p, c, u = 0, math.exp(-l), 0.0, random.random()
        c = p
        while u > c and x < 12:
            x += 1; p *= l / x; c += p
        return x
    return draw(lh), draw(la)

lam_cache = {m["id"]: lambdas(m["home"], m["away"], m.get("penalty_home",0), m.get("penalty_away",0))
             for m in matches["remaining"]}
groups = defaultdict(list)
for nm, t in teams.items():
    groups[t["group"]].append(nm)

count_1st = defaultdict(int); count_2nd = defaultdict(int)
count_3rd_q = defaultdict(int); count_q = defaultdict(int)

for _ in range(N_SIMS):
    pts = defaultdict(int); gd = defaultdict(int); gf = defaultdict(int)
    for p in matches["played"]:
        h, a, (sh, sa) = p["home"], p["away"], p["score"]
        gd[h] += sh - sa; gd[a] += sa - sh; gf[h] += sh; gf[a] += sa
        pts[h] += 3 if sh > sa else (1 if sh == sa else 0)
        pts[a] += 3 if sa > sh else (1 if sh == sa else 0)
    for m in matches["remaining"]:
        lh, la = lam_cache[m["id"]]
        sh, sa = sim_match(lh, la)
        h, a = m["home"], m["away"]
        gd[h] += sh - sa; gd[a] += sa - sh; gf[h] += sh; gf[a] += sa
        pts[h] += 3 if sh > sa else (1 if sh == sa else 0)
        pts[a] += 3 if sa > sh else (1 if sh == sa else 0)
    thirds = []
    for g, tl in groups.items():
        order = sorted(tl, key=lambda t: (pts[t], gd[t], gf[t], random.random()), reverse=True)
        count_1st[order[0]] += 1; count_2nd[order[1]] += 1
        count_q[order[0]] += 1; count_q[order[1]] += 1
        thirds.append(order[2])
    thirds.sort(key=lambda t: (pts[t], gd[t], gf[t], random.random()), reverse=True)
    for t in thirds[:8]:
        count_3rd_q[t] += 1; count_q[t] += 1

with open(os.path.join(ROOT, "output", "qualification.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["Groupe","Equipe","P(1er) %","P(2e) %","P(3e repeche) %","P(qualif totale) %"])
    for g in sorted(groups):
        for t in sorted(groups[g], key=lambda t: -count_q[t]):
            w.writerow([g, t, f"{count_1st[t]/N_SIMS*100:.1f}", f"{count_2nd[t]/N_SIMS*100:.1f}",
                        f"{count_3rd_q[t]/N_SIMS*100:.1f}", f"{count_q[t]/N_SIMS*100:.1f}"])

# ---------- Sorties console ----------
print("=== VALUE BETS (edge final 4-50%, p>=15%) ===")
for v in sorted(value_bets, key=lambda x: -x["edge"]):
    if v["est"]:
        continue
    print(f'{v["date"]} {v["match"]:34s} [{v["sel"]}] cote {v["cote"]:.2f} | '
          f'modele {v["p_model"]:.1f}% / final {v["p_final"]:.1f}% vs marche {v["p_marche"]:.1f}% | '
          f'edge +{v["edge"]:.1f}% | mise {v["mise"]:.2f}%')
print("\n--- A confirmer (cotes estimees, a verifier chez le bookmaker) ---")
for v in sorted(value_bets, key=lambda x: -x["edge"]):
    if v["est"]:
        print(f'{v["date"]} {v["match"]:34s} [{v["sel"]}] cote {v["cote"]:.2f} | edge +{v["edge"]:.1f}%')

print("\n=== QUALIFICATION (proba de sortir des poules) ===")
for g in sorted(groups):
    line = ", ".join(f"{t} {count_q[t]/N_SIMS*100:.0f}%"
                     for t in sorted(groups[g], key=lambda t: -count_q[t]))
    print(f"Groupe {g}: {line}")

print("\nFichiers : output/predictions.csv, output/qualification.csv")
# fin du script

