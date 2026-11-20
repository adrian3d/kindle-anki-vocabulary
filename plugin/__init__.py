from calibre.customize import InterfaceActionBase
from calibre.utils.localization import get_lang


class KindleVocabAnkiPlugin(InterfaceActionBase):
    name = 'Kindle Vocab to Anki'
    # La liste des extensions appartient à calibre : sa description suit la langue de calibre, pas le réglage du plugin.
    description = (
        'Vocabulaire et surlignages de la Kindle : filtres par langue, livre et date, traduction, export Anki et Markdown'
        if get_lang().lower().startswith('fr') else
        'Kindle vocabulary and highlights: filters by language, book and date, translation, Anki and Markdown export'
    )
    supported_platforms = ['windows', 'osx', 'linux']
    author = 'Adrian Vaucoret'
    version = (1, 1, 0)
    minimum_calibre_version = (7, 0, 0)
    actual_plugin = 'calibre_plugins.kindle_vocab_anki.action:KindleVocabAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.kindle_vocab_anki.config import ConfigWidget

        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
