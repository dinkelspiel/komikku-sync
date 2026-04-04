# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import time

from bs4 import BeautifulSoup
import requests

from komikku.consts import DOWNLOAD_MAX_DELAY
from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import get_response_elapsed


class Iken(Server):
    base_url: str
    api_url: str
    logo_url: str

    manga_url: str = None
    chapter_url: str = None
    api_manga_list_url: str = None
    api_manga_url: str = None
    api_chapters_url: str = None
    api_chapter_url: str = None

    headers: dict = None

    def __init__(self):
        if not self.headers:
            self.headers = {
                'Accept': 'application/json',
                'Origin': self.base_url,
                'User-Agent': USER_AGENT,
            }

        if self.manga_url is None:
            self.manga_url = self.base_url + '/series/{0}'
        if self.chapter_url is None:
            self.chapter_url = self.base_url + '/series/{0}/{1}'
        if self.api_manga_list_url is None:
            self.api_manga_list_url = self.api_url + '/series'
        if self.api_manga_url is None:
            self.api_manga_url = self.api_url + '/series/{0}'
        if self.api_chapters_url is None:
            self.api_chapters_url = self.api_url + '/series/{0}/chapters'
        if self.api_chapter_url is None:
            self.api_chapter_url = self.api_url + '/series/{0}/chapters/{1}'

        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update(self.headers)

    def get_manga_data(self, initial_data):
        """
        Returns manga data via API request

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        r = self.session_get(
            self.api_manga_url.format(initial_data['slug']),
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()

        data = initial_data.copy()
        data.update({
            'name': resp_data['title'],
            'authors': [],
            'scanlators': [],
            'genres': [],
            'status': 'ongoing',
            'synopsis': None,
            'chapters': [],
            'server_id': self.id,
            'cover': resp_data['cover'],
        })

        # Details
        for genre in resp_data['genres']:
            data['genres'].append(genre['name'])

        if resp_data['status'] == 'COMPLETED':
            data['status'] = 'complete'
        elif resp_data['status'] == 'ONGOING':
            data['status'] = 'ongoing'
        elif resp_data['status'] == 'DROPPED':
            data['status'] = 'suspended'
        elif resp_data['status'] == 'HIATUS':
            data['status'] = 'hiatus'

        if resp_data.get('author'):
            for author in resp_data['author'].split(','):
                data['authors'].append(author.strip())
        if resp_data.get('artist'):
            for artist in resp_data['artist'].split(','):
                data['authors'].append(artist.strip())

        if synopsis := resp_data['description']:
            data['synopsis'] = BeautifulSoup(synopsis, 'lxml').text.strip()

        # Chapters
        data['chapters'] = self.get_manga_chapters_data(resp_data['slug'])

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data via API
        """
        r = self.session_get(
            self.api_chapter_url.format(manga_slug, chapter_slug),
            headers={
                'Referer': self.manga_url.format(manga_slug),
            }
        )
        if r.status_code != 200:
            return None

        data = {
            'pages': [],
        }
        for image in r.json()['images']:
            data['pages'].append({
                'slug': None,
                'image': image['url'],
            })

        return data

    def get_manga_chapters_data(self, slug):
        """
        Returns manga chapters list via API
        """
        chapters = []

        def get_page(serie_id, page):
            r = self.session_get(
                self.api_chapters_url.format(slug),
                params={
                    'page': page,
                    'perPage': 30,
                    'sort': 'desc',
                },
                headers={
                    'Referer': f'{self.base_url}/',
                }
            )
            if r.status_code != 200:
                return None, False, None

            data = r.json()
            if not data.get('data'):
                return None, False, None

            more = data['totalPages'] > page

            return data['data'], more, get_response_elapsed(r)

        chapters = []
        delay = None
        more = True
        page = 1
        while more:
            if delay:
                time.sleep(delay)

            chapters_page, more, rtime = get_page(slug, page)
            if chapters_page:
                for chapter in chapters_page:
                    prefix = '🔒 ' if not chapter.get('isFree', True) else ''

                    chapters.append({
                        'slug': chapter['slug'],
                        'title': f'{prefix}Chapter {chapter["number"]}',
                        'num': chapter['number'],
                        'date': convert_date_string(chapter['createdAt'].split('T')[0], '%Y-%m-%d') if 'createdAt' in chapter else None,
                    })
                page += 1
                delay = min(rtime * 2, DOWNLOAD_MAX_DELAY) if rtime else None

            elif chapters_page is None:
                # Failed to retrieve a chapters list page, abort
                break

        return list(reversed(chapters))

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

    def get_latest_updates(self):
        """
        Returns latest updates
        """
        return self.get_manga_list(orderby='latest')

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_manga_list(self, term=None, orderby=None):
        url = self.api_manga_list_url

        params = {
            'page': 1,
            'perPage': 20,
        }
        if term:
            url += '/search'
            params['q'] = term
        else:
            params['sort'] = orderby

        r = self.session_get(
            url,
            params=params,
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            print(r.json())
            return None

        results = []
        for item in r.json()['data']:
            results.append({
                'slug': item['slug'],
                'name': item['title'],
                'cover': item['cover'],
            })

        return results

    def get_most_populars(self):
        """
        Returns most popular mangas
        """
        return self.get_manga_list(orderby='popular')

    def search(self, term):
        return self.get_manga_list(term=term)
