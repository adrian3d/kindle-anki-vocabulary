import getpass
import glob
import os

from calibre.gui2.actions import InterfaceAction
from qt.core import QIcon

from calibre_plugins.kindle_vocab_anki.config import prefs
from calibre_plugins.kindle_vocab_anki.dialog import MainDialog
from calibre_plugins.kindle_vocab_anki.i18n import _

VOCAB_DB = os.path.join('system', 'vocabulary', 'vocab.db')
CLIPPINGS = os.path.join('documents', 'My Clippings.txt')


class KindleVocabAction(InterfaceAction):
    name = 'Kindle Vocab to Anki'
    action_spec = (_('Vocabulaire Kindle'), None, _('Vocabulaire et surlignages de la Kindle vers Anki et Markdown'), None)

    def genesis(self):
        self.qaction.setIcon(QIcon.ic('dictionary.png'))
        self.qaction.triggered.connect(self.show_dialog)

    def show_dialog(self):
        vocab_db = self._find(VOCAB_DB) or prefs['vocab_db']
        clippings = self._find(CLIPPINGS) or prefs['clippings']
        MainDialog(self.gui, vocab_db, clippings, self.interface_action_base_plugin).exec()

    def _find(self, relative_path):
        device = self.gui.device_manager.connected_device
        user = getpass.getuser()
        roots = [getattr(device, '_main_prefix', None)]
        roots += glob.glob(f'/run/media/{user}/*') + glob.glob(f'/media/{user}/*') + glob.glob('/Volumes/*')
        for root in filter(None, roots):
            path = os.path.join(root, relative_path)
            if os.path.isfile(path):
                return path
        return ''
