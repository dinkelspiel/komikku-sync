# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.madara import Madara


class Mangalek(Madara):
    id = 'mangalek'
    name = 'مانجا ليك Mangalek'
    lang = 'ar'

    has_cf = True

    date_format = '%Y ,%d %B'

    base_url = 'https://mangalik.net'
    logo_url = 'https://io.mangalik.net/wp-content/app/lekmanganet/512.png'
    chapter_url = base_url + '/manga/{0}/{1}/'

    bypass_cf_url = base_url + '/manga/apotheosis/'

    # Mirrors
    # https://lekmanga.online/
    # https://lekmanga.site
    # https://manga-leko.site
    # https://like-manga.net
