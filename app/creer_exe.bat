@echo off
REM ============================================================
REM  Worldcup King of Bet - generateur du .exe
REM  Double-clique sur ce fichier : il compile launcher.cs avec
REM  le compilateur C# integre a Windows (.NET Framework, deja
REM  present sur Windows 10/11 - aucune installation requise).
REM ============================================================
cd /d "%~dp0"
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" (
    echo [ERREUR] Compilateur C# introuvable. Utilise Lancer_App.bat a la place.
    pause
    exit /b 1
)
"%CSC%" /nologo /target:winexe /out:"%~dp0WorldcupKingOfBet.exe" "%~dp0launcher.cs"
if exist "%~dp0WorldcupKingOfBet.exe" (
    echo.
    echo  [OK] WorldcupKingOfBet.exe cree dans le dossier app !
    echo  Double-clique dessus pour ouvrir ton dashboard.
    echo  Tu peux aussi creer un raccourci sur le Bureau :
    echo  clic droit sur le .exe ^> Envoyer vers ^> Bureau.
) else (
    echo [ERREUR] La compilation a echoue. Utilise Lancer_App.bat a la place.
)
echo.
pause
