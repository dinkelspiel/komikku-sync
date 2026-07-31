# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.foolslide import FoOlSlide


class Juinjutsuteam(FoOlSlide):
    id = 'juinjutsuteam'
    name = 'Juin Jutsu Team'
    lang = 'it'

    base_url = 'https://www.juinjutsureader.ovh'
    search_url = base_url + '/search/'
    latest_updates_url = base_url + '/latest/1/'
    manga_list_url = base_url + '/directory/'
    manga_url = base_url + '/series/{0}'
    chapter_url = base_url + '/read/{0}/it/{1}/page/1'

    name_selector = '#container_comic_content > .title_high'
    cover_selector = 'img.thumb'
    details_selector = '.info_comic b'
    synopsis_selector = '.trama'
    chapters_list_selector = '.list_chapter .element'
    chapters_list_link_selector = '.title_chapter > a'
    latest_updates_list_selector = '.list_elements > .group > .title_manga > a'
    search_list_selector = '.series_element'
    search_last_chapter_selector = '.cap a'
    search_list_cover_selector = 'img.thumb'
