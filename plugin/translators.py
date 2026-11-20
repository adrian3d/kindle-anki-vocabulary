import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from contextlib import closing
from dataclasses import dataclass

try:
    from calibre_plugins.kindle_vocab_anki.i18n import N_, _
except ImportError:
    # Hors de calibre, dans les tests, les modules du plugin s'importent sans le préfixe calibre_plugins.
    from i18n import N_, _

LANGUAGES = {
    'fr': 'French', 'en': 'English', 'es': 'Spanish', 'de': 'German', 'it': 'Italian',
    'pt': 'Portuguese', 'nl': 'Dutch', 'sv': 'Swedish', 'no': 'Norwegian', 'da': 'Danish',
    'fi': 'Finnish', 'pl': 'Polish', 'ru': 'Russian', 'el': 'Greek', 'tr': 'Turkish',
    'ja': 'Japanese', 'zh': 'Chinese', 'ca': 'Catalan', 'la': 'Latin',
}

ANTHROPIC_URL = 'https://api.anthropic.com'
ANTHROPIC_VERSION = '2026-10-21'
ANTHROPIC_FALLBACK_BETA = 'server-side-fallback-2026-07-01'
MODELS_WITH_SERVER_FALLBACK = {'claude-opus-5-5', 'claude-sonnet-5-5', 'claude-fable-5-2', 'claude-fable-5-1'}
DEFAULT_CLAUDE_MODEL = 'claude-opus-5-5'

DEEPL_FREE_URL = 'https://api-free.deepl.com'
DEEPL_PRO_URL = 'https://api.deepl.com'
DEEPL_TARGET_VARIANTS = {'en': 'EN-GB', 'pt': 'PT-PT'}

OLLAMA_URL = 'http://localhost:11434'
WIKDICT_URL = 'https://download.wikdict.com/dictionaries/sqlite/2'
WIKTIONARY_MAX_SENSES = 5

RETRYABLE_STATUSES = {429, 500, 502, 503, 504, 529}
MAX_ATTEMPTS = 3

TRANSLATIONS_SCHEMA = {
    'type': 'object',
    'properties': {
        'translations': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {'id': {'type': 'integer'}, 'translation': {'type': 'string'}},
                'required': ['id', 'translation'],
                'additionalProperties': False,
            },
        }
    },
    'required': ['translations'],
    'additionalProperties': False,
}


class TranslationError(Exception):
    pass


@dataclass(frozen=True)
class Item:
    key: str
    word: str
    stem: str
    usage: str


def language_name(code):
    return LANGUAGES.get(code, code)


def request_json(url, payload=None, headers=None, timeout=120, label='Service'):
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', **(headers or {})})

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as error:
            body = error.read().decode('utf-8', 'replace')
            if error.code in RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS:
                time.sleep(float(error.headers.get('retry-after') or 2 ** attempt))
                continue
            raise TranslationError(_('{service} : HTTP {code} — {message}').format(
                service=_(label), code=error.code, message=_error_message(body))) from error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise TranslationError(_('{service} : connexion impossible à {url} ({error})').format(
                service=_(label), url=url, error=getattr(error, 'reason', error))) from error
        except json.JSONDecodeError as error:
            raise TranslationError(_('{service} : réponse illisible').format(service=_(label))) from error


def _error_message(body):
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body[:300]
    error = parsed.get('error', parsed.get('message', body))
    if isinstance(error, dict):
        error = error.get('message', error)
    return str(error)[:300]


def _llm_instructions(source, target):
    return (
        f'You are a bilingual lexicographer writing flashcards for a {language_name(target)} speaker '
        f'who is learning {language_name(source)} by reading books.\n'
        f'Each item has a word as it appears in a sentence, its dictionary form (lemma) and that sentence. '
        f'Give the {language_name(target)} translation of the lemma in the sense it has in that sentence.\n'
        'Write one to three short equivalents separated by commas, most fitting first. '
        'Translate the lemma, not the inflected form: infinitive for verbs, singular for nouns. '
        'No explanations, no quotes, no trailing period. '
        'Return one translation per item, keeping the item ids.'
    )


def _llm_items(items):
    return json.dumps(
        [{'id': index, 'word': item.word, 'lemma': item.stem, 'sentence': item.usage} for index, item in enumerate(items)],
        ensure_ascii=False,
    )


