# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.foolslide import FoOlSlide


class Nifteam(FoOlSlide):
    id = 'nifteam'
    name = 'NIF Team'
    lang = 'it'

    base_url = 'https://read-nifteam.info'
    search_url = base_url + '/slide/search/'
    latest_updates_url = base_url + '/slide/'
    manga_list_url = base_url + '/slide/directory/'
    manga_url = base_url + '/slide/series/{0}'
    chapter_url = base_url + '/slide/read/{0}/it/{1}/page/1'

    name_selector = '.title h1'
    details_selector = None
    synopsis_selector = '.comic .info'
