import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing

try:
    from calibre_plugins.kindle_vocab_anki.i18n import _
except ImportError:
    # Hors de calibre, dans les tests, les modules du plugin s'importent sans le préfixe calibre_plugins.
    from i18n import _

ANKIDROID = 'com.ichi2.anki'
INTENT_HANDLER = f'{ANKIDROID}/.IntentHandler'
REMOTE_NAME = 'kindle-vocab-anki.apkg'
REMOTE_PATH = f'/storage/emulated/0/Download/{REMOTE_NAME}'
DOWNLOADS_URI = 'content://media/external/downloads'
COLLECTION_DIRS = (f'/sdcard/Android/data/{ANKIDROID}/files/AnkiDroid', '/sdcard/AnkiDroid')
SUBDECK_SEPARATOR = '\x1f'
POSITIVE_BUTTON = 'android:id/button1'
DIALOG_MESSAGE = 'android:id/message'

IMPORTED = 'imported'
NEEDS_CONFIRMATION = 'needs_confirmation'

NODE = re.compile(r'<node\b[^>]*>')
ATTRIBUTE = re.compile(r'([\w:-]+)="([^"]*)"')
BOUNDS = re.compile(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]')


class PhoneError(Exception):
    pass


def connect(adb=None, run=subprocess.run, sleep=time.sleep):
    adb = adb or shutil.which('adb')
    if not adb:
        raise PhoneError(_('La commande « adb » est introuvable : installez les outils Android (paquet android-tools-adb).'))

    phone = Phone(adb, None, run, sleep)
    devices = [line.split() for line in phone.adb('devices').splitlines()[1:] if line.strip()]
    ready = [serial for serial, state, *_rest in devices if state == 'device']
    if not ready:
        if any(state == 'unauthorized' for _serial, state, *_rest in devices):
            raise PhoneError(_('Le téléphone est branché mais n\'a pas autorisé le débogage USB : acceptez la demande à l\'écran.'))
        raise PhoneError(_('Aucun téléphone détecté : branchez-le en USB et activez le débogage USB.'))
    phone.serial = ready[0]
    return phone


