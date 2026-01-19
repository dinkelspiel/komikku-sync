# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import json
import re

from bs4 import BeautifulSoup

from komikku.servers.multi.madara import Madara2
from komikku.utils import get_buffer_mime_type

# 2025/01 fusion of Sinensis and Cerise => SCtoon (Peachscan)
# 2025/09 SCtoon => Lovers Toon (Madara)


class Sinensistoon(Madara2):
    id = 'sinensistoon'
    name = 'Lovers Toon (Sinensis/Cerise)'
    lang = 'pt_BR'

    date_format = '%d.%m.%Y'

    base_url = 'https://loverstoon.com'
    logo_url = base_url + '/wp-content/uploads/2025/09/cropped-faviliocon-32x32.png'
    chapters_url = base_url + '/manga/{0}/ajax/chapters/'

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(
            self.chapter_url.format(manga_slug, chapter_slug),
            headers={
                'Referer': self.manga_url.format(manga_slug),
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )

        found = False
        if script_element := soup.select_one('.page-break script'):
            script = script_element.string
            if script:
                re_pages = r'content:\s+(\[[\s\S*]+\])'
                if matches := re.search(re_pages, script):
                    found = True
                    pages = json.loads(matches.group(1))
                    for index, url in enumerate(pages):
                        data['pages'].append(dict(
                            slug=None,
                            image=url,
                            index=index + 1,
                        ))

        if not found:
            return None

        return data
