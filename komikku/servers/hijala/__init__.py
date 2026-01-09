# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.manga_stream import MangaStream


class Hijala(MangaStream):
    id = 'hijala'
    name = 'Hijala'
    lang = 'ar'

    has_cf = True

    base_url = 'https://hijala.com'

    authors_selector = '.tsinfo .imptdt:-soup-contains("الرسام") i, .tsinfo .imptdt:-soup-contains("المؤلف") i'
    genres_selector = '.info-desc .mgen a'
    scanlators_selector = '.tsinfo .imptdt:-soup-contains("نشر من قبل") i'
    status_selector = '.tsinfo .imptdt:-soup-contains("الحالة") i'
    synopsis_selector = '[itemprop="description"]'
