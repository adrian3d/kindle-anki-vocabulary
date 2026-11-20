import hashlib
import json
from dataclasses import asdict, dataclass

KINDS = ('vocabulary', 'expression')
MAX_CARDS_PER_PASSAGE = 5

SCHEMA = {
    'type': 'object',
    'properties': {
        'cards': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'passage_id': {'type': 'integer'},
                    'language': {'type': 'string'},
                    'kind': {'type': 'string', 'enum': list(KINDS)},
                    'excerpt': {'type': 'string'},
                    'front': {'type': 'string'},
                    'back': {'type': 'string'},
                    'note': {'type': 'string'},
                },
                'required': ['passage_id', 'language', 'kind', 'excerpt', 'front', 'back', 'note'],
                'additionalProperties': False,
            },
        }
    },
    'required': ['cards'],
    'additionalProperties': False,
}


@dataclass(frozen=True)
class Flashcard:
    kind: str
    excerpt: str
    front: str
    back: str
    note: str
    sentence: str
    book: str
    language: str = ''


def instructions(language):
    return (
        f'You help a native {language} speaker learn foreign languages from passages they highlighted while reading '
        'novels and essays. For each passage, pick what is most worth a flashcard for an upper-intermediate learner.\n'
        'Two kinds of cards:\n'
        '- "vocabulary": uncommon, literary or precise words, and phrasal verbs.\n'
        '- "expression": idioms, collocations and reusable turns of phrase or sentence patterns '
        '(for example "so much as", "it took everything in me not to ...", "all he did was ...").\n'
        f'Skip basic words, proper nouns and invented words. Return at most {MAX_CARDS_PER_PASSAGE} cards per passage, '
        'and none when nothing is worth learning.\n'
        'For each card:\n'
        '- "language": the ISO 639-1 code of the language of the passage, for example "en".\n'
        '- "excerpt": the words of the passage the card is about, copied exactly as they appear in the passage.\n'
        '- "front": the same words, still in the language of the passage: never translate them. In lowercase, except '
        'for proper nouns. The dictionary form for a word (infinitive, singular); for an expression, a short reusable '
        'form with "..." or "somebody/something" in place of the variable parts.\n'
        f'- "back": the {language} translation of "front", in the sense used in the passage. '
        'One to three short equivalents.\n'
        f'- "note": one short sentence in {language} about the nuance, register or construction; '
        'an empty string when there is nothing useful to add.\n'
        'Only "back" and "note" are in '
        f'{language}. For example, from "I drew in a sharp breath and lay back.", a good card has the excerpt '
        '"drew in a sharp breath" and the front "draw in a sharp breath"; "lay back" is too basic for a card.\n'
        f'Ignore passages that are already written in {language}. Keep the passage ids.'
    )


def extract_flashcards(llm, passages, target, language, cache, on_progress=None, should_cancel=None, refresh=False):
    provider = f'extract:{llm.cache_id}:{_digest(instructions(language))[:12]}'
    passages = [passage for passage in passages if passage.text]
    cards_by_passage, missing = {}, []
    for index, passage in enumerate(passages):
        cached = None if refresh else cache.get(provider, '', target, _digest(passage.text))
        if cached is None:
            missing.append(index)
        else:
            cards_by_passage[index] = [Flashcard(**card) for card in json.loads(cached)]

    done = len(passages) - len(missing)
    _notify(on_progress, done, len(passages))

    for start in range(0, len(missing), llm.extraction_batch_size):
        if should_cancel and should_cancel():
            break
        batch = missing[start:start + llm.extraction_batch_size]
        user = json.dumps([{'id': index, 'passage': passages[index].text} for index in batch], ensure_ascii=False)
        response = llm.complete_json(instructions(language), user, SCHEMA, effort='medium')

        extracted = {index: [] for index in batch}
        for entry in response.get('cards') or []:
            index = entry.get('passage_id')
            card = _make_card(entry, passages[index]) if index in extracted else None
            if card and len(extracted[index]) < MAX_CARDS_PER_PASSAGE:
                extracted[index].append(card)
        for index, cards in extracted.items():
            cache.put(provider, '', target, _digest(passages[index].text), '', json.dumps([asdict(card) for card in cards]))
        cards_by_passage.update(extracted)
        done += len(batch)
        _notify(on_progress, done, len(passages))

    unique = {}
    for index in sorted(cards_by_passage):
        for card in cards_by_passage[index]:
            unique.setdefault(card.front.lower(), card)
    return list(unique.values())


def _make_card(entry, passage):
    excerpt, front, back = ((entry.get(key) or '').strip() for key in ('excerpt', 'front', 'back'))
    if not excerpt or not front or not back or entry.get('kind') not in KINDS:
        return None
    # Un modèle de traduction traduit aussi le recto : un extrait absent du passage trahit une carte inventée.
    if _normalize(excerpt) not in _normalize(passage.text):
        return None
    language = (entry.get('language') or '').strip().lower()[:2]
    return Flashcard(entry['kind'], excerpt, front, back, (entry.get('note') or '').strip(), passage.text, passage.book,
                     language if language.isalpha() else '')


def _normalize(text):
    return ' '.join(text.replace('’', "'").replace('‘', "'").split()).casefold()


def _digest(text):
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


def _notify(on_progress, done, total):
    if on_progress:
        on_progress(done, total)
