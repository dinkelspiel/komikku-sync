# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.manga_stream import MangaStream


class Shadowmangas(MangaStream):
    id = 'shadowmangas'
    name = 'ShadowMangas'
    lang = 'es'
    is_nsfw = True
    status = 'disabled'

    base_url = 'https://shadowmangas.com'
    logo_url = 'https://i3.wp.com/shadowmangas.com/wp-content/uploads/2022/09/cropped-icoweb-32x32.png'

    authors_selector = '.infox .fmed:-soup-contains("Author") span, .infox .fmed:-soup-contains("Artist") span'
    genres_selector = '.mgen a'
    scanlators_selector = None
    status_selector = '.tsinfo .imptdt:-soup-contains("Status") i'
    synopsis_selector = '[itemprop="description"]'
