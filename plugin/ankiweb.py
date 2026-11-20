import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

PYPI_URL = 'https://pypi.org/pypi'
ANKI = ('anki', '26.09.4')
PURE_PACKAGES = (
    ('protobuf', '7.36.2'), ('decorator', '5.3.1'), ('markdown', '3.11.3'), ('requests', '2.34.2'),
    ('urllib3', '2.8.0'), ('idna', '3.20'), ('certifi', '2026.10.23'),
)
# Empreintes épinglées : un fichier modifié sur le dépôt de paquets est refusé plutôt qu'exécuté.
SHA256 = {
    'anki-26.9.4-cp310-abi3-macosx_12_0_arm64.whl': '4e9dd1e37471b35dff96e44837ea3ef26832d64d2e6079414a28f9f29adff4c8',
    'anki-26.9.4-cp310-abi3-macosx_12_0_x86_64.whl': '37a2150d3bcd11622fef279d680d97363f69ec3a7e8b64d0bdd52076d1f57ba3',
    'anki-26.9.4-cp310-abi3-manylinux_2_35_aarch64.whl': '52d319123a06d831fbc47cccfba087d75e00dc2e7eb4176c19a2901c525aad9e',
    'anki-26.9.4-cp310-abi3-manylinux_2_35_x86_64.whl': '67950105a13fe9894fe424eb799afe01b2a1762f402bf877aaa5b3cb879ec8cc',
    'anki-26.9.4-cp310-abi3-win_amd64.whl': '01adec8b3a0faa29e7258f829ae4b1b2f7f3bcc580866797fa3294cce6171390',
    'anki-26.9.4-cp310-abi3-win_arm64.whl': '3bee099cb00308abb31b6045b12a16427d0df23a96883fae4600b30ddbc3ebd2',
    'protobuf-7.36.2-py3-none-any.whl': 'bdb3a345d48db958e6ce1f18e508beb0cc981d64f24088427549c866cd039f1e',
    'decorator-5.3.1-py3-none-any.whl': 'f47fe6fdbd2edd623ecfe36875d37aba411624e2670dd395dddae1358689bb3c',
    'markdown-3.11.3-py3-none-any.whl': 'e1a31a112232504d753e5c01bb8c2de90d3f0ba986b063e10770cf7695b09e73',
    'requests-2.34.2-py3-none-any.whl': '2a0d60c172f83ac6ab31e4554906c0f3b3588d37b5cb939b1c061f4907e278e0',
    'urllib3-2.8.0-py3-none-any.whl': '0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3',
    'idna-3.20-py3-none-any.whl': 'ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c',
    'certifi-2026.10.23-py3-none-any.whl': 'e9b54de76e530bb6cf0ccd036787103acb58fd42ba930ea8bf948ddbaa2f61d1',
}
RELEASE = hashlib.sha256(json.dumps(SHA256, sort_keys=True).encode()).hexdigest()[:16]


class AnkiWebError(Exception):
    pass


def platform_tag():
    arm = platform.machine().lower() in ('arm64', 'aarch64')
    if sys.platform == 'win32':
        return 'win_arm64' if arm else 'win_amd64'
    if sys.platform == 'darwin':
        return 'macosx_12_0_arm64' if arm else 'macosx_12_0_x86_64'
    return 'manylinux_2_35_aarch64' if arm else 'manylinux_2_35_x86_64'


class AnkiWeb:
    def __init__(self, data_dir, helper_source, interpreter, pypi_url=PYPI_URL, sha256=None):
        self.directory = os.path.join(data_dir, 'ankiweb')
        self.libraries = os.path.join(self.directory, 'libs')
        self.helper_source, self.interpreter = helper_source, list(interpreter)
        self.pypi_url, self.sha256 = pypi_url.rstrip('/'), SHA256 if sha256 is None else sha256

    @property
    def collection(self):
        return os.path.join(self.directory, 'mirror', 'collection.anki2')

    @property
    def marker(self):
        return os.path.join(self.libraries, '.release')

    def is_installed(self):
        try:
            with open(self.marker, encoding='utf-8') as file:
                return file.read() == RELEASE
        except OSError:
            return False

    def install(self, on_step=lambda message: None):
        partial = self.libraries + '.partial'
        shutil.rmtree(partial, ignore_errors=True)
        os.makedirs(partial)
        try:
            packages = (ANKI, *PURE_PACKAGES)
            for index, (name, version) in enumerate(packages, start=1):
                on_step(f'Téléchargement des bibliothèques Anki ({index}/{len(packages)})…')
                suffix = f'{platform_tag()}.whl' if (name, version) == ANKI else 'none-any.whl'
                zipfile.ZipFile(io.BytesIO(self._download(name, version, suffix))).extractall(partial)
            with open(os.path.join(partial, '.release'), 'w', encoding='utf-8') as file:
                file.write(RELEASE)
            shutil.rmtree(self.libraries, ignore_errors=True)
            os.replace(partial, self.libraries)
        except (OSError, zipfile.BadZipFile) as error:
            raise AnkiWebError(f'Installation des bibliothèques Anki impossible : {error}') from error
        finally:
            shutil.rmtree(partial, ignore_errors=True)

    def _download(self, name, version, suffix):
        try:
            with urllib.request.urlopen(f'{self.pypi_url}/{name}/{version}/json', timeout=60) as response:
                files = json.loads(response.read())['urls']
            wheel = next((file for file in files if file['filename'].endswith(suffix)), None)
            if wheel is None:
                raise AnkiWebError(f'Aucune version de « {name} » pour ce système ({suffix}).')
            with urllib.request.urlopen(wheel['url'], timeout=300) as response:
                data = response.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, KeyError) as error:
            raise AnkiWebError(f'Téléchargement de « {name} » impossible : {error}') from error
        if hashlib.sha256(data).hexdigest() != self.sha256.get(wheel['filename']):
            raise AnkiWebError(f'Le fichier « {wheel["filename"]} » ne correspond pas à l\'empreinte attendue : installation annulée.')
        return data

    def login(self, username, password, endpoint=''):
        return self._call({'action': 'login', 'username': username, 'password': password, 'endpoint': endpoint})

    def list_decks(self, account, on_step=lambda message: None):
        return self._call({'action': 'decks', **account}, on_step)

    def export(self, account, package, on_step=lambda message: None, media=False):
        return self._call({'action': 'export', 'package': package, 'media': media, **account}, on_step)

    def forget(self):
        shutil.rmtree(os.path.join(self.directory, 'mirror'), ignore_errors=True)

    def _call(self, request, on_step=lambda message: None):
        if not self.is_installed():
            raise AnkiWebError('Les bibliothèques Anki ne sont pas installées.')
        helper = os.path.join(self.directory, 'helper.py')
        with open(helper, 'w', encoding='utf-8') as file:
            file.write(self.helper_source)

        try:
            process = subprocess.Popen(
                [*self.interpreter, helper], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace',
            )
        except OSError as error:
            raise AnkiWebError(f'Lancement de la synchronisation impossible : {error}') from error

        process.stdin.write(json.dumps({'collection': self.collection, 'libraries': self.libraries, **request}))
        process.stdin.close()
        result = None
        for line in process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            if 'step' in message:
                on_step(message['step'])
            elif 'ok' in message:
                result = message
        errors = process.stderr.read()
        process.wait()

        if result is None:
            raise AnkiWebError(f'La synchronisation s\'est arrêtée sans réponse : {errors.strip()[-300:]}')
        if not result['ok']:
            raise AnkiWebError(result['error'])
        return result
