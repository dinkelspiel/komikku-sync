# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import logging
import re

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.webview import CompleteChallenge

logger = logging.getLogger(__name__)


class Madtheme(Server):
    base_url: str = None
    api_base_url: str = None
    api_chapters_url: str = None

    date_format = '%B %d, %Y'
    series_name = None

    search_results_selector = '.book-detailed-item'
    authors_selector = '.meta p:-soup-contains("Authors") a'
    status_selector = '.meta p:-soup-contains("Status") a'
    genres_selector = '.meta p:-soup-contains("Genres") a'
    synopsis_selector = 'p.content'
    chapters_selector = 'ul#chapter-list li > a'
    images_selector = '.chapter-image img'

    cover_src_attr = 'data-src'
    image_src_attr = 'data-src'

    filters = [
        {
            'key': 'status',
            'type': 'select',
            'name': _('Status'),
            'description': _('Filter by Status'),
            'value_type': 'single',
            'default': 'all',
            'options': [
                {'key': 'all', 'name': _('All')},
                {'key': 'ongoing', 'name': _('Ongoing')},
                {'key': 'complete', 'name': _('Completed')},
            ]
        },
    ]

    def __init__(self):
        self.search_url = self.base_url + '/search'
        if self.series_name:
            self.manga_url = f'{self.base_url}/{self.series_name}' + '/{0}'
            self.chapter_url = f'{self.base_url}/{self.series_name}' + '/{0}/{1}'
        else:
            self.manga_url = self.base_url + '/{0}'
            self.chapter_url = self.base_url + '/{0}/{1}'
        if not self.api_chapters_url:
            self.api_chapters_url = self.api_base_url + '/manga/{0}/chapters?source=detail'

        if self.session is None and not self.has_cf:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    @CompleteChallenge()
    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        r = self.session_get(
            self.manga_url.format(initial_data['slug'])
        )
        if r.status_code != 200:
            return None

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
        ))

        soup = BeautifulSoup(r.text, 'lxml')

        data['name'] = soup.select_one('h1').text.strip()
        data['cover'] = soup.select_one('#cover img').get(self.cover_src_attr)

        # Details
        for element in soup.select(self.authors_selector):
            data['authors'].append(element.text.replace(',', '').strip())

        if element := soup.select_one(self.status_selector):
            status = element.text.strip()
            data['status'] = 'complete' if status == 'Completed' else 'ongoing'

        for element in soup.select(self.genres_selector):
            data['genres'].append(element.text.replace(',', '').strip())

        if element := soup.select_one(self.synopsis_selector):
            data['synopsis'] = element.text.strip()

        # Chapters
        self.get_manga_chapters_data(data, soup)

        return data

    @CompleteChallenge()
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
            self.api_chapters_url.format(sid),
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
                'date': convert_date_string(date_element.text.strip(), format=self.date_format, languages=[self.lang]),
            })

    @CompleteChallenge()
    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            page['image'],
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=page['image'].split('/')[-1],
        )

    def get_manga_id(self, soup):
        """
        Get manga server Id
        """
        sid = None
        for script_element in soup.find_all('script'):
            script = script_element.string
            if not script or 'var bookId' not in script:
                continue

            for line in script.split('\n'):
                line = line.strip()

                if matches := re.search(r'bookId = ([0-9]*);', script):
                    sid = matches.group(1)
                    break

            break

        return sid

    def get_manga_chapter_id(self, soup):
        """
        Get a manga chapter server Id
        """
        sid = None
        for script_element in soup.find_all('script'):
            script = script_element.string
            if not script or 'var chapterId' not in script:
                continue

            for line in script.split('\n'):
                line = line.strip()

                if matches := re.search(r'chapterId = ([0-9]*);', script):
                    sid = matches.group(1)
                    break

            break

        return sid

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_manga_list(self, term=None, status=None, orderby=None):
        params = {}
        if orderby == 'popular':
            params['sort'] = 'views'
        elif orderby == 'latest':
            params['sort'] = 'updated_at'
        else:
            params['q'] = term
        if status:
            params['status'] = status

        r = self.session_get(self.search_url, params=params)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for item in soup.select(self.search_results_selector):
            a_element = item.select_one('.title a')
            a_thumb_element = item.select_one('.thumb a img')

            if element := a_thumb_element.select_one('latest-chapter'):
                last_chapter = element.text.strip()
            else:
                last_chapter = None

            results.append({
                'slug': a_element.get('href').split('/')[-1],
                'name': a_element.text.strip(),
                'cover': a_thumb_element.get(self.cover_src_attr),
                'last_chapter': last_chapter,
            })

        return results

    @CompleteChallenge()
    def get_latest_updates(self, status=None):
        """
        Returns list of latest manga
        """
        return self.get_manga_list(status=status, orderby='latest')

    @CompleteChallenge()
    def get_most_populars(self, status=None):
        """
        Returns list of popular manga
        """
        return self.get_manga_list(status=status, orderby='popular')

    @CompleteChallenge()
    def search(self, term, status=None):
        return self.get_manga_list(term=term, status=status)
