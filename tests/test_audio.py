import urllib.parse

import audio
from cache import TranslationCache


def api_answer(server, *names):
    pages = [{'title': f'File:{name}', 'imageinfo': [{'url': f'{server.url}/files/{urllib.parse.quote(name.replace(" ", "_"))}', 'size': size}]}
             for name, size in names]
    return {'query': {'pages': [{'title': 'File:Example.jpg', 'imageinfo': [{'url': 'x.jpg', 'size': 1}]}, *pages]}}


def make(server, tmp_path, contact=''):
    return audio.Pronunciations(tmp_path / 'audio', TranslationCache(tmp_path / 'cache.sqlite3'), f'{server.url}/w/api.php',
                                workers=1, pause=0, contact=contact)


def test_it_prefers_an_american_recording_of_the_word_and_keeps_it(fake_server, tmp_path):
    fake_server.queue(200, api_answer(fake_server, ('Fr-chat.ogg', 900), ('LL-Q1860 (eng)-Speaker-chat.wav', 800),
                                      ('En-uk-chat.ogg', 700), ('En-us-chat.ogg', 1000), ('En-us-chatty.ogg', 10)))
    fake_server.queue(200, b'OggS-us')
    pronunciations = make(fake_server, tmp_path, contact='lecteur@example.org')

    filename = pronunciations.fetch('chat', 'en')

    assert filename.startswith('kindle-en-') and filename.endswith('.ogg')
    assert (tmp_path / 'audio' / filename).read_bytes() == b'OggS-us'
    assert fake_server.requests[1]['path'] == '/files/En-us-chat.ogg'
    assert 'titles=chat' in fake_server.requests[0]['path']
    assert fake_server.requests[1]['headers']['user-agent'] == 'KindleVocabAnki/1.0 (lecteur@example.org)'
    assert pronunciations.fetch('chat', 'en') == filename
    assert len(fake_server.requests) == 2


def test_it_falls_back_on_lingua_libre_and_on_the_lowercase_title(fake_server, tmp_path):
    fake_server.queue(200, {'query': {}})
    fake_server.queue(200, api_answer(fake_server, ('Fr-pleat.ogg', 10), ('LL-Q1860 (eng)-Speaker-pleat.wav', 800)))
    fake_server.queue(200, b'RIFF')

    filename = make(fake_server, tmp_path).fetch('Pleat', 'en')

    assert filename.endswith('.wav')
    assert 'titles=pleat' in fake_server.requests[1]['path']


def test_it_remembers_words_without_recording_but_retries_after_a_network_error(fake_server, tmp_path):
    fake_server.queue(200, api_answer(fake_server, ('Fr-kefta.ogg', 10)))
    fake_server.queue(500, {'error': 'down'})
    pronunciations = make(fake_server, tmp_path)

    assert pronunciations.fetch('kefta', 'en') == ''
    assert pronunciations.fetch('kefta', 'en') == ''
    assert pronunciations.fetch('stench', 'en') == ''
    fake_server.queue(200, api_answer(fake_server, ('En-us-stench.ogg', 10)))
    fake_server.queue(200, b'OggS')

    assert pronunciations.fetch('stench', 'en').endswith('.ogg')
    assert len(fake_server.requests) == 4


def test_it_waits_and_retries_when_wikimedia_limits_the_rate(fake_server, tmp_path):
    fake_server.queue(429, {'error': 'too many requests'})
    fake_server.queue(200, api_answer(fake_server, ('En-us-stench.ogg', 10)))
    fake_server.queue(503, {'error': 'busy'})
    fake_server.queue(200, b'OggS')

    assert make(fake_server, tmp_path).fetch('stench', 'en').endswith('.ogg')
    assert len(fake_server.requests) == 4


def test_it_only_looks_up_plain_words_and_reports_progress(fake_server, tmp_path):
    fake_server.queue(200, api_answer(fake_server, ('En-us-give up.ogg', 10)))
    fake_server.queue(200, b'OggS')
    progress = []

    result = make(fake_server, tmp_path).fetch_all(
        [('give up', 'en'), ('give up', 'en'), ('so much as ...', 'en'), ('take somebody in', 'en'), ('stench', '')],
        lambda done, total: progress.append((done, total)),
    )

    assert list(result) == [('give up', 'en')]
    assert progress == [(1, 1)]
    assert len(fake_server.requests) == 2
