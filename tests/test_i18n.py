import ast
import string
from pathlib import Path

import pytest

import clippings
import i18n
import phone
from test_phone import FakeAdb

PLUGIN = Path(__file__).resolve().parent.parent / 'plugin'


def marked_texts():
    texts = set()
    for path in PLUGIN.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('_', 'N_') \
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                texts.add(node.args[0].value)
    return texts


def placeholders(text):
    return {field for _literal, field, _spec, _conversion in string.Formatter().parse(text) if field}


@pytest.fixture
def english():
    i18n.set_language('en')
    yield
    i18n.set_language('fr')


def test_every_marked_text_has_an_english_translation_with_the_same_placeholders():
    texts = marked_texts()

    assert sorted(text for text in texts if text not in i18n.ENGLISH) == []
    assert sorted(text for text in i18n.ENGLISH if text not in texts) == []
    assert [text for text, english in i18n.ENGLISH.items() if placeholders(text) != placeholders(english)] == []


def test_it_follows_calibre_unless_a_language_is_chosen():
    assert i18n.resolve('auto', 'fr') == 'fr'
    assert i18n.resolve('auto', 'fr_CA') == 'fr'
    assert i18n.resolve('auto', 'de') == 'en'
    assert i18n.resolve('auto', None) == 'en'
    assert i18n.resolve('en', 'fr') == 'en'
    assert i18n.resolve('fr', 'en_US') == 'fr'


def test_messages_and_references_switch_to_english(english):
    with pytest.raises(phone.PhoneError, match='No phone detected'):
        phone.connect('adb', FakeAdb(devices='List of devices attached\n\n'))
    passage = clippings.parse(
        'Dune\r\n- Your Highlight on page 3 | location 12-14 | Added on Monday, 12 December 2022 08:50:25\r\n\r\nFear.\r\n==========\r\n'
    )[0]

    assert passage.reference == 'p. 3 · loc. 12-14 · 12/12/2022'
    assert i18n.language_label('German') == 'German'
    assert i18n._('Texte absent du catalogue') == 'Texte absent du catalogue'


def test_language_names_follow_the_interface_language():
    assert i18n._('Tout cocher') == 'Tout cocher'
    assert i18n.language_label('German') == 'Allemand'
