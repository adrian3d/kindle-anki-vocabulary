import json
import sqlite3

import pytest

import translators
from cache import TranslationCache
from translators import (
    ClaudeTranslator,
    DeepLTranslator,
    Item,
    OllamaTranslator,
    TranslationError,
    WiktionaryTranslator,
    translate_all,
)

ITEMS = [
    Item('en:stench', 'stench', 'stench', 'free of that rotting stench'),
    Item('en:billowing', 'billowing', 'billow', 'his black kefta billowing around him'),
]

LLM_ANSWER = json.dumps({'translations': [{'id': 0, 'translation': 'puanteur'}, {'id': 1, 'translation': 'onduler, flotter'}]})


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(translators.time, 'sleep', lambda seconds: None)


def test_claude_sends_a_structured_request_and_maps_ids_back(fake_server):
    fake_server.queue(200, {'stop_reason': 'end_turn', 'content': [{'type': 'thinking', 'thinking': ''}, {'type': 'text', 'text': LLM_ANSWER}]})

    result = ClaudeTranslator('sk-test', base_url=fake_server.url).translate(ITEMS, 'en', 'fr')

    request = fake_server.requests[0]
    assert result == {'en:stench': 'puanteur', 'en:billowing': 'onduler, flotter'}
    assert request['path'] == '/v1/messages'
    assert request['headers']['x-api-key'] == 'sk-test'
    assert request['headers']['anthropic-version'] == '2026-10-21'
    assert request['headers']['anthropic-beta'] == 'server-side-fallback-2026-07-01'
    assert request['body']['model'] == 'claude-opus-5-5'
    assert request['body']['fallbacks'] == 'default'
    assert request['body']['output_config']['format']['type'] == 'json_schema'
    assert 'thinking' not in request['body'] and 'temperature' not in request['body']
    assert 'French' in request['body']['system']
    assert json.loads(request['body']['messages'][0]['content'])[1] == {
        'id': 1, 'word': 'billowing', 'lemma': 'billow', 'sentence': 'his black kefta billowing around him',
    }


