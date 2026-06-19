# 🚀 Mettre King of Bet en ligne (GitHub Pages + cron automatique)

Objectif : un site **public**, gratuit, qui se **rafraîchit tout seul chaque jour** (cotes → modèle → CLV → calibration → re-déploiement) sans que ton PC soit allumé. La clé API reste **secrète** (jamais dans le site).

**Comment ça marche.** Ton dépôt GitHub contient le site (`app/`) + le moteur Python. Une **GitHub Action** tourne chaque jour à 06:00 UTC : elle récupère les cotes/résultats via l'API (clé lue dans un *secret*), relance le moteur (`cloud_refresh.py`), recommit l'état (bankroll, Elo, CLV…) et publie `app/` sur **GitHub Pages**. Le site est servi à `https://TON_PSEUDO.github.io/king-of-bet/`.

---

## Prérequis
- Un compte **GitHub** (gratuit) — https://github.com/signup
- **Git** installé sur ton PC — https://git-scm.com/download/win
- Ta clé **The Odds API** (déjà dans `data/api_config.json`, en local seulement).

---

## Étape 0 — Nettoyer le dossier `.git` (artefact à supprimer)
Un dossier `.git` incomplet a pu être créé. Dans le dossier du projet, supprime-le avant de commencer.

PowerShell (dans le dossier du projet) :
```powershell
Remove-Item -Recurse -Force .git
```
(ou Invite de commandes : `rmdir /s /q .git`)

## Étape 1 — Initialiser le dépôt **en local**
Dans le dossier `Worldcup king of bet` :
```bash
git init -b main
git add -A
git status            # vérifie que data/api_config.json n'apparaît PAS (il est gitignoré)
git commit -m "King of Bet — site + moteur + cron cloud"
```
> ✅ Le `.gitignore` exclut déjà `data/api_config.json` : ta clé ne partira jamais en ligne.

## Étape 2 — Créer le dépôt **sur GitHub**
1. https://github.com/new → Repository name : `king-of-bet` → **Public** → *Create repository* (ne coche rien d'autre).
2. Relie et pousse (remplace `TON_PSEUDO`) :
```bash
git remote add origin https://github.com/TON_PSEUDO/king-of-bet.git
git push -u origin main
```

## Étape 3 — Ajouter la clé API en **secret** (jamais dans le code)
Dans le dépôt GitHub : **Settings → Secrets and variables → Actions → New repository secret**
- Name : `ODDS_API_KEY` · Value : *(ta clé The Odds API)* → *Add secret*
- (optionnel) `APIFOOTBALL_KEY` : ta clé API-Football → permet de **régler les scores de la Coupe du Monde automatiquement**.
- (optionnel) onglet *Variables* → `FETCH_PROPS` = `1` pour récupérer aussi les props joueurs (consomme plus de quota).

## Étape 4 — Activer **GitHub Pages**
**Settings → Pages → Build and deployment → Source : `GitHub Actions`.** (Rien d'autre à régler.)

## Étape 5 — Lancer le déploiement
Onglet **Actions → "Refresh & Deploy King of Bet" → Run workflow** (ou attends le cron de 06:00 UTC).
À la fin, l'URL du site s'affiche dans le job *Deploy* :
```
https://TON_PSEUDO.github.io/king-of-bet/
```
La page d'accueil mène au **Hub multi-sports** et à l'**app Coupe du Monde**.

---

## Au quotidien
- **Automatique** : chaque jour à 06:00 UTC (~08:00 Paris) le site se met à jour seul. L'état (bankroll, Elo, CLV, calibration) est recommité par le bot `kob-bot`.
- **Forcer une maj** : Actions → Run workflow.
- **Récupérer l'état à jour en local** : `git pull` (le cloud devient la source de vérité du site ; tes tâches PC restent utiles pour le travail local mais ne sont plus nécessaires pour le site — tu peux les garder ou les désactiver pour éviter les doublons).
- **Modifier le code/design** : édite, puis `git add -A && git commit -m "..." && git push` → redéploiement automatique.

## Quota & coûts
- **Gratuit** : GitHub Pages + Actions (largement dans les limites pour 1 run/jour).
- **The Odds API** : offre gratuite = 500 requêtes/mois. Le cron par défaut fait ~3 appels/jour (WC + WNBA + NHL) ≈ 90/mois. Les props (`FETCH_PROPS=1`) ajoutent ~4 appels/jour — surveille le quota.

## Sécurité & conformité (important pour un site public)
- 🔒 **Ne committe jamais** `data/api_config.json` (déjà gitignoré). Si la clé a fuité, régénère-la sur the-odds-api.com.
- ⚖️ **Paris virtuels** : la page d'accueil et le hub affichent l'avertissement (bankroll fictive, aucun conseil de pari, jeu responsable, +18 et selon la légalité locale). Garde-le.
- 📜 **CGU The Odds API** : la rediffusion publique des cotes peut être encadrée — vérifie les conditions de ton offre avant de rendre les cotes brutes publiques. En cas de doute, n'affiche que les probabilités/edges du modèle, pas les cotes des bookmakers.

## Domaine personnalisé (optionnel)
Settings → Pages → *Custom domain* → saisis ton domaine, ajoute l'enregistrement DNS indiqué, coche *Enforce HTTPS*.

## Dépannage
- **Le déploiement échoue à "Deploy to Pages"** : vérifie que *Settings → Pages → Source = GitHub Actions*.
- **Données non rafraîchies** : vérifie que le secret `ODDS_API_KEY` existe (sinon le site se publie quand même avec les dernières données committées).
- **`git push` refusé** : connecte-toi (GitHub CLI `gh auth login`, ou un *Personal Access Token* comme mot de passe).
