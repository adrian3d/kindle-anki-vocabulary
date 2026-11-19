import sqlite3
from types import SimpleNamespace

import pytest

import phone
from phone import Phone, PhoneError

DIALOG = (
    '<hierarchy><node text="Importing" resource-id="com.ichi2.anki:id/alertTitle" class="android.widget.TextView" bounds="[160,972][426,1054]" />'
    '<node text="Add “kindle-vocab-anki.apkg” to collection?" resource-id="android:id/message" class="android.widget.TextView" bounds="[94,1098][986,1196]" />'
    '<node text="Cancel" resource-id="android:id/button2" class="android.widget.Button" bounds="[546,1269][722,1401]" />'
    '<node text="Add" resource-id="android:id/button1" class="android.widget.Button" bounds="[744,1269][920,1401]" /></hierarchy>'
)
OTHER_DIALOG = DIALOG.replace('kindle-vocab-anki.apkg', 'autre.apkg')
IMPORT_PAGE = (
    '<hierarchy><node text="" class="android.widget.ImageButton" bounds="[0,104][154,258]" />'
    '<node text="kindle-vocab-anki.apkg" class="android.widget.TextView" bounds="[13,288][382,365]" />'
    '<node text="Importer" class="android.widget.Button" bounds="[893,288][1072,365]" />'
    '<node text="" class="android.widget.Button" bounds="[937,269][998,269]" /></hierarchy>'
)
RESULT_PAGE = '<hierarchy><node text="Overview" class="android.widget.TextView" bounds="[60,300][400,360]" /></hierarchy>'


class FakeAdb:
    def __init__(self, screens=(), devices='List of devices attached\nSERIAL\tdevice\n', indexed=True, locked=False):
        self.screens, self.devices, self.indexed, self.locked = list(screens), devices, indexed, locked
        self.commands = []

    def __call__(self, command, **kwargs):
        text = ' '.join(command[1:])
        self.commands.append(text)
        return SimpleNamespace(returncode=0, stderr='', stdout=self.answer(text))

    def answer(self, text):
        if text.endswith('devices'):
            return self.devices
        if 'dumpsys window' in text:
            return f'isKeyguardShowing={"true" if self.locked else "false"}'
        if 'pm list packages' in text:
            return 'package:com.ichi2.anki\n'
        if 'content query' in text:
            other = 'Row: 0 _id=7, _display_name=Siege-and-Storm-vocabulaire.apkg\nRow: 1 _id=8, _display_name=old-kindle-vocab-anki.apkg\n'
            return other + ('Row: 2 _id=1000080582, _display_name=kindle-vocab-anki.apkg\n' if self.indexed else '')
        if 'uiautomator dump' in text:
            return self.screens.pop(0) if self.screens else RESULT_PAGE
        return ''

    def sent(self, fragment):
        return [command for command in self.commands if fragment in command]


def make_phone(adb):
    return Phone('adb', 'SERIAL', adb, lambda seconds: None)


def test_it_imports_confirms_both_screens_and_cleans_up():
    adb, steps = FakeAdb([DIALOG, IMPORT_PAGE, IMPORT_PAGE, RESULT_PAGE]), []

    outcome = make_phone(adb).send_package('/tmp/deck.apkg', steps.append)

    assert outcome == phone.IMPORTED
    assert adb.sent('push') == ['-s SERIAL push /tmp/deck.apkg /storage/emulated/0/Download/kindle-vocab-anki.apkg']
    assert 'content://media/external/downloads/1000080582' in adb.sent('am start -a android.intent.action.VIEW')[0]
    assert all("'" not in command and '--where' not in command for command in adb.sent('content query'))
    assert [command.split('input ')[1] for command in adb.sent('input ')] == ['tap 832 1335', 'tap 982 326', 'keyevent KEYCODE_BACK']
    assert adb.commands[-1].endswith('rm -f /storage/emulated/0/Download/kindle-vocab-anki.apkg')
    assert steps[0].startswith('Copie') and steps[-1] == 'Import en cours…'


def test_it_never_confirms_a_dialog_about_another_file():
    adb = FakeAdb([OTHER_DIALOG] * 10)

    outcome = make_phone(adb).send_package('/tmp/deck.apkg')

    assert outcome == phone.NEEDS_CONFIRMATION
    assert adb.sent('input ') == []
    assert adb.sent('rm -f')


def test_it_leaves_the_import_page_open_when_its_button_is_not_found():
    adb = FakeAdb([DIALOG] + [RESULT_PAGE] * 15)

    assert make_phone(adb).send_package('/tmp/deck.apkg') == phone.NEEDS_CONFIRMATION
    assert [command.split('input ')[1] for command in adb.sent('input ')] == ['tap 832 1335']


def test_it_refuses_a_locked_phone_or_an_unindexed_package():
    with pytest.raises(PhoneError, match='verrouillé'):
        make_phone(FakeAdb(locked=True)).send_package('/tmp/deck.apkg')

    adb = FakeAdb(indexed=False)
    with pytest.raises(PhoneError, match='indexé'):
        make_phone(adb).send_package('/tmp/deck.apkg')
    assert adb.sent('scan_file') and adb.sent('scan_volume') and adb.sent('rm -f')
    assert adb.sent('am start') == []


def test_connect_explains_missing_or_unauthorized_devices():
    assert phone.connect('adb', FakeAdb()).serial == 'SERIAL'
    with pytest.raises(PhoneError, match='autorisé'):
        phone.connect('adb', FakeAdb(devices='List of devices attached\nSERIAL\tunauthorized\n'))
    with pytest.raises(PhoneError, match='Aucun téléphone'):
        phone.connect('adb', FakeAdb(devices='List of devices attached\n\n'))


def test_it_reads_deck_names_from_both_collection_layouts(tmp_path):
    recent = sqlite3.connect(tmp_path / 'recent.anki2')
    recent.create_collation('unicase', lambda a, b: (a > b) - (a < b))
    recent.execute('CREATE TABLE decks (id integer primary key, name text not null collate unicase)')
    recent.executemany('INSERT INTO decks (name) VALUES (?)', [('Langues\x1fAnglais',), ('Default',), ('english vocabulary',)])
    recent.commit()
    legacy = sqlite3.connect(tmp_path / 'legacy.anki2')
    legacy.execute('CREATE TABLE col (decks text)')
    legacy.execute('INSERT INTO col VALUES (?)', ('{"1": {"name": "Default"}, "2": {"name": "Langues::Anglais"}}',))
    legacy.commit()

    assert phone.read_deck_names(tmp_path / 'recent.anki2') == ['Default', 'english vocabulary', 'Langues::Anglais']
    assert phone.read_deck_names(tmp_path / 'legacy.anki2') == ['Default', 'Langues::Anglais']
