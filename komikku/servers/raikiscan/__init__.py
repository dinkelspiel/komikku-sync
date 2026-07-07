# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.manga_stream import MangaStream


class Raikiscan(MangaStream):
    id = 'raikiscan'
    name = 'Raiki Scan'
    lang = 'es'
    status = 'disabled'

    base_url = 'https://raikiscan.com'
    logo_url = base_url + '/wp-content/uploads/2021/08/cropped-logo.5-32x32.png'

    authors_selector = '.tsinfo .imptdt:-soup-contains("Autor") i, .tsinfo .imptdt:-soup-contains("Artista") i'
    genres_selector = '.info-desc .mgen a'
    scanlators_selector = '.tsinfo .imptdt:-soup-contains("Serialización") i'
    status_selector = '.tsinfo .imptdt:-soup-contains("Estado") i'
    synopsis_selector = '[itemprop="description"]'
