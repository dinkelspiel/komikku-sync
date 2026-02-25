# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.manga_stream import MangaStream


class Pointzerotoons(MangaStream):
    id = 'pointzerotoons'
    name = 'Point Zero Toons'
    lang = 'pt_BR'

    date_format = '%d.%m.%Y'

    base_url = 'https://kitsuneyako.com'
    logo_url = base_url + '/wp-content/uploads/2026/01/cropped-Imagem-do-WhatsApp-de-2025-10-18-as-12.15.42_53866798-32x32.jpg'

    authors_selector = '.tsinfo .imptdt:-soup-contains("Artista") i, .tsinfo .imptdt:-soup-contains("Autor") i'
    genres_selector = '.tx-hero-genres a'
    scanlators_selector = '.tsinfo .imptdt:-soup-contains("Postado Por") i'
    status_selector = '.tsinfo .imptdt:-soup-contains("Status") i'
    synopsis_selector = '[itemprop="description"]'
