# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number


class Weebcentral(Server):
    id = 'weebcentral'
    name = 'Weeb Central'
    lang = 'en'

    base_url = 'https://weebcentral.com'
    logo_url = base_url + '/favicon.ico'
    search_url = base_url + '/search/data'
    manga_url = base_url + '/series/{0}'
    chapters_url = base_url + '/series/{0}/full-chapter-list'
    chapter_url = base_url + '/chapters/{0}'
    images_url = base_url + '/chapters/{0}/images?is_prev=False&reading_style=long_strip'
    cover_url = 'https://temp.compsci88.com/cover/normal/{0}.webp'

    filters = [
        {
            'key': 'adult',
            'type': 'select',
            'name': _('Adult Content'),
            'description': _('Filter by Adult Content'),
            'value_type': 'single',
            'default': 'Any',
            'options': [
                {'key': 'Any', 'name': _('Any')},
                {'key': 'True', 'name': _('Yes')},
                {'key': 'False', 'name': _('No')},
            ]
        },
        {
            'key': 'types',
            'type': 'select',
            'name': _('Types'),
            'description': _('Filter by Types'),
            'value_type': 'multiple',
            'options': [
                {'key': 'Manga', 'name': _('Manga'), 'default': False},
                {'key': 'Manhwa', 'name': _('Manhwa'), 'default': False},
                {'key': 'Manhua', 'name': _('Manhua'), 'default': False},
                {'key': 'OEL', 'name': _('OEL'), 'default': False},
            ],
        },
        {
            'key': 'statuses',
            'type': 'select',
            'name': _('Statuses'),
            'description': _('Filter by Statuses'),
            'value_type': 'multiple',
            'options': [
                {'key': 'Ongoing', 'name': _('Ongoing'), 'default': False},
                {'key': 'Complete', 'name': _('Complete'), 'default': False},
                {'key': 'Hiatus', 'name': _('Hiatus'), 'default': False},
                {'key': 'Canceled', 'name': _('Canceled'), 'default': False},
            ]
        },
    ]
    long_strip_genres = ['Manhua', 'Manhwa']

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        data = initial_data.copy()
        data.update({
            'authors': [],
            'scanlators': [],  # not available
            'genres': [],
            'status': None,
            'synopsis': None,
            'chapters': [],
            'server_id': self.id,
        })

        soup = BeautifulSoup(r.text, 'lxml')

        data['name'] = soup.select_one('h1').text.strip()
        data['cover'] = self.cover_url.format(data['slug'])

        # Details
        for a_element in soup.select('li:-soup-contains("Author") span a'):
            data['authors'].append(a_element.text.strip())

        for a_element in soup.select('li:-soup-contains("Tag") span a, li:-soup-contains("Type") a'):
            data['genres'].append(a_element.text.strip())

        if a_element := soup.select_one('li:-soup-contains("Status") a'):
            status = a_element.text.strip()

            if status == 'Complete':
                data['status'] = 'complete'
            elif status == 'Ongoing':
                data['status'] = 'ongoing'
            elif status == 'Hiatus':
                data['status'] = 'hiatus'
            elif status == 'Canceled':
                data['status'] = 'suspended'

        data['synopsis'] = soup.select_one('p.whitespace-pre-wrap.break-words').text.strip()

        # Chapters
        r = self.session_get(
            self.chapters_url.format(data['slug']),
            headers={
                'Hx-Current-Url': self.manga_url.format(data['slug']),
                'Hx-Request': 'true',
                'Hx-Target': 'chapter-list',
                'Referer': self.manga_url.format(data['slug']),
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        for a_element in reversed(soup.select('a')):
            title_element = a_element.select_one('span.flex > span')
            if not title_element:
                continue

            scanlator = 'Unknown'
            if img_element := soup.select_one('span:first-child > img'):
                if 'official' in img_element.get('src'):
                    scanlator = 'Offical'

            title = title_element.text.strip()
            num = title.split(' ')[-1]  # chapter number theoretically is at end of chapter title

            data['chapters'].append({
                'slug': a_element.get('href').split('/')[-1],
                'title': title,
                'scanlators': [scanlator],
                'num': num if is_number(num) else None,
                'date': convert_date_string(a_element.select_one('time').get('datetime').split('T')[0], '%Y-%m-%d'),
            })

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        r = self.session_get(
            self.images_url.format(chapter_slug),
            headers={
                'Hx-Current-Url': self.chapter_url.format(chapter_slug),
                'Hx-Request': 'true',
                'Referer': self.chapter_url.format(chapter_slug),
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = {
            'pages': [],
        }
        for element in soup.select('img'):
            data['pages'].append({
                'slug': None,
                'image': element.get('src'),
            })

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            page['image'],
            headers={
                'Referer': self.chapter_url.format(chapter_slug),
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return {
            'buffer': r.content,
            'mime_type': mime_type,
            'name': page['image'].split('/')[-1],
        }

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_latest_updates(self, adult=None, types=None, statuses=None):
        return self.search(orderby='Latest Updates', adult=adult, statuses=statuses, types=types)

    def get_most_populars(self, adult=None, types=None, statuses=None):
        return self.search(orderby='Popularity', adult=adult, statuses=statuses, types=types)

    def search(self, term='', orderby='Best Match', adult=None, types=None, statuses=None):
        r = self.session_get(
            self.search_url,
            params={
                'author': '',
                'text': term,
                'sort': orderby,
                'order': 'Ascending',
                'official': 'Any',
                'adult': adult,
                'included_status': statuses,
                'included_type': types,
                'display_mode': 'Minimal Display',
            },
            headers={
                'Hx-Current-Url': f'{self.base_url}/search',
                'Hx-Request': 'true',
                'Hx-Target': 'search-results',
                'Hx-Trigger': 'advanced-search-form',
                'Referer': f'{self.base_url}/search',
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for a_element in soup.select('article > a'):
            slug = a_element.get('href').split('/')[-2]

            results.append({
                'slug': slug,
                'name': a_element.text.strip(),
                'cover': self.cover_url.format(slug),
            })

        return results
