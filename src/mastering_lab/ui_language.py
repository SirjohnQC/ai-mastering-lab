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
 }
}


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
