# SPDX-FileCopyrightText: 2026 Willem Dinkelspiel <mail@keii.dev>
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import UTC
from datetime import datetime

from komikku.models import SyncedChapter
from komikku.sync import merge_chapter_state


class Record:
    def __init__(self, **values):
        vars(self).update(values)

    def update(self, data):
        vars(self).update(data)
        self.updated = data


def test_merge_chapter_state_uses_latest_resume_position():
    local_time = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
    remote_time = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    chapter = Record(slug='chapter-1', num='1', read=0, last_read=local_time, last_page_read_index=3)
    manga = Record(chapters=[chapter], last_read=local_time)
    remote = SyncedChapter('chapter-1', '1', False, int(remote_time.timestamp() * 1000), 12)

    assert merge_chapter_state(manga, (remote,)) == 1
    assert chapter.last_read == remote_time
    assert chapter.last_page_read_index == 12
    assert manga.last_read == remote_time


def test_merge_chapter_state_keeps_newer_local_resume_position():
    local_time = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    remote_time = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
    chapter = Record(slug='chapter-1', num='1', read=0, last_read=local_time, last_page_read_index=12)
    manga = Record(chapters=[chapter], last_read=local_time)
    remote = SyncedChapter('chapter-1', '1', True, int(remote_time.timestamp() * 1000), 3)

    assert merge_chapter_state(manga, (remote,)) == 1
    assert chapter.read == 1
    assert chapter.last_read == local_time
    assert chapter.last_page_read_index == 12
    assert manga.last_read == local_time
