import json
import sqlite3
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'plugin'))


def millis(year, month, day, hour=12):
    return int(datetime(year, month, day, hour).timestamp() * 1000)


@pytest.fixture
def vocab_db(tmp_path):
    path = tmp_path / 'vocab.db'
    conn = sqlite3.connect(path)
    conn.executescript(
        '''CREATE TABLE WORDS (id TEXT PRIMARY KEY, word TEXT, stem TEXT, lang TEXT, category INTEGER, timestamp INTEGER, profileid TEXT);
           CREATE TABLE LOOKUPS (id TEXT PRIMARY KEY, word_key TEXT, book_key TEXT, dict_key TEXT, pos TEXT, usage TEXT, timestamp INTEGER);
           CREATE TABLE BOOK_INFO (id TEXT PRIMARY KEY, asin TEXT, guid TEXT, lang TEXT, title TEXT, authors TEXT);'''
    )
    conn.executemany('INSERT INTO BOOK_INFO VALUES (?, ?, ?, ?, ?, ?)', [
        ('dune', 'A1', 'g1', 'en', 'Dune', 'Frank Herbert'),
        ('siege', 'A2', 'g2', 'en', 'Siege and Storm', 'Leigh Bardugo'),
        ('nansen', 'A3', 'g3', 'fr', 'Vers le Pôle', 'Fridtjof Nansen'),
    ])
    conn.executemany('INSERT INTO WORDS VALUES (?, ?, ?, ?, 0, ?, \'\')', [
        ('en:billowing', 'billowing', 'billow', 'en', millis(2026, 11, 18)),
        ('en:stench', 'stench', 'stench', 'en', millis(2025, 12, 31)),
        ('fr:banquise', 'banquise', 'banquise', 'fr', millis(2026, 6, 25)),
    ])
    conn.executemany('INSERT INTO LOOKUPS VALUES (?, ?, ?, \'\', \'\', ?, ?)', [
        ('l1', 'en:stench', 'dune', 'A stench rose from the cave. ', millis(2025, 12, 31)),
        ('l2', 'en:stench', 'siege', 'free of that rotting stench', millis(2026, 11, 18, 9)),
        ('l3', 'en:billowing', 'siege', 'his black kefta billowing around him', millis(2026, 11, 18, 10)),
        ('l4', 'fr:banquise', 'nansen', 'La banquise craquait.', millis(2026, 6, 25)),
    ])
    conn.commit()
    conn.close()
    return path


class FakeServer:
    def __init__(self):
        self.requests = []
        self.responses = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self._reply(None)

            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                self._reply(json.loads(self.rfile.read(length) or b'null'))

            def _reply(self, body):
                server.requests.append({'path': self.path, 'headers': {name.lower(): value for name, value in self.headers.items()}, 'body': body})
                status, payload = server.responses.pop(0) if server.responses else (404, {'error': 'no response queued'})
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.httpd.server_port}'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def queue(self, status, payload):
        self.responses.append((status, payload))

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def fake_server():
    server = FakeServer()
    yield server
    server.close()
