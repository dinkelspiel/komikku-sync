# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests

from komikku.servers.multi.madara import Madara2


class Toonily(Madara2):
    id = 'toonily'
    name = 'Toonily'
    lang = 'en'
    is_nsfw = True

    date_format = '%b %-d, %y'
    medium = None
    series_name = 'serie'

    base_url = 'https://toonily.com'
    logo_url = base_url + '/wp-content/uploads/2024/01/cropped-toonfavicon_color_changed-32x32.png'
    chapter_url = base_url + '/' + series_name + '/{0}/{1}/'

    results_selector = '.manga'
    result_name_slug_selector = '.post-title a'
    result_cover_selector = '.item-thumb img'

    def is_long_strip(self, _manga_data):
        return True

    def search(self, term, nsfw, orderby=None):
        params = {}
        if orderby is None:
            params.update({
                's': term or '',
                'post_type': 'wp-manga',
                'author': '',
                'artist': '',
                'release': '',
            })
        elif orderby == 'populars':
            params['m_orderby'] = 'views'
        elif orderby == 'latest':
            params['m_orderby'] = 'latest'

        cookie = requests.cookies.create_cookie(
            name='toonily-mature',
            value=str(int(nsfw)),
            domain=urlparse(self.base_url).netloc,
            path='/',
            expires=None,
        )
        self.session.cookies.set_cookie(cookie)

        r = self.session_get(f'{self.base_url}/webtoons/', params=params)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.page-item-detail'):
            thumb_element = element.select_one('.item-thumb')
            if not thumb_element.a:
                continue

            last_chapter_element = element.select_one('.chapter-item .chapter')
            if cover_element := thumb_element.a.img:
                cover = cover_element.get('src')
            else:
                cover = None

            results.append(dict(
                slug=thumb_element.a.get('href').split('/')[-2],
                name=thumb_element.a.get('title').strip(),
                cover=cover,
                last_chapter=last_chapter_element.text.strip() if last_chapter_element else None,
            ))

        return results
