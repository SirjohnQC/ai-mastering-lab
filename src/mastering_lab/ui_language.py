"""Small, persistent FR/EN UI dictionary for the guided Auto Studio screens.

User audio and settings never leave the local PC. UI translations do not
change internal mix/compression identifiers or Hermes prompt formats.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings

TRANSLATIONS = {
 'fr': {
  'language':'Langue', 'advanced':'⚙ Avancé', 'album':'💿 Mode album', 'references':'♫ Références',
  'intro':'Charge tes stems, lance Auto Produce, compare les mixages et approuve avant le mastering.',
  'import':'Importer','produce':'Produire','compare':'Comparer','master':'Mastering',
  'mix':'1. Mixage','compression':'2. Compression · Pro-C 3','recommend':'3. Recommandation IA · Compression',
  'original':'Original\nAucune','gentle':'Gentle\nDouce','firm':'Firm\nForte',
  'player':'Lecteur commun','play':'▶ Écouter','stop':'■ Stop',
  'journey':'Choisis ton mix → compare la compression → écoute → ♥ → Mastering.',
  'diagnostics_closed':'⚙ Diagnostics · Avancé (afficher)',
  'diagnostics_open':'⚙ Diagnostics · Avancé (masquer)',
  'options_closed':'⚙ Options facultatives · Avancé (afficher)',
  'options_open':'⚙ Options facultatives · Avancé (masquer)',
  'natural':'Naturel','balanced':'Équilibré','punchy':'Énergique',
  'listen_suggestion':'▶ Écouter la suggestion (sans approuver)',
  'master_choice':'Choix pour Mastering :',
  'equal_volume':'Égaliser le volume à l’écoute (RMS approximatif)',
  'continue':'→ Continuer vers Mastering — {mix}',
  'missing_source':'Aucun WAV valide pour le mix sélectionné. Retourne dans Comparer pour préparer les versions.',
  'busy':'Attends la fin de la préparation audio avant de continuer.',
  'master_error':'Impossible d’ouvrir Mastering : {error}',
  'master_ready':'Prêt à créer le master. Clique sur AUTO MASTER pour démarrer.',
  'source':'Source : {name} ({variant})\nAuto Master technique : cible −14 LUFS, plafond −1 dBTP, PCM 24 bits.',
  'no_approval':'Aucune compression approuvée. Original sera utilisé pour le mastering.',
  'hint':'Les repères roses signalent les passages à comparer.',
  'change_music':'↻ Changer de musique', 'auto_produce':'✦ AUTO PRODUCE',
  'pick_stems':'＋ Choisir des stems','pick_folder':'▣ Charger un dossier',
  'song_title':'Nom de la chanson (pour le WAV final)',
  'master_headline':'Ton mix, ton master.',
  'master_initial':'Sélectionne un mixage sur Comparer pour commencer.',
  'master_title':'Nom de la chanson (nom du fichier exporté)',
  'master_review':'Écoute du master',
  'master_cancel':'Annuler Auto Master',
  'master_open':'📁 Ouvrir le fichier master',
  'master_preflight':'✓ Vérifier avant publication',
  'master_advanced':'Réglages avancés et références →',
  'gen2':'✦ Améliorer avec Gen 2',
  'more':'Retouches avancées',
  'details':'Rapport et spectrogrammes',
  'disclaimer':'Ces trois fichiers sont des prémix et non des masters finaux.',
  'master_done':'✓ MASTER DÉJÀ CRÉÉ',
  'master_action':'✦ AUTO MASTER',
 },
 'en': {
  'language':'Language', 'advanced':'⚙ Advanced', 'album':'💿 Album mode', 'references':'♫ References',
  'intro':'Load your stems, run Auto Produce, compare mixes and approve a version before mastering.',
  'import':'Import','produce':'Produce','compare':'Compare','master':'Mastering',
  'mix':'1. Mix','compression':'2. Compression · Pro-C 3','recommend':'3. AI recommendation · Compression',
  'original':'Original\nNone','gentle':'Gentle\nLight','firm':'Firm\nStrong',
  'player':'Shared player','play':'▶ Play','stop':'■ Stop',
  'journey':'Choose a mix → compare compression → listen → ♥ → Mastering.',
  'diagnostics_closed':'⚙ Diagnostics · Advanced (show)',
  'diagnostics_open':'⚙ Diagnostics · Advanced (hide)',
  'options_closed':'⚙ Optional tools · Advanced (show)',
  'options_open':'⚙ Optional tools · Advanced (hide)',
  'natural':'Natural','balanced':'Balanced','punchy':'Energetic',
  'listen_suggestion':'▶ Audition recommendation (does not approve)',
  'master_choice':'Mastering selection:',
  'equal_volume':'Match listening volume (approximate RMS)',
  'continue':'→ Continue to Mastering — {mix}',
  'missing_source':'No valid WAV for the selected mix. Prepare your versions in Compare.',
  'busy':'Audio preparation must finish before continuing.',
  'master_error':'Could not open Mastering: {error}',
  'master_ready':'Ready to create the master. Click AUTO MASTER to begin.',
  'source':'Source: {name} ({variant})\nTechnical Auto Master: target −14 LUFS, ceiling −1 dBTP, 24-bit PCM.',
  'no_approval':'No compression approved. The original premix will be mastered.',
  'hint':'Pink markers highlight passages worth comparing.',
  'change_music':'↻ Change music','auto_produce':'✦ AUTO PRODUCE',
  'pick_stems':'＋ Select stems','pick_folder':'▣ Load folder',
  'song_title':'Song name (for final WAV)',
  'master_headline':'Your mix, your master.',
  'master_initial':'Select a mix in Compare to begin.',
  'master_title':'Song name (export filename)',
  'master_review':'Master preview',
  'master_cancel':'Cancel Auto Master',
  'master_open':'📁 Open mastered file',
  'master_preflight':'✓ Pre-release check',
  'master_advanced':'Advanced settings and references →',
  'gen2':'✦ Improve with Gen 2',
  'more':'Advanced adjustments',
  'details':'Report and spectrograms',
  'disclaimer':'These three files are premixes, not final masters.',
  'master_done':'✓ MASTER ALREADY CREATED',
  'master_action':'✦ AUTO MASTER',
 }
}


# Additional guided workflow and diagnostics labels. A dictionary is used
# rather than translating arbitrary log text or model output on the fly.
TRANSLATIONS['fr'].update({
 'import_headline':'Ta musique, ton prochain mix.',
 'import_explanation':'Ajoute les pistes séparées d’une chanson, puis crée trois propositions de mixage. Pour plusieurs chansons ou un WAV stéréo, ouvre Mode album.',
 'selected_stems':'STEMS SÉLECTIONNÉS', 'no_stems':'Aucun stem chargé',
 'loaded_stems':'✓ {count} stems chargés · {label}',
 'producing_headline':'On s’occupe du mixage. 🎸', 'producing_wait':'Préparation…',
 'producing_safe':'Les stems originaux ne seront pas modifiés.',
 'cancel_production':'Annuler le traitement',
 'master_caution':'Première passe technique : loudness, true peak et WAV 24 bits. Les contrôles QC ne remplacent pas l’écoute humaine ni la cohérence d’un album complet.',
 'master_already':'✓ Master déjà créé. Aucun nouveau traitement nécessaire.',
 'master_starting':'Vérification de la source et du moteur audio…',
 'master_preflight_running':'Analyse du WAV exporté en cours…',
 'master_preflight_error':'Contrôle impossible : {error}',
 'master_stopped':'Mastering arrêté', 'master_cancelling':'Annulation demandée…',
 'missing_master_file':'Le fichier master n’est plus disponible.',
 'missing_master_input':'Sélectionne un mixage WAV avant Auto Master.',
 'master_cancelled':'Auto Master annulé. Les originaux sont intacts.',
 'source_none':'Aucun mixage disponible.',
 'compare_wait':'Préparation des 9 pistes ou récupération du cache… Aucun original modifié.',
 'compare_ready_cached':'9 combinaisons récupérées du cache.',
 'compare_ready_new':'9 combinaisons préparées avec Pro-C 3.',
 'compare_measure_ok':'Mesures calculées sur les WAV.',
 'compare_hermes_ok':'Hermes local : propositions disponibles.',
 'compare_pcm_fallback':'Conseiller PCM : propositions de repli.',
 'compare_heart_hint':'♥ approuve le choix pour Mastering.',
 'compare_advice_pending':'Analyse en attente. La suggestion ne modifie aucun son.',
 'compare_hermes_reason':'Suggestion d’Hermes basée sur les mesures PCM; vérifie à l’écoute.',
 'compare_pcm_reason':'Recommandation calculée à partir des mesures PCM; vérifie à l’écoute.',
 'compare_advice_heart':'Suggestion seulement : ♥ requis pour Mastering.',
 'compare_review_count':'✦ {count} passages à écouter — repères roses sur la forme d’onde.',
 'compare_no_markers':'Aucun passage particulièrement affecté : compare à l’oreille.',
 'compare_marker_title':'Repères roses : passages à comparer avec {variant}.',
 'compare_marker_none':'Aucun repère mesurable pour ce mix.',
 'compare_approval_default':'Aucune compression approuvée. Original utilisé par défaut.',
 'compare_approval_yes':'♥ {mix} + {variant} approuvé pour le prochain mastering.',
 'compare_advice_failed':'Analyse de compression interrompue. Corrige l’erreur ci-dessus, puis régénère les copies.',
 'compare_calibration_missing':'Calibration Pro-C 3 manquante. Dans Tools → Plugin Calibration — Pro-C 3, lance Grille multipoint Pro-C 3, puis régénère les copies.',
 'compare_render_fail':'Rendu impossible : {error}',
 'compare_audio_error':'Erreur de lecture audio : {error}',
 'compare_play_loading':'Chargement…',
 'compare_status_wait':'Les copies Pro-C 3 se préparent automatiquement dans Comparer.',
 'compare_diagnostics_notice':'Détails techniques disponibles dans Diagnostics · Avancé.',
 'compare_tech_note':'Les diagnostics PCM ne mesurent pas directement le gain reduction Pro-C 3.',
})
TRANSLATIONS['en'].update({
 'import_headline':'Your music, your next mix.',
 'import_explanation':'Add one song’s separate tracks, then create three mix options. For multiple songs or a stereo WAV, open Album Mode.',
 'selected_stems':'SELECTED STEMS', 'no_stems':'No stems loaded',
 'loaded_stems':'✓ {count} stems loaded · {label}',
 'producing_headline':'Mixing your song. 🎸', 'producing_wait':'Preparing…',
 'producing_safe':'Your original stems will not be modified.',
 'cancel_production':'Cancel processing',
 'master_caution':'First technical pass: loudness, true peak and 24-bit WAV. QC checks do not replace critical listening or full-album consistency.',
 'master_already':'✓ Master already created. No further processing required.',
 'master_starting':'Checking the source and audio engine…',
 'master_preflight_running':'Analyzing the exported WAV…',
 'master_preflight_error':'Pre-release check failed: {error}',
 'master_stopped':'Mastering stopped', 'master_cancelling':'Cancellation requested…',
 'missing_master_file':'The mastered file is no longer available.',
 'missing_master_input':'Choose a mix WAV before Auto Master.',
 'master_cancelled':'Auto Master cancelled. Originals are unchanged.',
 'source_none':'No mix available.',
 'compare_wait':'Preparing nine versions or loading cache… Originals are unchanged.',
 'compare_ready_cached':'Nine combinations loaded from cache.',
 'compare_ready_new':'Nine combinations prepared with Pro-C 3.',
 'compare_measure_ok':'Measurements calculated from WAV files.',
 'compare_hermes_ok':'Local Hermes: recommendations available.',
 'compare_pcm_fallback':'PCM advisor: fallback recommendations.',
 'compare_heart_hint':'♥ approves the selection for Mastering.',
 'compare_advice_pending':'Analysis pending. This suggestion does not change the audio.',
 'compare_hermes_reason':'Hermes suggestion based on PCM metrics; judge by listening.',
 'compare_pcm_reason':'Recommendation from PCM measurements; judge by listening.',
 'compare_advice_heart':'Suggestion only: ♥ required for Mastering.',
 'compare_review_count':'✦ {count} passages to review — pink markers on the waveform.',
 'compare_no_markers':'No significantly affected passages: compare by ear.',
 'compare_marker_title':'Pink markers: review passages against {variant}.',
 'compare_marker_none':'No measurable review markers for this mix.',
 'compare_approval_default':'No compression approved. Original used by default.',
 'compare_approval_yes':'♥ {mix} + {variant} approved for the next master.',
 'compare_advice_failed':'Compression analysis stopped. Resolve the error above, then regenerate the copies.',
 'compare_calibration_missing':'Pro-C 3 calibration missing. Open Tools → Plugin Calibration — Pro-C 3, run Grille multipoint Pro-C 3, then regenerate the copies.',
 'compare_render_fail':'Render failed: {error}',
 'compare_audio_error':'Audio playback error: {error}',
 'compare_play_loading':'Loading…',
 'compare_status_wait':'Pro-C 3 previews are prepared automatically when entering Compare.',
 'compare_diagnostics_notice':'Technical details are available under Diagnostics · Advanced.',
 'compare_tech_note':'PCM diagnostics do not directly measure Pro-C 3 gain reduction.',
})


TRANSLATIONS['fr'].update({
    'workflow_import': 'POUR COMMENCER  /  Choisis des stems ou un dossier. Auto Produce devient disponible après le chargement.',
    'workflow_ready': 'PRÊT À PRODUIRE  /  Vérifie les stems et le titre, puis lance Auto Produce. Les originaux restent intacts.',
    'workflow_produce': 'PRODUCTION  /  Préparation des mixages. Suis l’avancement ci-dessous; Annuler permet d’interrompre le traitement.',
    'workflow_compare': 'ÉCOUTE ET CHOISIS  /  Compare les mixages et la compression. Le cœur approuve une compression pour le mastering; sinon Original est utilisé.',
    'workflow_master': 'MASTER ET VÉRIFICATION  /  Lance Auto Master, écoute le résultat et consulte le contrôle qualité avant de récupérer le WAV.',
    'workflow_album': 'MODE ALBUM  /  Importe tes chansons, définis leur ordre et vérifie les masters. Importer te ramène au travail sur une chanson.',
})
TRANSLATIONS['en'].update({
    'workflow_import': 'START HERE  /  Choose stems or a folder. Auto Produce becomes available after your tracks load.',
    'workflow_ready': 'READY TO PRODUCE  /  Review your stems and song title, then run Auto Produce. Your originals stay untouched.',
    'workflow_produce': 'PRODUCING  /  Preparing your mixes. Follow progress below; use Cancel to interrupt processing.',
    'workflow_compare': 'LISTEN AND CHOOSE  /  Compare mixes and compression. The heart approves compression for mastering; otherwise Original is used.',
    'workflow_master': 'MASTER AND CHECK  /  Run Auto Master, listen to the result and review quality checks before collecting your WAV.',
    'workflow_album': 'ALBUM MODE  /  Import songs, set their order and check the masters. Import returns to your single-song session.',
})


def get_language() -> str:
    value = QSettings('AI Mastering Lab', 'Auto Studio').value('language', 'fr')
    return value if value in TRANSLATIONS else 'fr'


def set_language(language: str) -> None:
    if language not in TRANSLATIONS:
        raise ValueError('Unsupported language.')
    QSettings('AI Mastering Lab', 'Auto Studio').setValue('language', language)


def tr(language: str, key: str, **values) -> str:
    strings = TRANSLATIONS.get(language, TRANSLATIONS['fr'])
    return strings.get(key, TRANSLATIONS['fr'].get(key, key)).format(**values)
