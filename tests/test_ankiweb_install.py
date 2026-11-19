import hashlib
import io
import zipfile

import pytest

import ankiweb
from ankiweb import AnkiWeb, AnkiWebError


def make_wheel(module):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as wheel:
        wheel.writestr(f'{module}/__init__.py', f'NAME = "{module}"\n')
    return buffer.getvalue()


@pytest.fixture
def pypi(fake_server):
    wheels = {}
    packages = (ankiweb.ANKI, *ankiweb.PURE_PACKAGES)
    for name, version in packages:
        suffix = f'{ankiweb.platform_tag()}.whl' if (name, version) == ankiweb.ANKI else 'none-any.whl'
        filename = f'{name}-{version}-{suffix}'
        wheels[filename] = make_wheel(name)
        fake_server.queue(200, {'urls': [
            {'filename': f'{name}-{version}.tar.gz', 'url': f'{fake_server.url}/files/source'},
            {'filename': filename, 'url': f'{fake_server.url}/files/{filename}'},
        ]})
        fake_server.queue(200, wheels[filename])
    fake_server.digests = {filename: hashlib.sha256(data).hexdigest() for filename, data in wheels.items()}
    return fake_server


def test_it_downloads_verifies_and_unpacks_every_library(tmp_path, pypi):
    client = AnkiWeb(str(tmp_path), '', ['python'], pypi.url, pypi.digests)
    steps = []

    assert not client.is_installed()
    client.install(steps.append)

    assert client.is_installed()
    assert (tmp_path / 'ankiweb' / 'libs' / 'anki' / '__init__.py').read_text() == 'NAME = "anki"\n'
    assert (tmp_path / 'ankiweb' / 'libs' / 'certifi' / '__init__.py').exists()
    assert pypi.requests[0]['path'] == '/anki/26.09.4/json'
    assert steps[0] == 'Téléchargement des bibliothèques Anki (1/8)…' and len(steps) == 8
    assert not (tmp_path / 'ankiweb' / 'libs.partial').exists()


def test_it_refuses_a_library_whose_fingerprint_changed(tmp_path, pypi):
    tampered = {**pypi.digests, next(iter(pypi.digests)): '0' * 64}
    client = AnkiWeb(str(tmp_path), '', ['python'], pypi.url, tampered)

    with pytest.raises(AnkiWebError, match='empreinte attendue'):
        client.install()

    assert not client.is_installed()
    assert not (tmp_path / 'ankiweb' / 'libs').exists() and not (tmp_path / 'ankiweb' / 'libs.partial').exists()


def test_it_explains_an_unreachable_package_index(tmp_path):
    client = AnkiWeb(str(tmp_path), '', ['python'], 'http://127.0.0.1:9')

    with pytest.raises(AnkiWebError, match='Téléchargement de « anki » impossible'):
        client.install()