def _parse_llm_json(raw_json, label):
    try:
        parsed = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as error:
        raise TranslationError(_('{service} : réponse JSON inattendue').format(service=_(label))) from error
    if not isinstance(parsed, dict):
        raise TranslationError(_('{service} : réponse JSON inattendue').format(service=_(label)))
    return parsed


def _map_llm_translations(items, response):
    result = {}
    for entry in response.get('translations') or []:
        index, translation = entry.get('id'), (entry.get('translation') or '').strip()
        if isinstance(index, int) and 0 <= index < len(items) and translation:
            result[items[index].key] = translation
    return result


class ClaudeTranslator:
    label = 'Claude'
    contextual = True
    batch_size = 40
    extraction_batch_size = 10

    def __init__(self, api_key, model=DEFAULT_CLAUDE_MODEL, base_url=ANTHROPIC_URL):
        self.api_key = api_key
        self.model = model or DEFAULT_CLAUDE_MODEL
        self.base_url = base_url.rstrip('/')
        self.cache_id = f'claude:{self.model}'

    def translate(self, items, source, target):
        response = self.complete_json(_llm_instructions(source, target), _llm_items(items), TRANSLATIONS_SCHEMA)
        return _map_llm_translations(items, response)

    def complete_json(self, system, user, schema, effort='low'):
        if not self.api_key:
            raise TranslationError(_('Claude : clé d\'API manquante (Préférences du plugin)'))

        headers = {'x-api-key': self.api_key, 'anthropic-version': ANTHROPIC_VERSION}
        payload = {
            'model': self.model,
            'max_tokens': 16000,
            'system': system,
            'output_config': {'effort': effort, 'format': {'type': 'json_schema', 'schema': schema}},
            'messages': [{'role': 'user', 'content': user}],
        }
        if self.model in MODELS_WITH_SERVER_FALLBACK:
            headers['anthropic-beta'] = ANTHROPIC_FALLBACK_BETA
            payload['fallbacks'] = 'default'

        response = request_json(f'{self.base_url}/v1/messages', payload, headers, timeout=300, label=self.label)

        stop_reason = response.get('stop_reason')
        if stop_reason == 'refusal':
            raise TranslationError(_('Claude : requête refusée par le modèle'))
        if stop_reason == 'max_tokens':
            raise TranslationError(_('Claude : réponse tronquée, réduisez la sélection'))

        text = next((block['text'] for block in response.get('content', []) if block.get('type') == 'text'), '')
        return _parse_llm_json(text, self.label)


class OllamaTranslator:
    label = 'Ollama'
    contextual = True
    batch_size = 10
    extraction_batch_size = 2

    def __init__(self, model, base_url=OLLAMA_URL):
        self.model = model
        self.base_url = (base_url or OLLAMA_URL).rstrip('/')
        self.cache_id = f'ollama:{model}'

    def translate(self, items, source, target):
        result = self._translate_batch(items, source, target)
        missing = [item for item in items if item.key not in result]
        if len(items) > 1:
            # Les petits modèles locaux ne rendent souvent qu'une partie d'un lot.
            if len(missing) > len(items) / 2:
                self.batch_size = 1
            for item in missing:
                result.update(self._translate_batch([item], source, target))
        return result

    def _translate_batch(self, items, source, target):
        response = self.complete_json(_llm_instructions(source, target), _llm_items(items), TRANSLATIONS_SCHEMA)
        return _map_llm_translations(items, response)

    def complete_json(self, system, user, schema, effort=None):
        if not self.model:
            raise TranslationError(_('Ollama : aucun modèle choisi (Préférences du plugin)'))

        response = request_json(
            f'{self.base_url}/api/chat',
            {
                'model': self.model,
                'stream': False,
                'format': schema,
                'options': {'temperature': 0},
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
            },
            timeout=600,
            label=self.label,
        )
        return _parse_llm_json(response.get('message', {}).get('content', ''), self.label)


def list_ollama_models(base_url=OLLAMA_URL):
    response = request_json(f'{(base_url or OLLAMA_URL).rstrip("/")}/api/tags', timeout=5, label='Ollama')
    return sorted(model['name'] for model in response.get('models', []))


