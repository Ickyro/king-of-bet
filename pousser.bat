@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ==================================================
echo    KING OF BET - Envoi vers GitHub (Pages)
echo ==================================================
echo Dossier : %cd%
echo.

REM --- 1) Git installe ? ---
where git >nul 2>nul
if errorlevel 1 (
  echo [ERREUR] Git n'est pas installe.
  echo Telecharge-le ici : https://git-scm.com/download/win
  echo Puis relance ce script.
  pause & exit /b 1
)

REM --- 2) URL du depot (reutilise celle deja configuree si presente) ---
set "URL="
for /f "delims=" %%u in ('git config --get remote.origin.url 2^>nul') do set "URL=%%u"
if defined URL (
  echo Depot deja relie a : !URL!
) else (
  echo Cree d'abord un depot vide sur https://github.com/new  ^(nom: king-of-bet, Public^)
  set /p "URL=Colle l'URL du depot (ex https://github.com/TONPSEUDO/king-of-bet.git) : "
)
if not defined URL ( echo [ERREUR] Aucune URL fournie. & pause & exit /b 1 )

REM --- 3) Nettoyer un .git incomplet (sans commit) ---
if exist ".git" (
  git rev-parse --verify HEAD >nul 2>nul
  if errorlevel 1 (
    echo Suppression d'un .git incomplet...
    rmdir /s /q ".git"
  )
)

REM --- 4) Init si besoin ---
if not exist ".git" git init -b main >nul

REM --- 5) Identite git si absente ---
git config user.email >nul 2>nul || git config user.email "vazzopardi06@gmail.com"
git config user.name  >nul 2>nul || git config user.name "Vince"

REM --- 6) Ajout des fichiers + securite : la cle ne doit JAMAIS partir ---
git add -A
git ls-files --error-unmatch data/api_config.json >nul 2>nul && (
  echo [ALERTE] data/api_config.json etait suivi : retrait du suivi.
  git rm --cached data/api_config.json >nul
)

REM --- 7) Commit ---
git commit -m "King of Bet - mise a jour" 1>nul 2>nul || echo (Rien de nouveau a committer.)

REM --- 8) Remote + push ---
git remote get-url origin >nul 2>nul && (git remote set-url origin "!URL!") || (git remote add origin "!URL!")
git branch -M main
echo.
echo Envoi vers !URL! ...
echo (Si on demande un identifiant : connecte-toi a GitHub dans la fenetre, ou utilise un token.)
git push -u origin main
if errorlevel 1 (
  echo.
  echo [ECHEC] Le push a echoue. Verifie l'URL et ta connexion GitHub, puis relance.
  pause & exit /b 1
)

echo.
echo ==================================================
echo   OK ! Il reste 2 reglages sur GitHub :
echo   1) Settings ^> Secrets and variables ^> Actions
echo      -^> New secret : ODDS_API_KEY = ta cle The Odds API
echo   2) Settings ^> Pages ^> Source : GitHub Actions
echo   Le site sortira sur https://TONPSEUDO.github.io/king-of-bet/
echo ==================================================
pause
