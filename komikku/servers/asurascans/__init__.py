# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import json

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.multi.madara import Madara
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type


class Asurascans(Server):
    id = 'asurascans'
    name = 'Asura Scans'
    lang = 'en'

    base_url = 'https://asurascans.com'
    logo_url = base_url + '/images/logo.webp'
    search_url = base_url + '/browse'
    manga_url = base_url + '/comics/{0}'
    chapter_url = base_url + '/comics/{0}/chapter/{1}'

    filters = [
        {
            'key': 'type',
            'type': 'select',
            'name': _('Type'),
            'description': _('Filter by Type'),
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': _('All')},
                {'key': 'manga', 'name': _('Manga')},
                {'key': 'manhwa', 'name': _('Manhwa')},
                {'key': 'manhua', 'name': _('Manhua')},
            ],
        },
    ]

    long_strip_genres = [
        'Manhwa',
        'Manhua',
    ]

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': USER_AGENT,
            })

    def check_slug(self, initial_data):
        # A random number is always appended to slug and it changes regularly
        # Try to retrieve new slug
        res = self.search(initial_data['name'], '')
        if not res:
            return None

        for item in res:
            base_slug = '-'.join(initial_data['slug'].split('-')[:-1])
            current_base_slug = '-'.join(item['slug'].split('-')[:-1])
            if current_base_slug in (initial_data['slug'], base_slug) and initial_data['slug'] != item['slug']:
                return item['slug']

        return None

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        if new_slug := self.check_slug(initial_data):
            initial_data['slug'] = new_slug

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.content, 'lxml')

        data = initial_data.copy()
        data.update({
            'authors': [],
            'scanlators': [],
            'genres': [],
            'status': None,
            'synopsis': None,
            'chapters': [],
            'server_id': self.id,
        })

        # Name & cover
        data['name'] = soup.select_one('h1').text.strip()
        data['cover'] = soup.select_one('#mobile-cover-img').get('src')

        # Details
        for element in soup.select('a.inline-flex.text-xs.font-medium'):
            data['genres'].append(element.text.strip())

        if element := soup.select_one('div:-soup-contains("Type") ~ div span:last-child'):
            data['genres'].append(element.text.strip().capitalize())

        if element := soup.select_one('div:-soup-contains("Status") ~ div span:last-child'):
            status = element.text.strip().lower()
            if status in 'ongoing':
                data['status'] = 'ongoing'
            elif status == 'completed':
                data['status'] = 'complete'
            elif status in ('axed', 'dropped'):
                data['status'] = 'suspended'
            elif status == 'hiatus':
                data['status'] = 'hiatus'

        if author_element := soup.select_one('div:-soup-contains("Author") ~ a'):
            author = author_element.text.strip()
            if author and author != '_':
                data['authors'].append(author)
        if author_element := soup.select_one('div:-soup-contains("Artist") ~ a'):
            author = author_element.text.strip()
            if author and author != '_' and author not in data['authors']:
                data['authors'].append(author)

        if element := soup.select_one('#description-text'):
            data['synopsis'] = element.text.strip()

        # Chapters
        data['chapters'] = self.get_manga_chapters_data(soup)

        return data

    def get_manga_chapters_data(self, soup):
        chapters = []

        for a_element in reversed(soup.select('div.divide-y > a.group')):
            slug = a_element.get('href').split('/')[-1]
            if date_element := a_element.select_one('span.text-sm'):
                date = convert_date_string(date_element.text.strip())
            else:
                date = None

            chapters.append({
                'slug': slug,
                'title': a_element.select_one('span.font-medium').text.strip(),
                'num': slug,
                'date': date,
            })

        return chapters

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(
            self.chapter_url.format(manga_slug, chapter_slug),
            headers={
                'Referer': self.manga_url.format(manga_slug),
            })
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')
        info = json.loads(soup.select_one('astro-island').get('props'))

        data = {
            'pages': [],
        }
        for page in info['pages'][1]:
            data['pages'].append({
                'slug': None,
                'image': page[1]['url'][1],
            })

        return data

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

    def get_manga_list(self, term=None, type=None, orderby=None):
        params = {}
        if term:
            params['q'] = term
        if orderby:
            params['order'] = 'desc'
            if orderby == 'popular':
                params['sort'] = 'popular'
        if type:
            params['type'] = type

        r = self.session_get(
            self.search_url,
            params=params,
            headers={
                'Referer': self.base_url,
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.content, 'lxml')

        results = []
        for a_element in soup.select('.series-card[data-series-id] > a'):
            cover_element = a_element.select_one('img[loading="lazy"]')

            results.append({
                'slug': a_element.get('href').split('/')[-1],
                'name': cover_element.get('alt').strip(),
                'cover': cover_element.get('src') if cover_element else None,
            })

        return results

    def get_latest_updates(self, type):
        return self.get_manga_list(type=type, orderby='latest')

    def get_most_populars(self, type):
        return self.get_manga_list(type=type, orderby='popular')

    def search(self, term, type):
        return self.get_manga_list(term=term, type=type)


class Asurascans_tr(Madara):
    id = 'asurascans_tr'
    name = 'Armoni Scans (Asura Scans)'
    lang = 'tr'

    has_cf = True

    date_format = '%d %B %Y'

    base_url = 'https://asurascans.com.tr'
