# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.madara import Madara2


class Mangasorigines(Madara2):
    id = 'mangasorigines'
    name = 'Mangas Origines'
    lang = 'fr'
    is_nsfw = True

    series_name = 'oeuvre'

    base_url = 'https://mangas-origines.fr'
    logo_url = base_url + '/wp-content/uploads/2023/07/cropped-favmo3-32x32.png'
    chapters_url = base_url + '/' + series_name + '/{0}/ajax/chapters/?t=1'

    details_cover_selector = 'picture > img'
    chapters_date_selector = '.timediff'

    images_src_attr = 'data-src'
