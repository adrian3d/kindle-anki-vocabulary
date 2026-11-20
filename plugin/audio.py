import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API_URL = 'https://en.wiktionary.org/w/api.php'
USER_AGENT = 'KindleVocabAnki/1.0'
CACHE_PROVIDER = 'audio:wiktionary'
EXTENSIONS = ('.ogg', '.oga', '.opus', '.mp3', '.wav', '.flac')
MAX_BYTES = 2_000_000
RETRIES = 3
# Lingua Libre nomme ses fichiers « LL-Q1860 (eng)-locuteur-mot.wav », avec le code ISO 639-3 de la langue.
ISO_639_3 = {
    'en': 'eng', 'fr': 'fra', 'de': 'deu', 'es': 'spa', 'it': 'ita', 'pt': 'por', 'nl': 'nld', 'sv': 'swe',
    'da': 'dan', 'nb': 'nob', 'pl': 'pol', 'cs': 'ces', 'ru': 'rus', 'uk': 'ukr', 'ja': 'jpn', 'zh': 'cmn',
    'ko': 'kor', 'tr': 'tur', 'el': 'ell', 'fi': 'fin', 'hu': 'hun', 'ro': 'ron', 'ca': 'cat',
}
ACCENTS = {'en': ('en-us', 'en-gb', 'en-uk'), 'pt': ('pt-br', 'pt-pt'), 'es': ('es-es', 'es-mx')}


def is_lookup_candidate(word):
    return bool(word) and '...' not in word and '…' not in word and 'somebody' not in word and 'something' not in word


class Pronunciations:
    def __init__(self, directory, cache, api_url=API_URL, workers=2, pause=1.0, contact=''):
        self.directory, self.cache, self.api_url, self.workers, self.pause = str(directory), cache, api_url, workers, pause
        # @see https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
        self.user_agent = f'{USER_AGENT} ({contact})' if contact else USER_AGENT

    def path(self, filename):
        return os.path.join(self.directory, filename)

    def fetch_all(self, items, on_progress=None):
        items = sorted({(word, lang) for word, lang in items if lang and is_lookup_candidate(word)})
        result, done = {}, 0
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            for item, filename in zip(items, executor.map(lambda entry: self.fetch(*entry), items)):
                done += 1
                if filename:
                    result[item] = filename
                if on_progress:
                    on_progress(done, len(items))
        return result

    def fetch(self, word, lang):
        cached = self.cache.get(CACHE_PROVIDER, lang, '', word)
        if cached is not None and (not cached or os.path.isfile(self.path(cached))):
            return cached
        try:
            filename = self._download(word, lang)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError, KeyError):
            # Une panne réseau ne doit pas marquer le mot comme dépourvu de prononciation.
            return ''
        self.cache.put(CACHE_PROVIDER, lang, '', word, '', filename)
        return filename

    def _download(self, word, lang):
        files = self._audio_files(word) or (self._audio_files(word.lower()) if word != word.lower() else [])
        best = _choose(files, word, lang)
        if best is None:
            return ''
        extension = os.path.splitext(urllib.parse.urlparse(best['url']).path)[1].lower()
        filename = f'kindle-{lang}-{hashlib.sha1(best["url"].encode("utf-8")).hexdigest()[:16]}{extension}'
        os.makedirs(self.directory, exist_ok=True)
        data = self._get(best['url'])
        partial = self.path(filename) + '.part'
        with open(partial, 'wb') as output:
            output.write(data)
        os.replace(partial, self.path(filename))
        return filename

    def _audio_files(self, title):
        params = {
            'action': 'query', 'format': 'json', 'formatversion': '2', 'titles': title, 'redirects': '1',
            'generator': 'images', 'gimlimit': '50', 'prop': 'imageinfo', 'iiprop': 'url|size',
        }
        response = json.loads(self._get(f'{self.api_url}?{urllib.parse.urlencode(params)}'))
        files = []
        for page in response.get('query', {}).get('pages', []):
            info = (page.get('imageinfo') or [{}])[0]
            name = page.get('title', '').split(':', 1)[-1]
            if info.get('url') and name.lower().endswith(EXTENSIONS) and 0 < info.get('size', 0) <= MAX_BYTES:
                files.append({'name': name, 'url': info['url'], 'size': info['size']})
        return files

    def _get(self, url):
        request = urllib.request.Request(url, headers={'User-Agent': self.user_agent})
        for attempt in range(RETRIES + 1):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return response.read(MAX_BYTES + 1)
            except urllib.error.HTTPError as error:
                # Wikimedia limite le débit des clients : on attend le délai demandé avant de réessayer.
                if error.code not in (429, 503) or attempt == RETRIES:
                    raise
                delay = error.headers.get('Retry-After', '')
                time.sleep(min(float(delay), 10) if delay.isdigit() else self.pause * 2 ** attempt)


def _choose(files, word, lang):
    wanted = re.compile(r'(?<![^\W\d_])' + re.escape(_simplify(word)) + r'(?![^\W\d_])')
    accents = ACCENTS.get(lang, ())
    lingua_libre = f'({ISO_639_3[lang]})' if lang in ISO_639_3 else None
    ranked = []
    for file in files:
        name = file['name'].lower()
        if not wanted.search(_simplify(os.path.splitext(name)[0])):
            continue
        if name.startswith(f'{lang}-') or name.startswith(f'{lang} '):
            accent = next((index for index, prefix in enumerate(accents) if name.startswith(prefix)), len(accents))
            ranked.append(((0, accent, file['size']), file))
        elif lingua_libre and name.startswith('ll-') and lingua_libre in name:
            ranked.append(((1, 0, file['size']), file))
    return min(ranked, key=lambda entry: entry[0])[1] if ranked else None


def _simplify(text):
    return ' '.join(text.lower().replace('_', ' ').split())
