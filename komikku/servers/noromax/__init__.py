# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.manga_stream import MangaStream


class Noromax(MangaStream):
    id = 'noromax'
    name = 'Noromax'
    lang = 'id'

    name_re_sub = r'Bahasa Indonesia'
    series_name = 'manga'

    base_url = 'https://noromax02.my.id'
    logo_url = base_url + '/wp-content/uploads/2026/02/cropped-Untitled-1-150x150.png'

    authors_selector = '.infox .fmed:-soup-contains("Artist") span, .infox .fmed:-soup-contains("Author") span'
    genres_selector = '.infox .mgen a'
    scanlators_selector = '.infox .fmed:-soup-contains("Serialization") span'
    status_selector = '.tsinfo .imptdt:-soup-contains("Status") i'
    synopsis_selector = '[itemprop="description"]'
