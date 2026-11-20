import os
import shutil
import sys

from calibre.utils.config import JSONConfig, config_dir
from qt.core import QApplication, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, Qt, QWidget

from calibre_plugins.kindle_vocab_anki import i18n, translators
from calibre_plugins.kindle_vocab_anki.cache import TranslationCache
from calibre_plugins.kindle_vocab_anki.i18n import N_, _

PROVIDERS = (
    ('wiktionary', N_('Wiktionnaire (hors ligne)')),
    ('deepl', 'DeepL'),
    ('claude', 'Claude'),
    ('ollama', N_('Ollama (local)')),
)
LANGUAGE_CHOICES = (
    ('auto', N_('Comme calibre')),
    ('fr', 'Français'),
    ('en', 'English'),
)

LLM_PROVIDERS = tuple(provider for provider in PROVIDERS if provider[0] in ('claude', 'ollama'))

prefs = JSONConfig('plugins/kindle_vocab_anki')
prefs.defaults['target_lang'] = 'fr'
prefs.defaults['provider'] = 'wiktionary'
prefs.defaults['extract_provider'] = 'claude'
prefs.defaults['deck_name'] = 'Kindle vocabulary'
prefs.defaults['reverse'] = True
prefs.defaults['audio'] = True
prefs.defaults['wikimedia_contact'] = ''
prefs.defaults['export_format'] = 'apkg'
prefs.defaults['ankiweb_user'] = ''
prefs.defaults['ankiweb_hkey'] = ''
prefs.defaults['ankiweb_endpoint'] = ''
prefs.defaults['claude_api_key'] = ''
prefs.defaults['claude_model'] = translators.DEFAULT_CLAUDE_MODEL
prefs.defaults['deepl_api_key'] = ''
prefs.defaults['ollama_url'] = translators.OLLAMA_URL
prefs.defaults['ollama_model'] = ''
prefs.defaults['vocab_db'] = ''
prefs.defaults['clippings'] = ''
prefs.defaults['language'] = 'auto'


def apply_language():
    from calibre.utils.localization import get_lang

    i18n.set_language(i18n.resolve(prefs['language'], get_lang()))


apply_language()


def data_dir():
    path = os.path.join(config_dir, 'plugins', 'kindle_vocab_anki')
    os.makedirs(path, exist_ok=True)
    return path


def make_cache():
    return TranslationCache(os.path.join(data_dir(), 'translations.sqlite3'))


def make_pronunciations():
    from calibre_plugins.kindle_vocab_anki.audio import Pronunciations

    return Pronunciations(os.path.join(data_dir(), 'audio'), make_cache(), contact=prefs['wikimedia_contact'].strip())


def make_ankiweb():
    import inspect

    from calibre_plugins.kindle_vocab_anki import ankiweb_helper
    from calibre_plugins.kindle_vocab_anki.ankiweb import AnkiWeb

    return AnkiWeb(data_dir(), inspect.getsource(ankiweb_helper), [find_calibre_debug(), '-e'])


def find_calibre_debug():
    # Le Python de calibre exécute la synchronisation : aucun autre interpréteur n'est requis sur la machine.
    name = 'calibre-debug.exe' if sys.platform == 'win32' else 'calibre-debug'
    directories = (getattr(sys, 'executables_location', ''), os.path.dirname(sys.executable), os.path.dirname(sys.argv[0]))
    for directory in directories:
        path = os.path.join(directory, name)
        if directory and os.path.isfile(path):
            return path
    return shutil.which('calibre-debug') or name


def make_translator(provider):
    if provider == 'claude':
        return translators.ClaudeTranslator(prefs['claude_api_key'].strip(), prefs['claude_model'].strip())
    if provider == 'deepl':
        return translators.DeepLTranslator(prefs['deepl_api_key'].strip())
    if provider == 'ollama':
        return translators.OllamaTranslator(prefs['ollama_model'].strip(), prefs['ollama_url'].strip())
    return translators.WiktionaryTranslator(os.path.join(data_dir(), 'dictionaries'))


class ConfigWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QFormLayout(self)

        self.language = QComboBox()
        for key, label in LANGUAGE_CHOICES:
            self.language.addItem(_(label), key)
        self.language.setCurrentIndex(max(self.language.findData(prefs['language']), 0))
        self.claude_api_key = self._secret(prefs['claude_api_key'])
        self.claude_model = QLineEdit(prefs['claude_model'])
        self.deepl_api_key = self._secret(prefs['deepl_api_key'])
        self.ollama_url = QLineEdit(prefs['ollama_url'])
        self.ollama_model = QComboBox()
        self.ollama_model.setEditable(True)
        self.ollama_model.setCurrentText(prefs['ollama_model'])
        self.ollama_status = QLabel('')
        self.wikimedia_contact = QLineEdit(prefs['wikimedia_contact'])
        self.wikimedia_contact.setPlaceholderText(_('Adresse e-mail ou page web'))

        refresh = QPushButton(_('Lister les modèles'))
        refresh.clicked.connect(self.refresh_ollama_models)
        ollama_row = QHBoxLayout()
        ollama_row.addWidget(self.ollama_model, 1)
        ollama_row.addWidget(refresh)

        layout.addRow(_('Langue du plugin'), self.language)
        language_help = QLabel(_('Prise en compte à la prochaine ouverture de la fenêtre ; le bouton de la barre '
                                 'd\'outils change au redémarrage de calibre.'))
        language_help.setWordWrap(True)
        layout.addRow('', language_help)
        layout.addRow(_('Clé d\'API Claude'), self.claude_api_key)
        layout.addRow(_('Modèle Claude'), self.claude_model)
        layout.addRow(_('Clé d\'API DeepL'), self.deepl_api_key)
        layout.addRow(_('Adresse d\'Ollama'), self.ollama_url)
        layout.addRow(_('Modèle Ollama'), ollama_row)
        layout.addRow('', self.ollama_status)
        layout.addRow(_('Contact pour Wikimedia'), self.wikimedia_contact)
        contact_help = QLabel(_('Les prononciations viennent de Wikimedia, qui refuse souvent les téléchargements des '
                                'programmes sans contact : ce contact est joint à chaque requête.'))
        contact_help.setWordWrap(True)
        layout.addRow('', contact_help)
        layout.addRow(QLabel(_('Les clés sont enregistrées en clair dans le dossier de configuration de calibre.')))

    @staticmethod
    def _secret(value):
        field = QLineEdit(value)
        field.setEchoMode(QLineEdit.EchoMode.Password)
        return field

    def refresh_ollama_models(self):
        current = self.ollama_model.currentText()
        self.ollama_status.setText(_('Recherche des modèles…'))
        self.ollama_status.repaint()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            models = translators.list_ollama_models(self.ollama_url.text().strip())
        except translators.TranslationError as error:
            self.ollama_status.setText(str(error))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.ollama_model.clear()
        self.ollama_model.addItems(models)
        self.ollama_model.setCurrentText(current or (models[0] if models else ''))
        self.ollama_status.setText(_('{count} modèle(s) installé(s)').format(count=len(models)))

    def save_settings(self):
        prefs['claude_api_key'] = self.claude_api_key.text().strip()
        prefs['claude_model'] = self.claude_model.text().strip() or translators.DEFAULT_CLAUDE_MODEL
        prefs['deepl_api_key'] = self.deepl_api_key.text().strip()
        prefs['ollama_url'] = self.ollama_url.text().strip() or translators.OLLAMA_URL
        prefs['ollama_model'] = self.ollama_model.currentText().strip()
        prefs['wikimedia_contact'] = self.wikimedia_contact.text().strip()
        prefs['language'] = self.language.currentData()
        apply_language()
