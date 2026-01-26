# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.manga_stream import MangaStream


class Tecnoscan(MangaStream):
    id = 'tecnoscan'
    name = 'Terco Scans (Tecno Scans)'
    lang = 'en'
    status = 'disabled'

    base_url = 'https://tercotoon.xyz'
    logo_url = base_url + '/wp-content/uploads/2024/11/cropped-LOGO-6-1-32x32.png'

    authors_selector = '.tsinfo .imptdt:-soup-contains("Artist") i, .tsinfo .imptdt:-soup-contains("Author") i'
    genres_selector = '.info-desc .mgen a'
    scanlators_selector = '.tsinfo .imptdt:-soup-contains("Serialization") i'
    status_selector = '.tsinfo .imptdt:-soup-contains("Status") i'
    synopsis_selector = '[itemprop="description"]'