def test_claude_omits_fallbacks_for_models_without_them(fake_server):
    fake_server.queue(200, {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': LLM_ANSWER}]})

    ClaudeTranslator('sk-test', 'claude-haiku-5-5', fake_server.url).translate(ITEMS, 'en', 'fr')

    assert 'fallbacks' not in fake_server.requests[0]['body']
    assert 'anthropic-beta' not in fake_server.requests[0]['headers']


def test_claude_reports_refusals_and_api_errors(fake_server):
    translator = ClaudeTranslator('sk-test', base_url=fake_server.url)

    fake_server.queue(200, {'stop_reason': 'refusal', 'content': []})
    with pytest.raises(TranslationError, match='refusée'):
        translator.translate(ITEMS, 'en', 'fr')

    fake_server.queue(401, {'type': 'error', 'error': {'type': 'authentication_error', 'message': 'invalid x-api-key'}})
    with pytest.raises(TranslationError, match='HTTP 401 — invalid x-api-key'):
        translator.translate(ITEMS, 'en', 'fr')

    with pytest.raises(TranslationError, match='clé'):
        ClaudeTranslator('').translate(ITEMS, 'en', 'fr')


def test_it_retries_overloaded_responses(fake_server):
    fake_server.queue(529, {'error': {'message': 'overloaded'}})
    fake_server.queue(200, {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': LLM_ANSWER}]})

    result = ClaudeTranslator('sk-test', base_url=fake_server.url).translate(ITEMS, 'en', 'fr')

    assert len(fake_server.requests) == 2
    assert result['en:stench'] == 'puanteur'


def test_ollama_asks_for_schema_constrained_json(fake_server):
    fake_server.queue(200, {'message': {'role': 'assistant', 'content': LLM_ANSWER}})

    result = OllamaTranslator('mistral', fake_server.url).translate(ITEMS, 'en', 'fr')

    body = fake_server.requests[0]['body']
    assert result == {'en:stench': 'puanteur', 'en:billowing': 'onduler, flotter'}
    assert fake_server.requests[0]['path'] == '/api/chat'
    assert (body['model'], body['stream']) == ('mistral', False)
    assert body['format']['required'] == ['translations']
    assert [message['role'] for message in body['messages']] == ['system', 'user']


def test_ollama_retries_missing_words_one_by_one_and_stops_batching(fake_server):
    one = lambda index, text: {'message': {'content': json.dumps({'translations': [{'id': index, 'translation': text}]})}}
    fake_server.queue(200, one(0, 'puanteur'))
    fake_server.queue(200, one(0, 'onduler'))
    fake_server.queue(200, one(0, 'vertige'))
    translator = OllamaTranslator('small', fake_server.url)
    items = ITEMS + [Item('en:dizziness', 'dizziness', 'dizziness', 'I willed the dizziness away')]

    result = translator.translate(items, 'en', 'fr')

    assert result == {'en:stench': 'puanteur', 'en:billowing': 'onduler', 'en:dizziness': 'vertige'}
    assert [len(json.loads(request['body']['messages'][1]['content'])) for request in fake_server.requests] == [3, 1, 1]
    assert translator.batch_size == 1


def test_ollama_lists_models_and_reports_unreachable_server(fake_server):
    fake_server.queue(200, {'models': [{'name': 'mistral:latest'}, {'name': 'gemma3:4b'}]})

    assert translators.list_ollama_models(fake_server.url) == ['gemma3:4b', 'mistral:latest']
    with pytest.raises(TranslationError, match='connexion impossible'):
        OllamaTranslator('mistral', 'http://127.0.0.1:9').translate(ITEMS, 'en', 'fr')
    with pytest.raises(TranslationError, match='modèle'):
        OllamaTranslator('').translate(ITEMS, 'en', 'fr')


def test_ollama_ignores_malformed_entries(fake_server):
    answer = json.dumps({'translations': [{'id': 7, 'translation': 'x'}, {'id': 1, 'translation': ' flotter '}, {'id': 0, 'translation': ''}]})
    fake_server.queue(200, {'message': {'content': answer}})
    fake_server.queue(200, {'message': {'content': 'pas du JSON'}})

    translator = OllamaTranslator('mistral', fake_server.url)
    with pytest.raises(TranslationError, match='JSON inattendue'):
        translator.translate(ITEMS, 'en', 'fr')
    assert translator.batch_size == 10


def test_deepl_translates_each_lemma_with_its_sentence(fake_server):
    fake_server.queue(200, {'translations': [{'detected_source_language': 'EN', 'text': 'puanteur'}]})
    fake_server.queue(200, {'translations': [{'detected_source_language': 'EN', 'text': 'onduler'}]})

    result = DeepLTranslator('key:fx', fake_server.url).translate(ITEMS, 'fr', 'en')

    assert result == {'en:stench': 'puanteur', 'en:billowing': 'onduler'}
    assert fake_server.requests[0]['path'] == '/v2/translate'
    assert fake_server.requests[0]['headers']['authorization'] == 'DeepL-Auth-Key key:fx'
    assert fake_server.requests[1]['body'] == {
        'text': ['billow'], 'source_lang': 'FR', 'target_lang': 'EN-GB', 'context': 'his black kefta billowing around him',
    }


def test_deepl_picks_the_endpoint_from_the_key():
    assert DeepLTranslator('abc:fx').base_url == 'https://api-free.deepl.com'
    assert DeepLTranslator('abc').base_url == 'https://api.deepl.com'


def make_dictionary(path):
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE simple_translation (written_rep TEXT, trans_list, max_score, rel_importance)')
    conn.executemany('INSERT INTO simple_translation VALUES (?, ?, 100, ?)', [
        ('stench', 'puanteur', 0.9),
        ('billow', 'ondoyer | flot | a | b | c | d', 0.5),
    ])
    conn.commit()
    conn.close()


def test_wiktionary_looks_up_the_lemma_offline(tmp_path):
    make_dictionary(tmp_path / 'en-fr.sqlite3')
    items = ITEMS + [Item('en:zzz', 'zzz', 'zzz', '')]

    result = WiktionaryTranslator(tmp_path).translate(items, 'en', 'fr')

    assert result == {'en:stench': 'puanteur', 'en:billowing': 'ondoyer, flot, a, b, c'}


def test_wiktionary_downloads_a_missing_dictionary(tmp_path, fake_server):
    make_dictionary(tmp_path / 'source.sqlite3')
    fake_server.queue(200, (tmp_path / 'source.sqlite3').read_bytes())
    translator = WiktionaryTranslator(tmp_path / 'dictionaries', fake_server.url)

    result = translator.translate(ITEMS[:1], 'en', 'fr')

    assert result == {'en:stench': 'puanteur'}
    assert fake_server.requests[0]['path'] == '/en-fr.sqlite3'
    assert (tmp_path / 'dictionaries' / 'en-fr.sqlite3').exists()


def test_wiktionary_reports_an_unavailable_language_pair(tmp_path, fake_server):
    fake_server.queue(404, b'not found')

    with pytest.raises(TranslationError, match='pas de dictionnaire English → Japanese'):
        WiktionaryTranslator(tmp_path, fake_server.url).translate(ITEMS, 'en', 'ja')
    assert list(tmp_path.iterdir()) == []


class CountingTranslator:
    cache_id = 'fake'
    contextual = True
    batch_size = 1

    def __init__(self):
        self.calls = []

    def translate(self, items, source, target):
        self.calls.append([item.key for item in items])
        return {item.key: item.stem.upper() for item in items if item.stem != 'billow'}


def test_translate_all_batches_reports_progress_and_caches(tmp_path):
    cache = TranslationCache(tmp_path / 'cache.sqlite3')
    translator, progress = CountingTranslator(), []

    first = translate_all(translator, ITEMS, 'en', 'fr', cache, lambda done, total: progress.append((done, total)))
    second = translate_all(translator, ITEMS, 'en', 'fr', cache)

    assert first == second == {'en:stench': 'STENCH'}
    assert progress == [(0, 2), (1, 2), (2, 2)]
    assert translator.calls == [['en:stench'], ['en:billowing'], ['en:billowing']]


def test_translate_all_keeps_one_translation_per_sentence_and_stops_on_cancel(tmp_path):
    cache = TranslationCache(tmp_path / 'cache.sqlite3')
    cache.put('fake', 'en', 'fr', 'stench', 'another sentence', 'ailleurs')
    translator = CountingTranslator()

    result = translate_all(translator, ITEMS, 'en', 'fr', cache, should_cancel=lambda: bool(translator.calls))

    assert result == {'en:stench': 'STENCH'}
    assert translator.calls == [['en:stench']]
