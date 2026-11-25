# AI Mastering Lab — v0.23.2 diagnostic audio (étape 1)

**Important : ce paquet est un module de diagnostic, pas le correctif d'interface v0.23.2 complet.** Le ZIP source de v0.23.1 n'était pas accessible pendant cette session. Il serait dangereux de réécrire `unified_comparison.py` à l'aveugle. Aucun fichier existant de l'application n'est remplacé.

## Pourquoi ce module existe

L'utilisateur constate que l'onde change lors du choix Balanced / Vocal Focus / Punchy, mais **pas** lors du choix Original / Gentle / Firm, et entend peu ou pas de changement. Dans v0.23.1 la forme d'onde est alimentée par celle du *premix* (clé de mix), pas celle du WAV `(mix, compression)` réellement écouté. C'est une limite d'UI certaine. L'absence de différence **audible** peut être normale avec l'égalisation RMS ou révéler une absence de traitement/un mauvais routage, ce qui doit être **mesuré**.

## Installation sans risque

1. Fermer AI Mastering Lab.
2. Copier `src/mastering_lab/compression_diagnostics.py` dans le projet existant sous `src/mastering_lab` (ne supprimer aucun autre fichier).
3. Placer `run_diagnostics.py` à la racine du projet.
4. Dans PowerShell, depuis `E:\Losing Motivation EP\mastering tool\ai-mastering-lab-starter` :

```powershell
python run_diagnostics.py
```

Ou depuis n'importe quel dossier :

```powershell
python run_diagnostics.py --root "E:\Losing Motivation EP\mastering tool\ai-mastering-lab-starter"
```

Exige les neuf WAV générés et un cache `settings/pro_c3_unified_cache.json` valide. Si le cache n'existe pas, ouvrir Comparer une fois et attendre que les neuf rendus soient prêts. Si les WAV ne sont pas disponibles, l'outil échoue explicitement (sans produire de faux résultats).

## Sorties

- `settings/pro_c3_diagnostics/latest.json` : **neuf** profils audio avec environ 720 valeurs d'enveloppe par fichier; RMS, sample peak, crest factor et chemins exacts; **six** comparaisons null-test de Gentle/Firm par rapport à Original du même mix.
- `settings/pro_c3_diagnostics/latest.csv` : résumé pour inspecter rapidement si Pro-C 3 traite bien l'audio.
- Console : `identical=True/False`, `ΔRMS`, RMS de la différence null-test et éventuels avertissements.

**Mesures réelles des WAV**, non pas le compteur de gain reduction interne du plugin. Ces mesures ne sont PAS des LUFS ni une mesure GR dB (gain reduction). Le null-test n'est strictement interprétable que si les WAV sont alignés; la queue de rendu de Pro-C 3 est exclue par comparaison limitée à la longueur du prémix Original.

## Instructions de raccordement v0.23.2 dans le vrai code Windows

À réaliser **après inspection du dépôt actuel** :

1. Dans `src/mastering_lab/unified_comparison.py`, vérifier `_files[(mix, comp)]` et `_active = (mix, comp)` ; ajouter un worker `QThread` qui calcule/enregistre les profils *une seule fois après génération ou chargement du cache*. Ne jamais lire neuf chansons entières sur le thread UI.
2. Pour chaque changement de combinaison, utiliser le **profil en cache de la paire `_active`**, jamais l'enveloppe du seul `mix`. `WaveformStrip.setData(profiles[f'{mix}/{comp}']['envelope'])` **seulement après vérification de son format d'entrée**; adapter l'enveloppe au format attendu si nécessaire.
3. Alimenter trois petites valeurs sous le transport pour la paire active : `RMS dBFS`, `sample peak dBFS`, `crest factor dB`. En bas, si comp != Original, afficher `Δ RMS` et `null-test difference RMS dBFS` par rapport à Original. Ne pas appeler cette différence « gain reduction » ni « LUFS ».
4. À chaque clic sur Original/Gentle/Firm, vérifier que le lecteur actif est exactement `_players[(mix, comp)]` et que les 8 autres sorties sont muettes. Aucun `setSource()`/`stop()`/`play()` lors du switch si les neuf sont déjà chargées.
5. Préserver le volume RMS optionnel, le cœur ♥ lié à la **paire** et `master_source()` approuvé. La forme d'onde doit représenter le WAV *brut* sélectionné, même si l'égalisation RMS change seulement le volume de sortie.
6. Tester Stop, fermeture de l'app, changement de chanson, invalidation du cache, lecture A/B/C sans retour à zéro. Cache invalide si source ou réglages Pro-C 3 ont changé.
7. Conserver les tests Windows avec des WAV connus identiques, Gentle atténué et Firm fortement atténué. Mettre un message de diagnostic si Firm et Original donnent `same_samples == true`.

### Précaution sur la cache

Le module lit seulement les fichiers référencés dans `settings/pro_c3_unified_cache.json` sous `settings/pro_c3_song_previews`, et ne modifie **aucun** WAV. Le cache actuel est basé sur chemins/tailles/dates; pour la production, ajouter l'identité des réglages VST, de la calibration et du renderer. Les différences spectrales ou de phase nécessitent des métriques supplémentaires.

## Tests effectués ici

`python -m unittest discover -s tests -v` : **6 tests réussis**, utilisant des WAV synthétiques et validant enveloppes, différences, identité, cache et refus du mono.

**Non testé :** PySide6/QtMultimedia, vrais fichiers de l'utilisateur, et vraie installation Pro-C 3 Windows. Une fois le dossier projet v0.23.1 fourni, intégrer le module à l'UI, vérifier en Windows, et livrer un patch v0.23.2 complet.
