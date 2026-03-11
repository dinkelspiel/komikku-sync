# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import logging

from bs4 import BeautifulSoup

from komikku.servers.multi.madtheme import Madtheme
from komikku.servers.utils import convert_date_string
from komikku.webview import CompleteChallenge

logger = logging.getLogger(__name__)


class Kaliscan(Madtheme):
    id = 'kaliscan'
    name = 'KaliScan'
    lang = 'en'

    base_url = 'https://kaliscan.com'
    logo_url = base_url + '/static/sites/icons/favicon-32x32.png'
    api_base_url = base_url + '/service/backend'
    api_chapters_url = api_base_url + '/chaplist/'
    api_chapter_url = api_base_url + '/chapterServer/'

    series_name = 'manga'

    synopsis_selector = 'p.content ~ p'
    images_selector = '.chapter-image'

    @CompleteChallenge()
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML content

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

        soup = BeautifulSoup(r.text, 'lxml')

        sid = self.get_manga_chapter_id(soup)
        if sid is None:
            logger.warning('Failed to get `%s` chapter server Id', manga_name)
            return None

        r = self.session_get(
            self.api_chapter_url,
            params={
                'server_id': 1,
                'chapter_id': sid,
            },
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
        for element in soup.select(self.images_selector):
            data['pages'].append(dict(
                slug=None,
                image=element.get(self.image_src_attr),
            ))

        return data

    def get_manga_chapters_data(self, data, soup=None):
        """
        Get list of chapters
        """
        sid = self.get_manga_id(soup)
        if sid is None:
            logger.warning('Failed to get `%s` server Id', data['name'])
            return

        r = self.session_get(
            self.api_chapters_url,
            params={
                'manga_id': sid,
            },
            headers={
                'Referer': self.manga_url.format(data['slug']),
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        for element in reversed(soup.select(self.chapters_selector)):
            title_element = element.select_one('.chapter-title')
            date_element = element.select_one('.chapter-update')

            data['chapters'].append({
                'slug': element.get('href').split('/')[-1],
                'title': title_element.text.strip(),
                'date': convert_date_string(date_element.text.strip(), languages=[self.lang]),
            })
