# -*- coding: utf-8 -*-
"""
cloud_refresh.py — pipeline de RAFRAÎCHISSEMENT pour l'hébergement (GitHub Actions).

Contrairement au runner Cowork (sans réseau Python), un job CI a un accès réseau
normal : on récupère donc les cotes/résultats EN DIRECT via urllib (clé en variable
d'env), on relance le moteur + run_all + calibrate, et le workflow publie app/.

Secrets attendus (variables d'env du job) :
  ODDS_API_KEY        (obligatoire)  — The Odds API
  APIFOOTBALL_KEY     (optionnel)    — API-Football, pour régler les scores WC
  FETCH_PROPS=1       (optionnel)    — récupère aussi les player props WNBA (quota +)

Robuste : chaque étape est isolée ; une erreur (quota, ligue vide) n'interrompt pas
la publication. Aucune clé n'est jamais écrite dans app/.
"""
import os
import sys
import json
import subprocess
import urllib.request
import urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
KEY = os.environ.get("ODDS_API_KEY")
if not KEY:
    try:
        KEY = json.load(open(os.path.join(ROOT, "data", "api_config.json"), encoding="utf-8")).get("odds_api_key")
    except Exception:
        KEY = None
BOOKS = "pinnacle,draftkings,fanduel"


def _scrub(msg):
    """Masque la clé API dans tout message (logs CI publics)."""
    m = str(msg)
    return m.replace(KEY, "***") if KEY else m


def run(cmd, env=None):
    print("·", " ".join(cmd))
    e = dict(os.environ)
    if env:
        e.update(env)
    try:
        r = subprocess.run([sys.executable] + cmd, cwd=ROOT, env=e, capture_output=True, text=True, timeout=300)
        out = (r.stdout or "").strip().splitlines()
        if out:
            print("   " + out[-1])
        if r.returncode != 0 and r.stderr:
            print("   ! " + _scrub(r.stderr.strip().splitlines()[-1]))
    except Exception as ex:
        print("   ! échec:", _scrub(str(ex))[:120])


def fetch(url, dest):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "kob-cloud/1.0"})
        data = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
        open(dest, "w", encoding="utf-8").write(data)
        n = data.count('"id"')
        print("   fetched -> %s (~%d events)" % (dest, n))
        return True
    except Exception as ex:
        print("   ! fetch KO:", _scrub(str(ex))[:120])
        return False


def odds_url(sport, markets="h2h,totals"):
    return ("https://api.the-odds-api.com/v4/sports/%s/odds?apiKey=%s&markets=%s"
            "&oddsFormat=decimal&bookmakers=%s" % (sport, KEY, markets, BOOKS))


def main():
    if not KEY:
        print("ODDS_API_KEY absent — on régénère quand même le site avec les données existantes.")
    tmp = "/tmp"
    # 1) Coupe du Monde : cotes (urllib direct via ODDS_API_KEY) + résultats si API-Football
    if KEY:
        run(["fetch_odds.py"])              # fetch_odds.py lit ODDS_API_KEY et appelle l'API en direct
    if os.environ.get("APIFOOTBALL_KEY") or _cfg("apifootball_key"):
        run(["fetch_results.py"])
    # 2) Sports live multi-books (line shopping)
    live = [("basketball_wnba", "data_wnba"), ("icehockey_nhl", "data_nhl")]
    if KEY:
        for sk, dd in live:
            f = os.path.join(tmp, dd + ".json")
            if fetch(odds_url(sk), f):
                run(["fetch_live.py", "odds", "--data", dd, "--from", f])
                run(["fetch_live.py", "close", "--data", dd, "--from", f])  # snapshot CLV
        # 3) Props WNBA (optionnel, coûte du quota)
        if os.environ.get("FETCH_PROPS") == "1":
            ev = os.path.join(tmp, "wnba_events.json")
            if fetch("https://api.the-odds-api.com/v4/sports/basketball_wnba/events?apiKey=%s" % KEY, ev):
                try:
                    for e in json.load(open(ev, encoding="utf-8"))[:4]:
                        pf = os.path.join(tmp, "props_%s.json" % e["id"][:8])
                        u = ("https://api.the-odds-api.com/v4/sports/basketball_wnba/events/%s/odds?apiKey=%s"
                             "&markets=player_points&oddsFormat=decimal&bookmakers=draftkings,fanduel" % (e["id"], KEY))
                        if fetch(u, pf):
                            run(["fetch_live.py", "props", "--data", "data_wnba", "--from", pf])
                except Exception as ex:
                    print("   ! props KO:", str(ex)[:100])
    # 4) Moteur WC + hub + calibration
    run(["run_worldcup.py"])
    run(["run_all.py"])
    run(["calibrate.py"])
    run(["run_all.py"])   # re-export pour intégrer calibration.json fraîche
    print("OK -> app/ prêt à publier")


def _cfg(k):
    try:
        return json.load(open(os.path.join(ROOT, "data", "api_config.json"), encoding="utf-8")).get(k)
    except Exception:
        return None


if __name__ == "__main__":
    main()
