# -*- coding: utf-8 -*-
"""
engine/core.py — primitives de probabilite et de paris SPORT-AGNOSTIQUES.

Aucune dependance a un sport precis : ces fonctions manipulent des cotes, des
probabilites et des matrices de score. Elles sont calibrees a l'identique du
moteur WC v2.3 audite, mais reutilisables pour n'importe quel sport.
"""
import math

# ----------------------------------------------------------------------------
# 1. ELO  (generique : utilisable pour foot, tennis, basket, esport...)
# ----------------------------------------------------------------------------
def elo_we(diff):
    """Esperance de victoire d'un joueur/equipe avec un ecart Elo `diff`."""
    return 1.0 / (1.0 + 10 ** (-diff / 400.0))


def elo_delta(diff, result, k=60.0, g=1.0):
    """Variation d'Elo apres un match. `result` in {1,0.5,0}. `g` = multiplicateur
    d'importance/marge (1 par defaut ; le sport peut le moduler par l'ecart de score)."""
    return k * g * (result - elo_we(diff))


# ----------------------------------------------------------------------------
# 2. LOIS DE SCORE  (sports a buts : foot, hockey, handball...)
# ----------------------------------------------------------------------------
def poisson(lam, k):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def dc_tau(x, y, lh, la, rho):
    """Correction Dixon-Coles sur les petits scores (dependance 0-0/1-0/0-1/1-1)."""
    if x == 0 and y == 0:
        return 1 - lh * la * rho
    if x == 0 and y == 1:
        return 1 + lh * rho
    if x == 1 and y == 0:
        return 1 + la * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def score_matrix(lh, la, rho=-0.12, maxg=10):
    """Matrice de probabilites de score (Poisson x correction Dixon-Coles)."""
    mx = [[poisson(lh, i) * poisson(la, j) * dc_tau(i, j, lh, la, rho)
           for j in range(maxg)] for i in range(maxg)]
    s = sum(sum(r) for r in mx)
    return [[v / s for v in r] for r in mx]


def matrix_markets(mx):
    """Extrait les marches standards d'une matrice de score : 1N2, O/U2.5, BTTS,
    top scores. Retourne un dict pret a l'emploi."""
    maxg = len(mx)
    p1 = sum(mx[i][j] for i in range(maxg) for j in range(maxg) if i > j)
    pn = sum(mx[i][i] for i in range(maxg))
    p2 = 1 - p1 - pn
    o25 = sum(mx[i][j] for i in range(maxg) for j in range(maxg) if i + j >= 3)
    btts = sum(mx[i][j] for i in range(1, maxg) for j in range(1, maxg))
    top = sorted(((i, j, mx[i][j]) for i in range(maxg) for j in range(maxg)),
                 key=lambda x: -x[2])[:3]
    return {"p1": p1, "pn": pn, "p2": p2, "o25": o25, "btts": btts, "top": top}


# ----------------------------------------------------------------------------
# 3. DE-VIG & PROBABILITES MARCHE  (tous sports)
# ----------------------------------------------------------------------------
def devig_power(odds):
    """De-vig par methode 'power' : corrige le biais favori-outsider (mieux que
    le de-vig proportionnel). Accepte un nombre quelconque d'issues."""
    inv = [1.0 / o for o in odds]
    lo, hi = 0.5, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        s = sum(p ** k for p in inv)
        if s > 1:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    ps = [p ** k for p in inv]
    s = sum(ps)
    return [p / s for p in ps]


def pool_probs(market, keys=("h", "d", "a")):
    """Probabilites marche de-viguees, en moyennant plusieurs books si fournis
    dans market['sources'] (moyenne geometrique ponderee = line shopping)."""
    n = len(keys)
    srcs = market.get("sources")
    if not srcs:
        return devig_power([market[k] for k in keys])
    pooled = [1.0] * n
    tw = 0.0
    for s in srcs:
        ps = devig_power([s[k] for k in keys])
        w = s.get("w", 1.0)
        tw += w
        for i in range(n):
            pooled[i] *= ps[i] ** w
    pooled = [p ** (1.0 / max(tw, 1e-9)) for p in pooled]
    tot = sum(pooled)
    return [p / tot for p in pooled]


# ----------------------------------------------------------------------------
# 4. BLEND MODELE / MARCHE  (tous sports)
# ----------------------------------------------------------------------------
def blend(p_model, p_market, odds, alpha=0.30):
    """Melange modele/marche. Le marche est sharp -> poids majoritaire.
    Amortisseur : si le modele sur-cote un outsider (cote>=4 et p_model>p_market),
    on reduit son influence pour eviter les faux 'edges'."""
    al = alpha
    if odds >= 4 and p_model > p_market:
        al = alpha * max(0.0, 1 - 4 * (p_model - p_market))
    return al * p_model + (1 - al) * p_market


# ----------------------------------------------------------------------------
# 5. VALUE & MISES  (tous sports)
# ----------------------------------------------------------------------------
def edge(p_final, odds):
    return p_final * odds - 1


def kelly_fraction(p_final, odds):
    """Fraction de Kelly pleine pour une cote decimale."""
    b = odds - 1
    if b <= 0:
        return 0.0
    return max(0.0, (p_final * b - (1 - p_final)) / b)


def stake_fraction(p_final, odds, kfrac=0.25, kcap=0.02):
    """Mise en fraction de bankroll : quart-Kelly plafonne."""
    return min(kcap, kfrac * kelly_fraction(p_final, odds))


def cap_portfolio(stakes, expo_max=0.12):
    """Plafonne l'exposition totale d'un portefeuille de mises (liste de fractions).
    Retourne les mises re-echelonnees."""
    tot = sum(stakes)
    if tot > expo_max and tot > 0:
        f = expo_max / tot
        return [s * f for s in stakes]
    return list(stakes)


# ----------------------------------------------------------------------------
# 6. EVALUATION DE COMBINES  (tous sports)
# ----------------------------------------------------------------------------
def combo_odds(legs):
    r = 1.0
    for l in legs:
        r *= l["cote"]
    return r


def combo_prob(legs):
    """Proba jointe d'un combine en supposant l'independance (legs sur events
    distincts -> hypothese raisonnable apres anti-correlation)."""
    r = 1.0
    for l in legs:
        r *= l["p"]
    return r


def combo_ev(legs):
    """Esperance de valeur d'un combine : p_jointe * cote_totale - 1."""
    return combo_prob(legs) * combo_odds(legs) - 1
