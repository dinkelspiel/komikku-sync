# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number


class Shadowmanga(Server):
    id = 'shadowmanga'
    name = 'Shadow Manga'
    lang = 'es'
    is_nsfw = True

    base_url = 'https://shademanga.com'
    logo_url = base_url + '/favicon.png'

    manga_url = base_url + '/serie/local/{0}'
    chapter_url = base_url + '/reader/local/{0}'

    api_url = base_url + '/api/series-locales'
    api_latest_updates_url = api_url + '/novedades'
    api_most_popular = api_url + '/popular'
    api_search_url = api_url + '/search-candidates'
    api_manga_url = api_url + '/{0}'
    api_chapter_url = api_url + '/{0}/capitulos/{1}/paginas'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Returns serie data using API

        Initial data should contain at least serie's slug (provided by search)
        """
        r = self.session_get(
            self.api_manga_url.format(initial_data['slug']),
            headers={
                'Referer': self.manga_url.format(initial_data['slug']),
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()

        data = initial_data.copy()
        data.update({
            'name': resp_data['titulo'],
            'authors': [],
            'scanlators': [],
            'genres': [],
            'status': None,
            'synopsis': resp_data['descripcion'],
            'chapters': [],
            'server_id': self.id,
            'cover': resp_data['portadaUrl'],
        })

        # Authors
        if author := resp_data.get('autor'):
            data['authors'].append(author)

        # Genres
        if genres := resp_data.get('generos'):
            for genre in genres.strip().split(','):
                genre = genre.strip()
                if genre:
                    data['genres'].append(genre)

        # Status
        status = resp_data['estado']
        if status == 'En curso':
            data['status'] = 'ongoing'
        elif status == 'Completado':
            data['status'] = 'complete'
        elif status == 'Pausada':
            data['status'] = 'hiatus'

        # Chapters
        chapters = []
        for chapter in sorted(resp_data['capitulos'], key=lambda i: i['orden']):
            num = chapter['numeroCapitulo']
            title = f'Cap. {num}'
            if chapter['titulo'] and chapter['titulo'] != title:
                title = f'{title} - {chapter["titulo"]}'
            chapters.append({
                'slug': chapter['id'],
                'title': title,
                'num': num if is_number(num) else None,
                'date': convert_date_string(chapter['fechaSubida'].split('T')[0], format='%Y-%m-%d'),
            })

        data['chapters'] = chapters

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns serie chapter data using API

        Currently, only pages are expected.
        """
        r = self.session_get(
            self.api_chapter_url.format(manga_slug, chapter_slug),
            headers={
                'Referer': self.chapter_url.format(chapter_slug),
            }
        )
        if r.status_code != 200:
            return None

        data = {
            'pages': [],
        }
        for url in r.json()['paginas']:
            data['pages'].append({
                'slug': None,
                'image': url,
            })

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(page['image'])
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
        Returns serie absolute URL
        """
        return self.manga_url.format(slug)

    def get_latest_updates(self):
        r = self.session_get(
            self.api_latest_updates_url,
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        result = {}
        for genre in r.json():
            for serie in genre['series']:
                if serie['id'] in result:
                    continue
                result[serie['id']] = {
                    'name': serie['titulo'],
                    'slug': serie['id'],
                    'cover': serie['portadaUrl'],
                }

        return list(result.values())

    def get_most_populars(self):
        r = self.session_get(
            self.api_most_popular,
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        result = {}
        for genre in r.json():
            for serie in genre['series']:
                if serie['id'] in result:
                    continue
                result[serie['id']] = {
                    'name': serie['titulo'],
                    'slug': serie['id'],
                    'cover': serie['portadaUrl'],
                }

        return list(result.values())

    def search(self, term):
        r = self.session_get(
            self.api_search_url,
            params={
                'q': term,
                'includeAdult': 'true',
                'showSinPortada': 'false',
                'take': 120,
            },
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        result = []
        for serie in r.json():
            result.append({
                'name': serie['titulo'],
                'slug': serie['id'],
                'cover': serie['portadaUrl'],
            })

        return result
