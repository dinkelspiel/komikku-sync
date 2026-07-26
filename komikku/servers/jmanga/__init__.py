# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _

from komikku.servers.multi.mangareader import Mangareader


class Jmanga(Mangareader):
    id = 'jmanga'
    name = 'JManga'
    lang = 'ja'
    is_nsfw = True

    base_url = 'https://jmanga.care'
    list_url = base_url + '/filter/'
    search_url = base_url + '/'
    manga_url = base_url + '/read/{0}/'
    chapter_url = base_url + '/read/{0}/{1}/{2}/'
    api_chapter_images_url = base_url + '/json/chapter?mode=vertical&id={0}'

    filters = [
        {
            'key': 'type',
            'type': 'select',
            'name': _('Type'),
            'description': _('Filter by Type'),
            'value_type': 'single',
            'default': 'all',
            'options': [
                {'key': 'all', 'name': '全て'},
                {'key': 'Raw Manga', 'name': 'Raw Manga'},
                {'key': 'BLコミック', 'name': 'BLコミック'},
                {'key': 'TLコミック', 'name': 'TLコミック'},
                {'key': 'オトナコミック', 'name': _('オトナコミック')},
                {'key': '女性マンガ', 'name': '女性マンガ'},
                {'key': '少女マンガ', 'name': '少女マンガ'},
                {'key': '少年マンガ', 'name': '少年マンガ'},
                {'key': '青年マンガ', 'name': '青年マンガ'},
            ],
        },
        {
            'key': 'status',
            'type': 'select',
            'name': _('Status'),
            'description': _('Filter by Status'),
            'value_type': 'single',
            'default': 'all',
            'options': [
                {'key': 'all', 'name': '全て'},
                {'key': 'Publishing', 'name': _('Ongoing')},
                {'key': 'Completed', 'name': _('Complete')},
            ],
        },
    ]

    languages_codes = {
        # 'en': 'en',
        'ja': 'ja',
    }
