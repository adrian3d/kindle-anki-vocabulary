import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip('anki')

import ankiweb
import apkg
from ankiweb import AnkiWeb, AnkiWebError

HELPER = (Path(__file__).resolve().parent.parent / 'plugin' / 'ankiweb_helper.py').read_text(encoding='utf-8')


@pytest.fixture
def server(tmp_path):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    environment = {**os.environ, 'SYNC_USER1': 'reader:secret', 'SYNC_BASE': str(tmp_path / 'server'),
                   'SYNC_HOST': '127.0.0.1', 'SYNC_PORT': str(port)}
    process = subprocess.Popen([sys.executable, '-m', 'anki.syncserver'], env=environment,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _attempt in range(100):
        try:
            socket.create_connection(('127.0.0.1', port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield f'http://127.0.0.1:{port}/'
    process.terminate()
    process.wait()


def make_package(tmp_path, name, deck, *words):
    path = tmp_path / name
    apkg.write_apkg(path, deck, [apkg.Note(f'en:{word}', word, f'traduction de {word}') for word in words])
    return str(path)


def make_client(directory):
    client = AnkiWeb(str(directory), HELPER, [sys.executable, '-I'])
    os.makedirs(client.libraries)
    Path(client.marker).write_text(ankiweb.RELEASE, encoding='utf-8')
    return client


def connect(tmp_path, name, endpoint):
    client = make_client(tmp_path / name)
    login = client.login('reader', 'secret', endpoint)
    return client, {'hkey': login['hkey'], 'endpoint': login['endpoint']}


def test_it_exports_to_an_empty_account_then_merges_with_other_devices(tmp_path, server):
    computer, account = connect(tmp_path, 'computer', server)
    steps = []

    first = computer.export(account, make_package(tmp_path, 'a.apkg', 'English vocabulary', 'stench', 'billow'), steps.append)

    assert first['added'] == 2
    assert 'English vocabulary' in first['decks']
    assert steps == ['Récupération de la collection AnkiWeb…', 'Ajout des cartes…', 'Envoi vers AnkiWeb…']

    phone, phone_account = connect(tmp_path, 'phone', server)
    assert 'English vocabulary' in phone.list_decks(phone_account)['decks']
    from_phone = phone.export(phone_account, make_package(tmp_path, 'b.apkg', 'Anglais::Dune', 'spice'))
    assert from_phone['added'] == 1

    again = computer.export(account, make_package(tmp_path, 'c.apkg', 'English vocabulary', 'stench', 'woozy'))
    assert again['added'] == 1
    assert {'English vocabulary', 'Anglais::Dune'} <= set(computer.list_decks(account)['decks'])
    assert {'English vocabulary', 'Anglais::Dune'} <= set(phone.list_decks(phone_account)['decks'])


def test_it_reports_refused_credentials_and_a_missing_runtime(tmp_path, server):
    client = make_client(tmp_path / 'computer')

    with pytest.raises(AnkiWebError, match='identifiants'):
        client.login('reader', 'wrong', server)
    with pytest.raises(AnkiWebError, match='identifiants'):
        client.list_decks({'hkey': 'invalide', 'endpoint': server})
    with pytest.raises(AnkiWebError, match='pas installées'):
        AnkiWeb(str(tmp_path / 'nowhere'), HELPER, [sys.executable]).list_decks({'hkey': 'x', 'endpoint': server})


def test_it_adds_cards_to_a_populated_account_without_forcing_a_full_sync(tmp_path, server):
    from anki.collection import Collection
    from anki.sync_pb2 import SyncCollectionResponse

    device = Collection(str(tmp_path / 'device.anki2'))
    auth = device.sync_login('reader', 'secret', server)
    note = device.new_note(device.models.by_name('Basic'))
    note['Front'], note['Back'] = 'déjà là', 'already there'
    device.add_note(note, device.decks.id('English vocabulary'))
    assert device.sync_collection(auth, False).required == SyncCollectionResponse.FULL_UPLOAD
    device.close_for_full_sync()
    device.full_upload_or_download(auth=auth, server_usn=None, upload=True)
    device.reopen(after_full_sync=True)

    computer, account = connect(tmp_path, 'computer', server)
    result = computer.export(account, make_package(tmp_path, 'a.apkg', 'English vocabulary', 'stench', 'billow'))

    assert result['added'] == 2
    assert device.sync_collection(auth, False).required == SyncCollectionResponse.NO_CHANGES
    assert device.note_count() == 3
    assert len(device.find_cards('deck:"English vocabulary"')) == 5
    device.close()


def test_it_uploads_the_pronunciations_with_the_cards(tmp_path, server):
    from anki.collection import Collection

    media_dir = tmp_path / 'audio'
    media_dir.mkdir()
    (media_dir / 'kindle-en-stench.ogg').write_bytes(b'OggS-stench')
    package = tmp_path / 'audio.apkg'
    apkg.write_apkg(package, 'English vocabulary', [
        apkg.Note('en:stench', 'stench', 'puanteur', lang='en', audio='kindle-en-stench.ogg'),
        apkg.Note('en:billow', 'billow', 'onduler', lang='en'),
    ], media_dir=media_dir)
    computer, account = connect(tmp_path, 'computer', server)
    steps = []

    computer.export(account, str(package), steps.append, media=True)

    assert steps[-1].startswith('Envoi des prononciations vers AnkiWeb')
    device = Collection(str(tmp_path / 'device.anki2'))
    auth = device.sync_login('reader', 'secret', server)
    device.sync_collection(auth, False)
    device.close_for_full_sync()
    device.full_upload_or_download(auth=auth, server_usn=None, upload=False)
    device.reopen(after_full_sync=True)
    device.sync_media(auth)
    while device.media_sync_status().active:
        time.sleep(0.1)
    assert (Path(device.media.dir()) / 'kindle-en-stench.ogg').read_bytes() == b'OggS-stench'
    card = device.get_card(device.find_cards('Word:billow card:1')[0])
    assert [tag.lang for tag in card.question_av_tags()] == ['en_US']
    device.close()


def test_it_reports_cards_of_an_older_note_type_and_replaces_them_on_request(tmp_path, server, monkeypatch):
    from anki.collection import Collection

    computer, account = connect(tmp_path, 'computer', server)
    with monkeypatch.context() as patch:
        patch.setattr(apkg, 'MODEL_ID', 1763596800002)
        patch.setattr(apkg, 'MODEL_NAME', 'Kindle vocabulary')
        computer.export(account, make_package(tmp_path, 'old.apkg', 'English vocabulary', 'give in', 'grin'))

    skipped = computer.export(account, make_package(tmp_path, 'new.apkg', 'Test prononciation', 'give in', 'wart'))

    assert (skipped['added'], skipped['conflicting'], skipped['conflicting_decks'], skipped['replaced']) == (
        1, 1, ['English vocabulary'], 0)

    replaced = computer.export(account, make_package(tmp_path, 'again.apkg', 'Test prononciation', 'give in', 'wart'),
                               replace_older=True)

    assert (replaced['added'], replaced['replaced'], replaced['existing'], replaced['conflicting']) == (1, 1, 1, 0)
    device = Collection(str(tmp_path / 'device.anki2'))
    auth = device.sync_login('reader', 'secret', server)
    device.sync_collection(auth, False)
    device.close_for_full_sync()
    device.full_upload_or_download(auth=auth, server_usn=None, upload=False)
    device.reopen(after_full_sync=True)
    words = lambda search: sorted(device.get_note(nid)['Word'] for nid in device.find_notes(search))
    assert words('deck:"Test prononciation"') == ['give in', 'wart']
    assert words('deck:"English vocabulary"') == ['grin']
    device.close()