class Phone:
    def __init__(self, adb, serial, run=subprocess.run, sleep=time.sleep):
        self.adb_path, self.serial, self.run, self.sleep = adb, serial, run, sleep

    def adb(self, *args, check=True, timeout=120):
        command = [self.adb_path, *(['-s', self.serial] if self.serial else []), *args]
        try:
            result = self.run(command, capture_output=True, text=True, timeout=timeout, errors='replace')
        except (OSError, subprocess.TimeoutExpired) as error:
            raise PhoneError(_('adb {command} a échoué : {error}').format(command=args[0], error=error)) from error
        if check and result.returncode != 0:
            raise PhoneError(_('adb {command} a échoué : {error}').format(
                command=' '.join(args[:3]), error=(result.stderr or result.stdout).strip()[:300]))
        return result.stdout

    def shell(self, command, check=True, timeout=120):
        return self.adb('shell', command, check=check, timeout=timeout)

    def list_decks(self):
        directory = tempfile.mkdtemp(prefix='kindle-vocab-anki-')
        try:
            local = os.path.join(directory, 'collection.anki2')
            for remote_dir in COLLECTION_DIRS:
                self.adb('pull', f'{remote_dir}/collection.anki2', local, check=False)
                if os.path.exists(local):
                    self.adb('pull', f'{remote_dir}/collection.anki2-wal', local + '-wal', check=False)
                    return read_deck_names(local)
            raise PhoneError(_('Collection AnkiDroid introuvable sur le téléphone.'))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def send_package(self, local_path, on_step=lambda message: None):
        if 'isKeyguardShowing=true' in self.shell('dumpsys window', check=False):
            raise PhoneError(_('Le téléphone est verrouillé : déverrouillez-le puis relancez l\'envoi.'))
        if ANKIDROID not in self.shell(f'pm list packages {ANKIDROID}'):
            raise PhoneError(_('AnkiDroid n\'est pas installé sur le téléphone.'))

        on_step(_('Copie du paquet sur le téléphone…'))
        self.adb('push', local_path, REMOTE_PATH)
        try:
            on_step(_('Ouverture de l\'import dans AnkiDroid…'))
            self.shell(f'am start -a android.intent.action.VIEW -d {self._content_uri()} -t application/apkg '
                       f'--grant-read-uri-permission -n {INTENT_HANDLER}')
            if not self._confirm_import(on_step):
                return NEEDS_CONFIRMATION
        finally:
            self.shell(f'rm -f {REMOTE_PATH}', check=False)
        return IMPORTED

    def _content_uri(self):
        # AnkiDroid refuse les chemins de fichiers : il lui faut l'adresse attribuée par l'index des médias.
        for scan in (f'--method scan_file --arg {REMOTE_PATH}', '--method scan_volume --arg external_primary'):
            self.shell(f'content call --uri content://media {scan}', check=False)
            # Filtrage côté Python : une clause --where demanderait des apostrophes que le shell du téléphone altère.
            rows = self.shell(f'content query --uri {DOWNLOADS_URI} --projection _id:_display_name', check=False)
            identifiers = re.findall(rf'_id=(\d+), _display_name={re.escape(REMOTE_NAME)}\s*$', rows, re.MULTILINE)
            if identifiers:
                return f'{DOWNLOADS_URI}/{identifiers[-1]}'
        raise PhoneError(_('Android n\'a pas indexé le paquet copié : import impossible.'))

    def _confirm_import(self, on_step):
        dialog_button = self._wait_for(_find_dialog_button, attempts=10)
        if dialog_button is None:
            return False
        self._tap(dialog_button)

        on_step(_('Validation de l\'import…'))
        import_button = self._wait_for(_find_import_button, attempts=15)
        if import_button is None:
            return False
        self._tap(import_button)

        on_step(_('Import en cours…'))
        self._wait_for(lambda nodes: None if _find_import_button(nodes) else True, attempts=60)
        self.shell('input keyevent KEYCODE_BACK', check=False)
        return True

    def _wait_for(self, find, attempts):
        for _attempt in range(attempts):
            found = find(parse_nodes(self.adb('exec-out', 'uiautomator', 'dump', '/dev/tty', check=False)))
            if found is not None:
                return found
            self.sleep(1)
        return None

    def _tap(self, node):
        left, top, right, bottom = map(int, BOUNDS.search(node['bounds']).groups())
        self.shell(f'input tap {(left + right) // 2} {(top + bottom) // 2}')


def parse_nodes(dump):
    return [dict(ATTRIBUTE.findall(node)) for node in NODE.findall(dump)]


def read_deck_names(collection_path):
    with closing(sqlite3.connect(collection_path)) as conn:
        conn.create_collation('unicase', lambda a, b: (a.lower() > b.lower()) - (a.lower() < b.lower()))
        try:
            names = [name for (name,) in conn.execute('SELECT name FROM decks')]
        except sqlite3.OperationalError:
            names = [deck['name'] for deck in json.loads(conn.execute('SELECT decks FROM col').fetchone()[0]).values()]
    return sorted((name.replace(SUBDECK_SEPARATOR, '::') for name in names), key=str.lower)


def _find_dialog_button(nodes):
    # Le nom du fichier doit figurer dans le message : on ne valide jamais une autre boîte de dialogue.
    if not any(node.get('resource-id') == DIALOG_MESSAGE and REMOTE_NAME in node.get('text', '') for node in nodes):
        return None
    return next((node for node in nodes if node.get('resource-id') == POSITIVE_BUTTON and _has_area(node)), None)


def _find_import_button(nodes):
    for index, node in enumerate(nodes):
        if node.get('text') == REMOTE_NAME:
            return next((n for n in nodes[index + 1:] if n.get('class', '').endswith('Button') and _has_area(n)), None)
    return None


def _has_area(node):
    match = BOUNDS.search(node.get('bounds', ''))
    return bool(match) and int(match.group(3)) > int(match.group(1)) and int(match.group(4)) > int(match.group(2))
