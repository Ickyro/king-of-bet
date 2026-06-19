# -*- coding: utf-8 -*-
"""
safe_update.py — wrapper STABILISATEUR du pipeline.

1. Sauvegarde data/*.json + app/app_data.js dans data/_backups/<timestamp>/.
2. Lance run_worldcup.py.
3. Lance selftest.py --no-run (valide les outputs SANS relancer le moteur).
4. Si le moteur ou le selftest echoue -> RESTAURE le backup (rollback) et sort en code 1.
   Sinon -> garde les 5 derniers backups (prune) et sort en code 0.

Les taches planifiees doivent appeler `python safe_update.py` au lieu de
`python run_worldcup.py` : ca blinde contre une ecriture tronquee ou un agent
qui plante en cours de route (jamais de data/ corrompu publie).
"""
import os
import sys
import glob
import json
import shutil
import subprocess
import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
APP = os.path.join(ROOT, "app", "app_data.js")
BKROOT = os.path.join(DATA, "_backups")
KEEP = 5


def _files():
    fs = glob.glob(os.path.join(DATA, "*.json"))
    if os.path.exists(APP):
        fs.append(APP)
    return fs


def backup():
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(BKROOT, ts)
    os.makedirs(dst, exist_ok=True)
    for f in _files():
        shutil.copy2(f, os.path.join(dst, os.path.basename(f)))
    return dst


def restore(src):
    for f in glob.glob(os.path.join(src, "*.json")):
        shutil.copy2(f, os.path.join(DATA, os.path.basename(f)))
    appbk = os.path.join(src, "app_data.js")
    if os.path.exists(appbk):
        shutil.copy2(appbk, APP)


def prune():
    baks = sorted(glob.glob(os.path.join(BKROOT, "*")))
    for old in baks[:-KEEP]:
        shutil.rmtree(old, ignore_errors=True)


def main():
    os.makedirs(BKROOT, exist_ok=True)
    bk = backup()
    print("Backup -> %s" % bk)
    r1 = subprocess.run([sys.executable, os.path.join(ROOT, "run_worldcup.py")],
                        capture_output=True, text=True, cwd=ROOT)
    ok_run = r1.returncode == 0 and "OK ->" in r1.stdout
    # rafraichir le hub multi-sports AVANT le selftest (sinon section 9 voit un fichier perime)
    subprocess.run([sys.executable, os.path.join(ROOT, "run_all.py")], capture_output=True, text=True, cwd=ROOT)
    r2 = subprocess.run([sys.executable, os.path.join(ROOT, "selftest.py"), "--no-run"],
                        capture_output=True, text=True, cwd=ROOT)
    ok_test = r2.returncode == 0
    if not (ok_run and ok_test):
        restore(bk)
        print("!!! ECHEC (moteur ok=%s, selftest ok=%s) -> ROLLBACK depuis %s" % (ok_run, ok_test, bk))
        print("--- run_worldcup stderr ---\n" + (r1.stderr or "")[-400:])
        print("--- selftest tail ---\n" + (r2.stdout or "")[-400:])
        sys.exit(1)
    prune()
    print(r1.stdout.strip().splitlines()[-1] if r1.stdout.strip() else "run OK")
    print("SAFE-UPDATE OK (backup conserve, %d backups gardes)" % KEEP)


if __name__ == "__main__":
    main()
