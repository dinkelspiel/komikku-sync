# SPDX-FileCopyrightText: 2026 Willem Dinkelspiel <mail@keii.dev>
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from datetime import UTC
from datetime import datetime

import pytest

from komikku.models import SyncedChapter
from komikku.models import SyncedManga
from komikku.models import SyncedState


def test_binary_and_text_round_trip():
    state = SyncedState((
        SyncedManga(
            slug='作品',
            server_id='mangadex',
            name='Manga name',
            url='https://example.org/manga',
            chapters=(
                SyncedChapter('chapter-1', '1', True),
                SyncedChapter(None, '2.5', False, 1787737385123, 17),
                SyncedChapter('special', None, True),
            ),
        ),
        SyncedManga('empty', 'local', (), None, None),
    ))

    payload = state.encode()

    assert payload.startswith(SyncedState.MAGIC)
    assert SyncedState.decode(payload) == state
    assert SyncedState.from_text(state.to_text()) == state


def test_binary_format_fixture():
    state = SyncedState((SyncedManga(
        'manga',
        'server',
        (SyncedChapter('chapter-1', '1', False),),
    ),))

    assert state.encode().hex() == '4b53594e0278da6364cd4dcc4b4f642b4e2d2a4b2d62606064e34cce482c28492dd235643404008192082f'


def test_decodes_legacy_binary_format():
    payload = bytes.fromhex('4b53594e0178da6364cd4dcc4b4f642b4e2d2a4b2d62606064e34cce482c28492dd235643404008192082f')

    assert SyncedState.decode(payload) == SyncedState((SyncedManga(
        'manga',
        'server',
        (SyncedChapter('chapter-1', '1', False),),
    ),))


def test_from_mangas():
    class Record:
        def __init__(self, **values):
            vars(self).update(values)

    manga = Record(
        slug='manga',
        server_id='server',
        name='Name',
        url=None,
        chapters=[
            Record(
                slug='chapter',
                num=1.0,
                read=1,
                last_read=datetime(2026, 8, 26, 10, 3, 5, 123000, UTC),
                last_page_read_index=12,
            ),
            Record(slug=None, num=None, read=0),
        ],
    )

    state = SyncedState.from_mangas([manga])

    assert state == SyncedState((SyncedManga(
        'manga',
        'server',
        (
            SyncedChapter('chapter', '1.0', True, 1787738585123, 12),
            SyncedChapter(None, None, False),
        ),
        'Name',
        None,
    ),))


def test_binary_is_smaller_than_compact_json():
    state = SyncedState((SyncedManga(
        'manga',
        'server',
        tuple(SyncedChapter(f'chapter-{number}', str(number), number % 2 == 0) for number in range(100)),
        'Name',
        'https://example.org/manga',
    ),))
    json_data = {
        'server:manga': {
            'slug': 'manga',
            'server_id': 'server',
            'name': 'Name',
            'url': 'https://example.org/manga',
            'chapters': [
                {'slug': chapter.slug, 'num': chapter.num, 'read': chapter.read}
                for chapter in state.mangas[0].chapters
            ],
        },
    }

    assert len(state.encode()) < len(json.dumps(json_data, separators=(',', ':')).encode())


@pytest.mark.parametrize('payload', [
    b'',
    b'KSYN\x03payload',
    SyncedState.MAGIC,
    SyncedState.MAGIC + b'not-zlib',
    SyncedState(()).encode() + b'extra',
])
def test_rejects_invalid_binary(payload):
    with pytest.raises((TypeError, ValueError)):
        SyncedState.decode(payload)


@pytest.mark.parametrize('text', ['', 'invalid', 'ksync:not*base64'])
def test_rejects_invalid_text(text):
    with pytest.raises(ValueError):
        SyncedState.from_text(text)
