# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.foolslide import FoOlSlide


class Deathtollscans(FoOlSlide):
    id = 'deathtollscans'
    name = 'Death Toll Reader'
    lang = 'en'

    base_url = 'https://reader.deathtollscans.net'
    search_url = base_url + '/search/'
    manga_list_url = base_url + '/directory/'
    manga_url = base_url + '/series/{0}/'
    chapter_url = base_url + '/read/{0}/en/{1}/page/1'