class DeepLTranslator:
    label = 'DeepL'
    contextual = True
    # Le paramètre « context » vaut pour toute la requête : un mot par appel pour garder sa phrase.
    batch_size = 1
    cache_id = 'deepl'

    def __init__(self, api_key, base_url=None):
        self.api_key = api_key
        self.base_url = (base_url or (DEEPL_FREE_URL if api_key.endswith(':fx') else DEEPL_PRO_URL)).rstrip('/')

    def translate(self, items, source, target):
        if not self.api_key:
            raise TranslationError(_('DeepL : clé d\'API manquante (Préférences du plugin)'))

        result = {}
        for item in items:
            payload = {
                'text': [item.stem],
                'source_lang': source.upper(),
                'target_lang': DEEPL_TARGET_VARIANTS.get(target, target.upper()),
            }
            if item.usage:
                payload['context'] = item.usage
            response = request_json(
                f'{self.base_url}/v2/translate',
                payload,
                {'Authorization': f'DeepL-Auth-Key {self.api_key}'},
                label=self.label,
            )
            translation = (response.get('translations') or [{}])[0].get('text', '').strip()
            if translation:
                result[item.key] = translation
        return result


class WiktionaryTranslator:
    label = N_('Wiktionnaire')
    contextual = False
    batch_size = 200
    cache_id = 'wiktionary'

    def __init__(self, dictionaries_dir, base_url=WIKDICT_URL):
        self.dictionaries_dir = str(dictionaries_dir)
        self.base_url = base_url.rstrip('/')

    def dictionary_path(self, source, target):
        return os.path.join(self.dictionaries_dir, f'{source}-{target}.sqlite3')

    def translate(self, items, source, target):
        path = self.dictionary_path(source, target)
        if not os.path.exists(path):
            self.download(source, target)

        result = {}
        with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as conn:
            for item in items:
                translation = self._lookup(conn, item)
                if translation:
                    result[item.key] = translation
        return result

    def download(self, source, target):
        path = self.dictionary_path(source, target)
        url = f'{self.base_url}/{source}-{target}.sqlite3'
        os.makedirs(self.dictionaries_dir, exist_ok=True)
        partial_path = path + '.part'
        try:
            with urllib.request.urlopen(url, timeout=120) as response, open(partial_path, 'wb') as output:
                while chunk := response.read(1 << 16):
                    output.write(chunk)
        except urllib.error.HTTPError as error:
            _remove(partial_path)
            if error.code == 404:
                raise TranslationError(_('Wiktionnaire : pas de dictionnaire {source} → {target}').format(
                    source=language_name(source), target=language_name(target))) from error
            raise TranslationError(_('Wiktionnaire : téléchargement impossible (HTTP {code})').format(code=error.code)) from error
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            _remove(partial_path)
            raise TranslationError(_('Wiktionnaire : téléchargement impossible ({error})').format(error=error)) from error
        os.replace(partial_path, path)

    @staticmethod
    def _lookup(conn, item):
        candidates = dict.fromkeys([item.stem, item.stem.lower(), item.word, item.word.lower()])
        for candidate in candidates:
            row = conn.execute(
                'SELECT trans_list FROM simple_translation WHERE written_rep = ? ORDER BY rel_importance DESC',
                (candidate,),
            ).fetchone()
            if row and row[0]:
                return ', '.join(row[0].split(' | ')[:WIKTIONARY_MAX_SENSES])
        return None


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def translate_all(translator, items, source, target, cache, on_progress=None, should_cancel=None):
    result, missing = {}, []
    for item in items:
        cached = cache.get(translator.cache_id, source, target, item.stem, _cache_context(translator, item))
        if cached:
            result[item.key] = cached
        else:
            missing.append(item)

    done = len(result)
    _notify(on_progress, done, len(items))

    while missing:
        if should_cancel and should_cancel():
            break
        batch, missing = missing[:translator.batch_size], missing[translator.batch_size:]
        translated = translator.translate(batch, source, target)
        for item in batch:
            if item.key in translated:
                cache.put(translator.cache_id, source, target, item.stem, _cache_context(translator, item), translated[item.key])
        result.update(translated)
        done += len(batch)
        _notify(on_progress, done, len(items))

    return result


def _cache_context(translator, item):
    return item.usage if translator.contextual else ''


def _notify(on_progress, done, total):
    if on_progress:
        on_progress(done, total)
