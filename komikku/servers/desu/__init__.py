# SPDX-FileCopyrightText: 2020-2026 GrownNed
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: GrownNed <grownned@gmail.com>
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from datetime import datetime

import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.utils import get_buffer_mime_type

SERVER_NAME = 'Desu'

headers = {
    'User-Agent': USER_AGENT,
}


class Desu(Server):
    id = 'desu'
    name = SERVER_NAME
    lang = 'ru'
    is_nsfw = True

    base_url = 'https://desu.uno'
    logo_url = base_url + '/styles/favicons/favicon-32x32.png?v=1'
    api_url = base_url + '/api'
    api_search_url = api_url + '/manga'
    api_manga_url = api_url + '/manga/{0}'
    api_chapters_url = api_url + '/manga/{0}/chapters'
    api_chapter_url = api_url + '/manga/{0}/chapters/{1}'

    manga_title_css_selector = 'h1 > span.name'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers = headers

    def get_manga_data(self, initial_data):
        """
        Returns manga data from API

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(
            self.api_manga_url.format(initial_data['slug']),
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()['manga']

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

        data['name'] = resp_data['russian']
        data['url'] = resp_data['view_url']
        data['cover'] = resp_data['cover']['preview']

        if resp_data.get('translators'):
            data['scanlators'] = [t['name'] for t in resp_data['translators']]
        data['genres'] = [genre['name'] for genre in resp_data['genres']]
        if resp_data['status'] == 'ongoing':
            data['status'] = 'ongoing'
        elif resp_data['status'] == 'released':
            data['status'] = 'complete'
        data['synopsis'] = resp_data['description']

        # Chapters
        r = self.session_get(
            self.api_chapters_url.format(initial_data['slug']),
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()['chapters']

        for chapter in reversed(resp_data):
            title = ''
            if volume := chapter.get('volume'):
                title += f'Том {volume}'
            if number := chapter.get('number'):
                title += f' Глава {number}'
            if chapter.get('title'):
                title += f' - {chapter["title"]}'

            data['chapters'].append({
                'slug': chapter['chapter_id'],
                'title': title,
                'num': number,
                'date': datetime.fromtimestamp(chapter['publish_date']).date(),
            })

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data from API

        Currently, only pages are expected.
        """
        r = self.session_get(
            self.api_chapter_url.format(manga_slug, chapter_slug),
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()['chapter']

        data = {
            'pages': [],
        }
        for page in resp_data['pages']:
            data['pages'].append({
                'slug': None,
                'image': page['url'],
            })

        return data

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

        return {
            'buffer': r.content,
            'mime_type': mime_type,
            'name': page['image'].split('/')[-1].split('?')[0],
        }

    @staticmethod
    def get_manga_url(slug, url):
        """
        Returns manga absolute URL
        """
        return url

    def get_latest_updates(self):
        """
        Returns latest updated mangas
        """
        return self.search('', orderby='updated')

    def get_most_populars(self):
        """
        Returns most popular mangas (bayesian rating)
        """
        return self.search('', orderby='popular')

    def search(self, term, orderby=None):
        params = {
            'limit': 50,
        }
        if orderby is not None:
            params['order_by'] = orderby
        else:
            params['search'] = term

        r = self.session_get(
            f'{self.api_search_url}/',
            params=params,
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()['mangas']

        return [{
            'slug': item['manga_id'],
            'name': item['russian'],
            'cover': item['cover']['preview'],
            # last_chapter=item['chapters']['updated']['number'],
        } for item in resp_data]
