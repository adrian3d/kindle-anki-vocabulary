import json
from dataclasses import dataclass

import flashcards
from cache import TranslationCache
from translators import ClaudeTranslator, OllamaTranslator


@dataclass
class Passage:
    text: str | None
    book: str = 'Siege and Storm'


PASSAGES = [
    Passage('If you so much as raise your hands, Ivan will end the tracker.'),
    Passage(None),
    Passage('I willed the dizziness away, shook her off, then stumbled.'),
    Passage('La banquise craquait.', 'Vers le Pôle'),
]


class FakeLlm:
    cache_id = 'fake'
    extraction_batch_size = 2

    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def complete_json(self, system, user, schema, effort=None):
        self.calls.append({'system': system, 'user': json.loads(user), 'schema': schema, 'effort': effort})
        return self.answers.pop(0)


def card(passage_id, kind, front, back, note='', excerpt=None, language='en'):
    return {'passage_id': passage_id, 'language': language, 'kind': kind, 'excerpt': front if excerpt is None else excerpt,
            'front': front, 'back': back, 'note': note}


def test_it_extracts_cards_per_passage_and_keeps_their_sentence(tmp_path):
    llm = FakeLlm([
        {'cards': [
            card(0, 'expression', 'so much as', 'ne serait-ce que', 'Renforce une condition.'),
            card(1, 'vocabulary', 'dizziness', 'vertige', language='EN-gb'),
            card(1, 'vocabulary', 'to stumble', 'trébucher', excerpt='stumbled'),
        ]},
        {'cards': []},
    ])
    progress = []

    cards = flashcards.extract_flashcards(
        llm, PASSAGES, 'fr', 'French', TranslationCache(tmp_path / 'cache.sqlite3'), lambda done, total: progress.append((done, total)),
    )

    assert [(c.kind, c.front, c.back, c.note) for c in cards] == [
        ('expression', 'so much as', 'ne serait-ce que', 'Renforce une condition.'),
        ('vocabulary', 'dizziness', 'vertige', ''),
        ('vocabulary', 'to stumble', 'trébucher', ''),
    ]
    assert cards[1].sentence == 'I willed the dizziness away, shook her off, then stumbled.'
    assert cards[2].excerpt == 'stumbled'
    assert [c.language for c in cards] == ['en', 'en', 'en']
    assert cards[0].book == 'Siege and Storm'
    assert progress == [(0, 3), (2, 3), (3, 3)]
    assert [entry['id'] for entry in llm.calls[0]['user']] == [0, 1]
    assert llm.calls[1]['user'] == [{'id': 2, 'passage': 'La banquise craquait.'}]
    assert llm.calls[0]['effort'] == 'medium'
    assert 'native French speaker' in llm.calls[0]['system']


def test_it_drops_invalid_duplicate_and_excess_cards(tmp_path):
    llm = FakeLlm([{'cards': [
        card(0, 'vocabulary', 'Stench', 'puanteur'),
        card(0, 'vocabulary', 'stench', 'odeur'),
        card(0, 'grammar', 'x', 'y'),
        card(0, 'vocabulary', '', 'vide'),
        card(9, 'vocabulary', 'ghost', 'fantôme'),
        *[card(0, 'vocabulary', f'word{n}', 'mot', excerpt='rotting') for n in range(9)],
    ]}])

    cards = flashcards.extract_flashcards(llm, [Passage('free of that rotting stench')], 'fr', 'French', TranslationCache(tmp_path / 'c.sqlite3'))

    assert [c.front for c in cards] == ['Stench', 'word0', 'word1', 'word2']


def test_it_drops_cards_whose_excerpt_is_not_in_the_passage(tmp_path):
    llm = FakeLlm([{'cards': [
        card(0, 'vocabulary', 'tirer péniblement', 'inspirer profondément', excerpt='tirer péniblement'),
        card(0, 'expression', 'draw in a sharp breath', 'inspirer brusquement', excerpt='DREW IN  a sharp breath'),
        card(0, 'expression', "can't help ...", 'ne pas pouvoir s’empêcher de', excerpt="couldn't help"),
    ]}])

    cards = flashcards.extract_flashcards(
        llm, [Passage('I drew in a sharp breath and couldn’t help but laugh.')], 'fr', 'French', TranslationCache(tmp_path / 'c.sqlite3'),
    )

    assert [c.front for c in cards] == ['draw in a sharp breath', "can't help ..."]


def test_it_asks_again_on_refresh_and_keeps_the_new_cards(tmp_path):
    cache = TranslationCache(tmp_path / 'cache.sqlite3')
    flashcards.extract_flashcards(FakeLlm([{'cards': [card(0, 'expression', 'so much as', 'ne serait-ce que')]}]),
                                  PASSAGES[:1], 'fr', 'French', cache)

    refreshed = FakeLlm([{'cards': [card(0, 'vocabulary', 'tracker', 'pisteur')]}])
    first = flashcards.extract_flashcards(refreshed, PASSAGES[:1], 'fr', 'French', cache, refresh=True)
    second = flashcards.extract_flashcards(FakeLlm([]), PASSAGES[:1], 'fr', 'French', cache)

    assert len(refreshed.calls) == 1
    assert [c.front for c in first] == [c.front for c in second] == ['tracker']


def test_it_asks_again_when_the_prompt_changes(tmp_path, monkeypatch):
    cache = TranslationCache(tmp_path / 'cache.sqlite3')
    answer = {'cards': [card(0, 'expression', 'so much as', 'ne serait-ce que')]}
    flashcards.extract_flashcards(FakeLlm([answer]), PASSAGES[:1], 'fr', 'French', cache)
    monkeypatch.setattr(flashcards, 'instructions', lambda language: f'New prompt for {language}')

    again = FakeLlm([answer])
    flashcards.extract_flashcards(again, PASSAGES[:1], 'fr', 'French', cache)

    assert len(again.calls) == 1


def test_it_never_asks_twice_for_the_same_passage_and_stops_on_cancel(tmp_path):
    cache = TranslationCache(tmp_path / 'cache.sqlite3')
    answer = {'cards': [card(0, 'expression', 'so much as', 'ne serait-ce que')]}
    first = FakeLlm([answer])
    flashcards.extract_flashcards(first, PASSAGES[:1], 'fr', 'French', cache)

    second = FakeLlm([{'cards': []}])
    cards = flashcards.extract_flashcards(second, PASSAGES, 'fr', 'French', cache, should_cancel=lambda: bool(second.calls))

    assert [c.front for c in cards] == ['so much as']
    assert [[entry['id'] for entry in call['user']] for call in second.calls] == [[1, 2]]


def test_claude_and_ollama_serve_the_extraction_schema(fake_server, tmp_path):
    answer = json.dumps({'cards': [card(0, 'vocabulary', 'stench', 'puanteur')]})
    fake_server.queue(200, {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': answer}]})
    fake_server.queue(200, {'message': {'content': answer}})
    passages = [Passage('free of that rotting stench')]

    claude = flashcards.extract_flashcards(ClaudeTranslator('sk', base_url=fake_server.url), passages, 'fr', 'French', TranslationCache(tmp_path / 'a.sqlite3'))
    ollama = flashcards.extract_flashcards(OllamaTranslator('gemma', fake_server.url), passages, 'fr', 'French', TranslationCache(tmp_path / 'b.sqlite3'))

    assert claude == ollama
    assert claude[0].front == 'stench'
    assert fake_server.requests[0]['body']['output_config'] == {'effort': 'medium', 'format': {'type': 'json_schema', 'schema': flashcards.SCHEMA}}
    assert fake_server.requests[1]['body']['format'] == flashcards.SCHEMA
