# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.manga_stream import MangaStream


class Rimuscans(MangaStream):
    id = 'rimuscans'
    name = 'Rimu Scans'
    lang = 'fr'
    status = 'disabled'  # theme change

    has_cf = True

    base_url = 'https://rimuscans.com'

    authors_selector = None
    genres_selector = '.mgen a'
    scanlators_selector = None
    status_selector = None
    synopsis_selector = '[itemprop="description"]'

    def is_long_strip(self, data):
        return True
