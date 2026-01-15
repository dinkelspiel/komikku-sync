# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.manga_stream import MangaStream


class Mangastop(MangaStream):
    id = 'mangastop'
    name = 'Manga Stop'
    lang = 'pt_BR'
    is_nsfw = True

    has_cf = True

    base_url = 'https://mangastop.net'
    logo_url = 'https://images.mangastop.net/file/bucketamz/2025/09/logomarca-150x150.png'
    bypass_cf_url = base_url + '/manga/martial-peak/'

    authors_selector = '.j-manga-info p:-soup-contains("Artista") a, .j-manga-info p:-soup-contains("Autor") a'
    genres_selector = '.info-desc .mgen a, .tsinfo .imptdt:-soup-contains("Type") a'
    scanlators_selector = None
    status_selector = '.tsinfo .imptdt:-soup-contains("Status") i'
    synopsis_selector = '[itemprop="description"]'

    long_strip_genres = [
        'Manhua',
        'Manhwa',
    ]
