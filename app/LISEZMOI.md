# 🖥️ App Worldcup King of Bet — mode d'emploi

## Lancer l'app (2 options)

**Option .exe (demandée)** : double-clique sur `creer_exe.bat` → il compile `WorldcupKingOfBet.exe` avec le compilateur C# **déjà intégré à Windows** (aucune installation). Ensuite double-clique sur le .exe (tu peux en faire un raccourci Bureau : clic droit → Envoyer vers → Bureau).

**Option directe** : double-clique sur `Lancer_App.bat` ou sur `WorldcupKingOfBet.html`.

## Les 7 onglets

1. **📊 Dashboard** — les 3 tickets du jour (sûr/équilibré/fun) avec mises calculées sur TA bankroll (modifiable en haut à droite), et les prochains matchs.
2. **📅 Pronostics** — les ~70 matchs restants : probabilités 1N2 du moteur v2, cotes justes, xG, Over 2.5, BTTS, scores les plus probables, cotes bookmaker. Filtres par date et groupe.
3. **🏆 Qualifications** — probabilités de qualification des 48 équipes (20 000 simulations Monte-Carlo, tiebreakers FIFA).
4. **💎 Values & Buteurs** — value bets 1N2 validés par les garde-fous, marché buteurs (P modèle vs cote), et anomalies détectées.
5. **⚔️ Matchups** — pour chaque match : comparaison poste par poste (barres), avantages détectés par le moteur de facteurs, styles, forces/faiblesses, temps forts.
6. **🎰 Ticket Opti** — TON générateur : choisis cote cible, nombre de sélections, marchés (1N2/nuls/buteurs), date, filtres (matchup fort, éviter équipes publiques, inclure une équipe/un joueur) → l'app calcule le combiné optimal selon les probabilités du moteur (mode Sécurité = proba max, mode Value = espérance max), avec ajout direct dans Mes Paris.
7. **🎫 Mes Paris** — ton tracker : ajoute tes paris (ou les tickets Opti), marque gagné/perdu, suis ton P/L, ROI et la courbe de bankroll + la section 🤖 de l'agent parieur automatique. Sauvegarde automatique dans le navigateur + bouton Export JSON.

## Mettre à jour les données (chaque jour)
Demande à Claude : « mets à jour le modèle » → il inscrit les résultats, rafraîchit les cotes, relance `model/wc_model_v2.py` → le fichier `app_data.js` est régénéré → rouvre l'app (F5).
