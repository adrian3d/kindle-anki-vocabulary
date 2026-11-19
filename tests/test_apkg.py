import csv
import json
import sqlite3
import zipfile

import apkg
from apkg import Note

NOTES = [
    Note('en:stench', 'stench', 'puanteur', 'free of that rotting stench', 'stench', 'Siege & Storm', ('kindle', 'siege-storm')),
    Note('en:billowing', 'billow', 'onduler', 'his <black> kefta billowing around him', 'billowing', 'Siege & Storm'),
]


def read_collection(path, tmp_path):
    with zipfile.ZipFile(path) as package:
        assert sorted(package.namelist()) == ['collection.anki2', 'media']
        package.extract('collection.anki2', tmp_path)
    return sqlite3.connect(tmp_path / 'collection.anki2')


def test_it_writes_notes_and_cards_in_the_named_deck(tmp_path):
    path = tmp_path / 'deck.apkg'

    apkg.write_apkg(path, 'English vocabulary', NOTES, reverse=True, timestamp=1763596800.0)

    conn = read_collection(path, tmp_path)
    models, decks = conn.execute('SELECT models, decks FROM col').fetchone()
    deck_id = next(int(key) for key, deck in json.loads(decks).items() if deck['name'] == 'English vocabulary')
    fields = conn.execute('SELECT flds FROM notes ORDER BY id').fetchall()
    assert [field['name'] for field in json.loads(models)[str(apkg.MODEL_ID)]['flds']] == list(apkg.FIELDS)
    assert fields[0][0].split('\x1f') == ['stench', 'puanteur', 'free of that rotting <b>stench</b>', 'Siege &amp; Storm', '', '1']
    assert fields[1][0].split('\x1f')[2] == 'his &lt;black&gt; kefta <b>billowing</b> around him'
    assert conn.execute('SELECT tags FROM notes ORDER BY id').fetchone()[0] == ' kindle siege-storm '
    assert conn.execute('SELECT did, ord FROM cards ORDER BY id').fetchall() == [(deck_id, 0), (deck_id, 1)] * 2


def test_it_writes_a_single_card_per_note_without_reverse(tmp_path):
    path = tmp_path / 'deck.apkg'

    apkg.write_apkg(path, 'Deck', NOTES, reverse=False)

    conn = read_collection(path, tmp_path)
    assert conn.execute('SELECT ord FROM cards').fetchall() == [(0,), (0,)]
    assert conn.execute('SELECT flds FROM notes').fetchone()[0].endswith('\x1f')


def test_it_keeps_identifiers_stable_between_exports(tmp_path):
    def guids(name):
        apkg.write_apkg(tmp_path / name, 'Deck', NOTES)
        with zipfile.ZipFile(tmp_path / name) as package:
            package.extract('collection.anki2', tmp_path / name.replace('.apkg', ''))
        conn = sqlite3.connect(tmp_path / name.replace('.apkg', '') / 'collection.anki2')
        return conn.execute('SELECT guid FROM notes ORDER BY id').fetchall(), conn.execute('SELECT decks FROM col').fetchone()

    assert guids('a.apkg') == guids('b.apkg')


def test_it_writes_an_anki_csv_with_file_headers(tmp_path):
    path = tmp_path / 'deck.csv'
    notes = NOTES + [Note('hl:x', 'so much as', 'ne serait-ce que, "même"', 'If you so much as move', 'so much as', '', ('kindle',), 'Renforce.')]

    apkg.write_csv(path, 'English vocabulary', notes)

    lines = path.read_text(encoding='utf-8').splitlines()
    assert lines[:5] == ['#separator:Comma', '#html:true', '#deck:English vocabulary', '#tags column:6', '#guid column:7']
    rows = list(csv.reader(lines[5:]))
    assert rows[0][:6] == ['stench', 'puanteur', 'free of that rotting <b>stench</b>', 'Siege &amp; Storm', '', 'kindle siege-storm']
    assert rows[2][:6] == ['so much as', 'ne serait-ce que, "même"', 'If you <b>so much as</b> move', '', 'Renforce.', 'kindle']
    assert len({row[6] for row in rows}) == 3


def test_it_formats_a_highlighted_passage_as_a_quote(tmp_path):
    passage = Note('passage:1', 'La peur tue\nl\'esprit <vite>.', 'Dune', book='Dune', note='p. 12', passage=True)
    apkg.write_apkg(tmp_path / 'deck.apkg', 'Citations', [passage], reverse=False)
    apkg.write_csv(tmp_path / 'deck.csv', 'Citations', [passage])

    conn = read_collection(tmp_path / 'deck.apkg', tmp_path)
    fields = conn.execute('SELECT flds, sfld FROM notes').fetchone()
    expected = '<div class="passage">La peur tue<br>l\'esprit &lt;vite&gt;.</div>'
    assert fields[0].split('\x1f') == [expected, 'Dune', '', 'Dune', 'p. 12', '']
    assert fields[1] == 'La peur tue\nl\'esprit <vite>.'
    assert conn.execute('SELECT ord FROM cards').fetchall() == [(0,)]
    assert next(csv.reader((tmp_path / 'deck.csv').read_text(encoding='utf-8').splitlines()[5:]))[:2] == [expected, 'Dune']


def test_it_highlights_whole_words_only():
    assert apkg.highlight_sentence('The art of war; war is art.', 'war') == 'The art of <b>war</b>; war is art.'
    assert apkg.highlight_sentence('Wartime stories', 'war') == 'Wartime stories'
    assert apkg.make_tag('Siege and Storm (Leigh Bardugo)') == 'siege-and-storm-leigh-bardugo'
