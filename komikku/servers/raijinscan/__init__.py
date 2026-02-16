# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import base64
from gettext import gettext as _
import logging

from bs4 import BeautifulSoup

from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number
from komikku.webview import CompleteChallenge

logger = logging.getLogger(__name__)


class Raijinscan(Server):
    id = 'raijinscan'
    name = 'Raijin Scan'
    lang = 'fr'
    has_cf = True

    base_url = 'https://raijin-scans.fr'
    logo_url = base_url + '/wp-content/uploads/2025/05/cropped-logopp-32x32.png'
    search_url = base_url + '/'
    manga_url = base_url + '/manga/{0}/'
    chapter_url = base_url + '/manga/{0}/{1}/'
    bypass_cf_url = base_url + '/manga/nano-machine-1/'

    filters = [
        {
            'key': 'statuses',
            'type': 'select',
            'name': _('Status'),
            'description': _('Filter by Statuses'),
            'value_type': 'multiple',
            'options': [
                {'key': 'on-going', 'name': _('Ongoing'), 'default': False},
                {'key': 'end', 'name': _('Completed'), 'default': False},
            ],
        },
        {
            'key': 'types',
            'type': 'select',
            'name': _('Type'),
            'description': _('Filter by Types'),
            'value_type': 'multiple',
            'options': [
                {'key': 'manga', 'name': _('Manga'), 'default': False},
                {'key': 'manhwa', 'name': _('Manhwa'), 'default': False},
                {'key': 'manhua', 'name': _('Manhua'), 'default': False},
            ],
        },
    ]
    long_strip_genres = ['Manhwa', 'Webtoon']

    def __init__(self):
        self.session = None

    @CompleteChallenge()
    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],  # not available
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        data['name'] = soup.select_one('.serie-title').text.strip()
        data['cover'] = soup.select_one('img.cover').get('src')

        # Details
        data['genres'] = [element.text.strip() for element in soup.select('.genre-list .grx div')]
        if element := soup.select_one('.stat-item .stat-details:-soup-contains("Type") .manga'):
            type = element.text.strip()
            if type not in data['genres']:
                data['genres'].append(type)

        if element := soup.select_one('.stat-item .stat-details:-soup-contains("État du titre") .manga'):
            status = element.text.strip()
            if status == 'En cours':
                data['status'] = 'ongoing'
            elif status == 'Terminé':
                data['status'] = 'complete'

        if element := soup.select_one('.stat-item .stat-details:-soup-contains("Auteur") .stat-value'):
            data['authors'].append(element.text.strip())
        if element := soup.select_one('.stat-item .stat-details:-soup-contains("Artiste") .stat-value'):
            artist = element.text.strip()
            if artist not in data['authors']:
                data['authors'].append(artist)

        # Synopsis
        data['synopsis'] = soup.select_one('.description').text.strip()

        # Chapters
        for element in reversed(soup.select('ul li.item')):
            if 'premium-chapter' in element.get('class'):
                continue
            a_element = element.select_one('a')
            date_element = a_element.select_one('.chapter-meta')
            slug = a_element.get('href').split('/')[-1]

            data['chapters'].append(dict(
                slug=slug,
                title=a_element.get('title'),
                num=slug if is_number(slug) else None,
                date=convert_date_string(date_element.text.strip(), languages=[self.lang]) if date_element else None,
            ))

        return data

    @CompleteChallenge()
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )
        for element in soup.select('.protected-image-data'):
            data['pages'].append(dict(
                image=base64.b64decode(element.get('data-src')).decode('utf-8'),
                slug=None,
            ))

        return data

    @CompleteChallenge()
    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            page['image'],
            headers={
                'Referer': self.chapter_url.format(manga_slug, chapter_slug),
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

    @CompleteChallenge()
    def get_latest_updates(self, statuses=None, types=None):
        """
        Returns recent mangas
        """
        return self.search(None, statuses=statuses, types=types, orderby='recently_added')

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    @CompleteChallenge()
    def get_most_populars(self, statuses=None, types=None):
        """
        Returns most viewed mangas
        """
        return self.search(None, statuses=statuses, types=types, orderby='most_viewed')

    @CompleteChallenge()
    def search(self, term, statuses=None, types=None, orderby=None):
        params = {
            'post_type': 'wp-manga',
            's': term or '',
        }
        if statuses:
            params['status[]'] = statuses
        if types:
            params['type[]'] = types
        if orderby:
            params['sort'] = orderby

        r = self.session_get(self.base_url, params=params)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.unit'):
            a_element = element.select_one('.info a')
            img_element = element.select_one('.poster > div > img')
            last_chapter_element = element.select_one('.info ul li:first-child .ch-num')

            results.append({
                'slug': a_element.get('href').split('/')[-2],
                'name': a_element.text.strip(),
                'cover': img_element.get('src'),
                'last_chapter': last_chapter_element.text.strip().split()[-1],
            })

        return results
