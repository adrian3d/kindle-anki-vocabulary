import hashlib
import sqlite3
from contextlib import closing


class TranslationCache:
    def __init__(self, path):
        self.path = str(path)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS translations (
                       provider TEXT NOT NULL,
                       source TEXT NOT NULL,
                       target TEXT NOT NULL,
                       stem TEXT NOT NULL,
                       context TEXT NOT NULL,
                       translation TEXT NOT NULL,
                       PRIMARY KEY (provider, source, target, stem, context)
                   )'''
            )

    def get(self, provider, source, target, stem, usage=''):
        with closing(self._connect()) as conn:
            row = conn.execute(
                '''SELECT translation FROM translations
                   WHERE provider = ? AND source = ? AND target = ? AND stem = ? AND context = ?''',
                (provider, source, target, stem, _digest(usage)),
            ).fetchone()
        return row[0] if row else None

    def load(self, provider, source, target):
        with closing(self._connect()) as conn:
            rows = conn.execute(
                'SELECT stem, context, translation FROM translations WHERE provider = ? AND source = ? AND target = ?',
                (provider, source, target),
            ).fetchall()
        return {(stem, context): translation for stem, context, translation in rows}

    @staticmethod
    def context_key(usage):
        return _digest(usage)

    def put(self, provider, source, target, stem, usage, translation):
        with closing(self._connect()) as conn, conn:
            conn.execute(
                'INSERT OR REPLACE INTO translations VALUES (?, ?, ?, ?, ?, ?)',
                (provider, source, target, stem, _digest(usage), translation),
            )

    def _connect(self):
        return sqlite3.connect(self.path)


def _digest(usage):
    return hashlib.sha1(usage.encode('utf-8')).hexdigest() if usage else ''
