"""Visible, explicit premix feedback; no audio or automatic votes are written."""
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox

from .preference_learning import VARIANTS, preference_path, save_choice
from .mix_comparison import VARIANT_LABELS


COPY = {
    'en': {
        'title': 'Your ears teach the next pass',
        'hint': 'Select and listen to each Original premix using the player above. Rate all three: 1 = dislike, 5 = love. These scores concern the mix, before compression or EQ trials.',
        'select': 'Select', 'unrated': 'Not rated',
        'save': 'Save ratings and use my favorite',
        'wait': 'Waiting for measured mixes. Ratings are saved locally and guide future recommendations and Gen 2 proposals; they do not train the model itself.',
        'ready': 'Rate each version, then save. If top scores tie, select your favorite among them.',
        'saved': 'Saved ({count} sessions). Favorite: {mix}. Your ratings will guide the next AI evaluation and Gen 2 proposal. Originals are unchanged.',
        'tie': 'Select one of the highest-rated mixes to resolve the tie.',
        'incomplete': 'Give each premix a score from 1 to 5 before saving.',
        'error': 'Could not save ratings: {error}',
    },
    'fr': {
        'title': 'Tes oreilles guident la prochaine passe',
        'hint': 'Sélectionne et écoute chaque prémix Original avec le lecteur ci-dessus. Note les trois : 1 = je n’aime pas, 5 = j’adore. Ces notes portent sur le mix avant compression ou essais EQ.',
        'select': 'Sélectionner', 'unrated': 'Sans note',
        'save': 'Enregistrer les notes et utiliser mon favori',
        'wait': 'En attente des mesures. Les notes restent locales et guident les recommandations et propositions Gen 2; elles ne réentraînent pas le modèle.',
        'ready': 'Note chaque version, puis enregistre. En cas d’égalité, sélectionne ton favori parmi les mieux notées.',
        'saved': 'Enregistré ({count} sessions). Favori : {mix}. Tes notes guideront la prochaine évaluation IA et proposition Gen 2. Les originaux sont intacts.',
        'tie': 'Sélectionne un des mixages les mieux notés pour départager l’égalité.',
        'incomplete': 'Donne une note de 1 à 5 à chaque prémix avant d’enregistrer.',
        'error': 'Impossible d’enregistrer : {error}',
    },
}


class MixRatingPanel(QFrame):
    selected = Signal(str)
    saved = Signal(str)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.language = 'fr'
        self.session = None
        self.metrics = None
        self.favorite = None
        self.suggested = None
        self.song = ''
        self.setObjectName('mixRatings')
        self.setStyleSheet('QFrame#mixRatings {background:#172630;border:1px solid #34564f;border-radius:10px;}'
                          'QSpinBox {padding:8px;background:#192231;border:1px solid #425169;border-radius:6px;}'
                          'QPushButton:checked {border:1px solid #73e2bf;}')
        layout = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setStyleSheet('font-weight:700;font-size:16px;')
        layout.addWidget(self.title)
        self.hint = QLabel(); self.hint.setWordWrap(True); layout.addWidget(self.hint)
        row = QHBoxLayout(); layout.addLayout(row)
        self.scores = {}; self.selectors = {}
        for key in VARIANTS:
            column = QVBoxLayout(); row.addLayout(column)
            select = QPushButton(VARIANT_LABELS[key]); select.setCheckable(True)
            select.clicked.connect(lambda checked=False, k=key: self.choose(k))
            column.addWidget(select); self.selectors[key] = select
            score = QSpinBox(); score.setRange(0, 5)
            score.setAccessibleName(VARIANT_LABELS[key] + ' / 5')
            score.valueChanged.connect(self._edited)
            column.addWidget(score); self.scores[key] = score
        self.save_button = QPushButton(); self.save_button.setObjectName('primary')
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self._status_key = 'wait'; self._status_args = {}
        self.set_language('fr')
        self.reset()

    def message(self, key, **values):
        self._status_key, self._status_args = key, values
        self.status.setText(COPY[self.language][key].format(**values))

    def set_language(self, language):
        self.language = language if language in COPY else 'fr'
        texts = COPY[self.language]
        self.title.setText(texts['title']); self.hint.setText(texts['hint'])
        self.save_button.setText(texts['save'])
        for key, score in self.scores.items():
            score.setSpecialValueText(texts['unrated'])
            self.selectors[key].setText(texts['select'] + ' · ' + VARIANT_LABELS[key])
        self.message(self._status_key, **self._status_args)

    def reset(self):
        self.session = self.metrics = self.favorite = None
        for key, score in self.scores.items():
            score.setValue(0); score.setEnabled(False)
            self.selectors[key].setChecked(False); self.selectors[key].setEnabled(False)
        self.save_button.setEnabled(False)
        self.message('wait')

    def set_session(self, report, metrics, suggested=None, song=''):
        if not isinstance(metrics, dict) or set(metrics) != set(VARIANTS):
            return
        self.session = str(Path(report).resolve()); self.metrics = metrics
        self.suggested, self.song = suggested, song
        for key, score in self.scores.items():
            score.setEnabled(True); self.selectors[key].setEnabled(True)
        self.save_button.setEnabled(True); self.message('ready')

    def choose(self, key):
        self.favorite = key
        for variant, button in self.selectors.items():
            button.setChecked(variant == key)
        self.selected.emit(key)

    def _edited(self, *_):
        if self.metrics:
            self.save_button.setEnabled(True)
            self.message('ready')

    def save(self):
        if not self.metrics or not self.session:
            self.message('wait')
            return False
        ratings = {key: score.value() for key, score in self.scores.items()}
        if not all(ratings.values()):
            self.message('incomplete'); return False
        winners = [key for key, value in ratings.items() if value == max(ratings.values())]
        selected = winners[0] if len(winners) == 1 else self.favorite
        if selected not in winners:
            self.message('tie'); return False
        try:
            count = save_choice(preference_path(self.root), selected=selected,
                                metrics=self.metrics, ratings=ratings, session=self.session,
                                ai_suggested=self.suggested, song=self.song)
        except (OSError, ValueError, TypeError) as exc:
            self.message('error', error=str(exc)); return False
        self.choose(selected)
        self.save_button.setEnabled(False)
        self.message('saved', count=count, mix=VARIANT_LABELS[selected])
        self.saved.emit(selected)
        return True
