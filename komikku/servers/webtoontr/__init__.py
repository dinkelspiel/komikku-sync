# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.madara import Madara


class Webtoontr(Madara):
    id = 'webtoontr'
    name = 'Webtoon TR'
    lang = 'tr'
    status = 'disabled'  # Dead source
    is_nsfw = True

    date_format = '%d/%m/%Y'
    series_name = 'webtoon'

    base_url = 'https://webtoontr.net'
    logo_url = base_url + '/wp-content/uploads/2021/08/cropped-Icon2-32x32.png'
    chapter_url = base_url + '/' + series_name + '/{0}/{1}/'

    details_synopsis_selector = '.manga-excerpt'
