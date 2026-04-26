# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from bs4 import BeautifulSoup

from komikku.servers.multi.heancms import HeanCMS


class Kenscans(HeanCMS):
    id = 'kenscans'
    name = 'Kenscans'
    lang = 'en'

    base_url = 'https://kencomics.com'
    logo_url = base_url + '/favicon-32x32.png'
    api_url = 'https://api.kencomics.com/api'

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Pages URLs are available in a <script> element
        """
        r = self.session_get(
            self.chapter_url.format(manga_slug, chapter_slug),
            headers={
                'Referer': self.manga_url.format(manga_slug),
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )
        for image in soup.select('.image-container img'):
            data['pages'].append(dict(
                slug=None,
                image=image.get('src'),
            ))

        return data
