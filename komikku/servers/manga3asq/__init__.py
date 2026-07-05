# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import re

from komikku.servers.multi.madara import Madara2


class Manga3asq(Madara2):
    id = 'manga3asq'
    name = 'مانجا العاشق'
    lang = 'ar'

    date_format = '%Y \u060c%B %-d'

    base_url = 'https://3asq.pro'
    logo_url = base_url + '/wp-content/uploads/2021/06/cropped-ICON-32x32.png'
    chapters_url = base_url + '/manga/{0}/ajax/chapters/'
    chapter_url = base_url + '/manga/{0}/{1}/'

    details_synopsis_selector = '.manga-excerpt'

    @staticmethod
    def extract_chapter_nums_from_slug(slug):
        re_nums = r'(\d+)[-_]?(\d+)?.*'

        if matches := re.search(re_nums, slug):
            if num := matches.group(1):
                num = f'{int(num)}'

                if num_dec := matches.group(2):
                    num = f'{num}.{int(num_dec)}'

                return num, None

        return None, None
