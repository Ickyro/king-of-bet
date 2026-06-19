# -*- coding: utf-8 -*-
"""
selftest.py — audit qualite / smoke test du pipeline Worldcup King of Bet.

Lance le moteur puis valide les sorties (JSON valides, cles presentes, tickets
sans violation d'anti-correlation, pas d'octets nuls dans les modules, paper
trading coherent...). Sort en code 1 si un check echoue.

Usage :  python selftest.py
"""
import os
import sys
import json
import glob
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
FAILS = []
OKS = []


def check(name, cond, detail=""):
    (OKS if cond else FAILS).append(name + ((" — " + detail) if detail and not cond else ""))
    print(("  OK  " if cond else "FAIL  ") + name + (("  [" + detail + "]") if detail else ""))


def load_app_data():
    txt = open(os.path.join(ROOT, "app", "app_data.js"), encoding="utf-8").read()
    return json.loads(txt[txt.index("=") + 1:].strip().rstrip(";"))


print("=== 1. Compilation des modules Python ===")
mods = ["run_worldcup.py", "run_sport.py", "backtest.py"] + glob.glob("engine/*.py") + glob.glob("sports/*.py")
import py_compile
for m in mods:
    try:
        py_compile.compile(os.path.join(ROOT, m), doraise=True)
        check("compile %s" % m, True)
    except Exception as e:
        check("compile %s" % m, False, str(e)[:60])

print("=== 2. Pas d'octets nuls dans les modules ===")
for m in mods + ["app/WorldcupKingOfBet.html"]:
    raw = open(os.path.join(ROOT, m), "rb").read()
    check("no-null %s" % m, b"\x00" not in raw)

print("=== 3. Donnees JSON valides ===")
for j in glob.glob("data/*.json"):
    try:
        json.load(open(os.path.join(ROOT, j), encoding="utf-8")); check("json %s" % j, True)
    except Exception as e:
        check("json %s" % j, False, str(e)[:60])

if "--no-run" in sys.argv:
    print("=== 4. Execution du moteur (SKIP : --no-run, validation des outputs existants) ===")
else:
    print("=== 4. Execution du moteur ===")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "run_worldcup.py")],
                       capture_output=True, text=True, cwd=ROOT)
    check("run_worldcup.py exit 0", r.returncode == 0, r.stderr.strip()[-80:])
    check("sortie 'OK ->'", "OK ->" in r.stdout)

print("=== 5. app_data.js : structure ===")
try:
    D = load_app_data()
    check("app_data.js JSON valide", True)
    for k in ["predictions", "qualification", "values", "anomalies", "scorers",
              "ticket_batch", "ticket_pool", "factors", "profils", "backtest", "signals", "paper"]:
        check("cle app_data.%s" % k, k in D)
    check("predictions non vide", len(D.get("predictions", [])) > 0)
    p0 = D["predictions"][0]
    for f in ["p1", "pn", "p2", "o25", "btts", "disc", "ko"]:
        check("pred.%s present" % f, f in p0)
    check("disc.cards_exp", "cards_exp" in p0.get("disc", {}))
    # somme 1N2 ~ 100
    s = p0["p1"] + p0["pn"] + p0["p2"]
    check("somme 1N2 ~ 100%", abs(s - 100) < 0.5, "somme=%.2f" % s)
except Exception as e:
    check("app_data.js JSON valide", False, str(e)[:80]); D = {}

print("=== 6. Tickets : anti-correlation (1 leg/match) ===")
tb = D.get("ticket_batch", {})
viol = 0
for prof in ("banker", "value", "jackpot", "fun"):
    for t in tb.get(prof, []):
        ids = [l.get("event_id") for l in t["legs"]]
        if len(set(ids)) != len(ids):
            viol += 1
check("0 violation anti-correlation", viol == 0, "%d violations" % viol)

print("=== 7. Backtest & paper trading coherents ===")
bt = D.get("backtest", {})
check("backtest.source present", bt.get("source") in ("logged", "elo_core"))
check("backtest.brier_model present", "brier_model" in bt)
pb = D.get("paper", {})
check("paper.bankroll numerique", isinstance(pb.get("bankroll"), (int, float)))
bets = pb.get("bets", [])
check("paper.bets liste", isinstance(bets, list))
# pl coherent pour les paris regles
bad = [b for b in bets if b.get("status") == "won" and b.get("pl", 0) <= 0]
check("paris gagnes ont pl>0", len(bad) == 0, "%d incoherents" % len(bad))

print("=== 8. App, marches & CLV ===")
html = open(os.path.join(ROOT, "app", "WorldcupKingOfBet.html"), encoding="utf-8").read()
for needle, name in [("function rPromos", "onglet Promos"), ("data-t=\"promos\"", "nav Promos"),
                     ("function buildSystem", "paris systeme"), ("function rGen", "generateur"),
                     ("p.disc", "affichage cartons/corners")]:
    check("app: " + name, needle in html)
check("closing_odds.json present", os.path.exists(os.path.join(ROOT, "data", "closing_odds.json")))
markets = set(l.get("market") for l in D.get("ticket_pool", []))
check("pool contient 1N2", "1N2" in markets)
check("pool contient buteur", "buteur" in markets)
_oc = json.load(open(os.path.join(ROOT, "data", "odds.json"), encoding="utf-8"))
_has_cc = any(isinstance(v, dict) and ((isinstance(v.get("cards"), dict) and v["cards"].get("est") is False) or (isinstance(v.get("corners"), dict) and v["corners"].get("est") is False)) for v in _oc.values())
if _has_cc:
    check("pool contient Cartons/Corners", bool({"Cartons", "Corners"} & markets), str(sorted(markets)))
else:
    check("pool Cartons/Corners (option — aucune cote réelle c/c actuellement)", True)

print("=== 9. Multi-sports (plugins + hub) ===")
sys.path.insert(0, ROOT)
try:
    from engine import sport as _spm
    import sports as _sp  # noqa
    avail = _spm.available()
    for k in ["football", "football_clubs", "tennis", "basketball", "nfl"]:
        check("sport enregistré: " + k, k in avail)
except Exception as e:
    check("registre des sports", False, str(e)[:60])
if "--no-run" not in sys.argv:
    subprocess.run([sys.executable, os.path.join(ROOT, "run_all.py")], capture_output=True, text=True, cwd=ROOT)
msp = os.path.join(ROOT, "app", "multisport_data.js")
if os.path.exists(msp):
    try:
        txt = open(msp, encoding="utf-8").read()
        MS = json.loads(txt[txt.index("=") + 1:].strip().rstrip(";"))
        check("multisport_data.js valide", True)
        check("multisport order >= 5", len(MS.get("order", [])) >= 5, str(MS.get("order")))
        for k in MS.get("order", []):
            sd = MS["sports"][k]
            check("hub sport %s (rows+tickets)" % k, bool(sd.get("rows")) and "tickets" in sd)
    except Exception as e:
        check("multisport_data.js valide", False, str(e)[:60])
else:
    check("multisport_data.js présent", False)
hub = os.path.join(ROOT, "app", "MultiSport.html")
check("hub MultiSport.html présent", os.path.exists(hub))
if os.path.exists(hub):
    ht = open(hub, encoding="utf-8").read()
    check("hub: vue Top cross-sport", "renderTop" in ht)
    check("hub: icônes 5 sports", all(x in ht for x in ["football_clubs", "nfl", "basketball", "tennis"]))

print()
print("================ RESULTAT ================")
print("Checks OK : %d | Echecs : %d" % (len(OKS), len(FAILS)))
if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("TOUS LES CHECKS PASSENT ✅")
