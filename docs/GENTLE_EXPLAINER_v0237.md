# v0.23.7 — Pourquoi Gentle est-il discret ?

**Objectif :** expliquer avec prudence pourquoi le rendu Gentle peut ne produire aucun repère ou sembler presque identique au mix Original.

## Fonctionnement
- L'interface Compare affiche une explication sous les mesures WAV, sans fenêtre secondaire ni bouton supplémentaire.
- Elle examine les mesures réelles du prémix Original (peak/RMS/crest), les différences PCM du Gentle et le seuil **physique en dB relu par le plugin** dans son rapport JUCE.
- Elle distingue : source mesurée sous le seuil, rendu strictement identique nécessitant vérification, effet mesurable et cas indéterminés.
- **Un crest factor bas ne prouve pas une compression préalable.** Le moteur le signale explicitement sans diagnostic catégorique.
- Aucun changement aux réglages FabFilter, aux WAV, aux repères, au lecteur commun, au cache de rendu ou à la validation ♥ de Mastering.
- Tous les fichiers de chanson, stems, WAV, analyses de session et configurations personnelles restent locaux, hors GitHub.

## Limites
Ce diagnostic n'est **ni un historique de gain reduction Pro-C 3**, ni une analyse du détecteur interne, ni un jugement de qualité musicale. Un seuil de crête PCM sous le seuil relu suggère peu d'action du compresseur, mais les modèles de détection, l'enveloppe, les transitoires et les effets de plugin peuvent modifier le résultat. Pas d'attribution définitive de cause.

## Test Windows
1. Installer la branche `feature/v0.23.7-gentle-explainer` et lancer `python scripts/desktop.py`.
2. Comparer Balanced + Original puis Gentle sur un morceau déjà en cache. Vérifier le nouveau texte « Pourquoi Gentle est-il discret? ».
3. Lorsque Gentle est quasi invisible, vérifier que le diagnostic ne proclame pas automatiquement « mix déjà compressé ».
4. Contrôler que le seuil en dB affiché provient du rapport Pro-C 3 et **non** de la valeur normalisée.
5. Vérifier que Firm continue à afficher ses marqueurs, que les neuf lecteurs restent synchronisés et que le ♥ reste nécessaire pour utiliser une version compressée au mastering.
6. Lancer `python -m unittest discover -s tests -p "test_gentle_explainer_v0237.py"`, puis les tests des versions précédentes.

La PR est empilée sur v0.23.6 et doit être validée sur l'environnement JUCE/Qt Windows avant fusion.
