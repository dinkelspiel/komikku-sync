# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import datetime
from functools import wraps
from gettext import gettext as _
import json
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


def convert_old_slug(slug):
    # for ex: 4-one-piece => one_piece
    if slug.split('-')[0].isdigit():
        return '_'.join(slug.split('-')[1:])

    return slug


def get_data(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        server = args[0]
        if server.csrf_token:
            return func(*args, **kwargs)

        r = server.session_get(server.base_url)
        if r.status_code != 200:
            return func(*args, **kwargs)

        soup = BeautifulSoup(r.text, 'lxml')

        for script_element in soup.select('script'):
            script = script_element.string
            if not script:
                continue

            if '_token' in script:
                # CSRF token
                for line in script.split('\n'):
                    line = line.strip()
                    if match := server.re_csrf_token.search(line):
                        server.csrf_token = match.group(1)
                        break

            elif 'window.laravel.route' in script:
                # Various data: latest updates, genres...
                for line in script.split('\n'):
                    line = line.strip()
                    if line.startswith('window.laravel.route'):
                        try:
                            data = json.loads(line[23:-1].replace(',}', '}'))['data']
                        except Exception:
                            logger.error('Failed to parse homepage and retrieved data')
                        else:
                            server.data = dict(
                                genres=dict(),
                                latest_updates=[],
                            )

                            slugs = []
                            for item in data['published']:
                                slug = item['manga']['url'].split('/')[-1]
                                if slug in slugs:
                                    continue

                                last_chapter = item['chapters'][0]
                                number = last_chapter['number']
                                if last_chapter['subNumber']:
                                    number = f'{number}.{last_chapter["subNumber"]}'

                                server.data['latest_updates'].append(dict(
                                    slug=slug,
                                    name=item['manga']['title'],
                                    cover=item['manga']['cover'],
                                    last_chapter=f'{number} - {last_chapter["name"]}',
                                ))
                                slugs.append(slug)

                            for genre in data['genre-map']:
                                server.data['genres'][genre['genre_id']] = genre['genre_name']

                        break

        return func(*args, **kwargs)

    return wrapper


class Mangatube(Server):
    id = 'mangatube'
    name = 'Manga-Tube'
    lang = 'de'
    is_nsfw = True

    has_captcha = True  # Custom captcha challange

    base_url = 'https://manga-tube.me'
    search_url = base_url + '/search'
    manga_url = base_url + '/series/{0}'
    chapter_url = base_url + '/series/{0}/read/{1}/1'
    image_url = 'https://a.mtcdn.org/m/{0}/{1}/{2}'
    api_url = base_url + '/api'
    api_search_url = api_url + '/manga/search'
    api_manga_url = api_url + '/manga/{0}'
    api_chapters_url = api_url + '/manga/{0}/chapters'
    api_chapter_url = api_url + '/manga/{0}/chapter/{1}'

    filters = [
        {
            'key': 'type',
            'type': 'select',
            'name': _('Type'),
            'description': _('Type of Serie'),
            'value_type': 'single',
            'default': None,
            'options': [
                {'key': '-1', 'name': _('All')},
                {'key': '0', 'name': _('Manga')},
                {'key': '1', 'name': _('Manhwa')},
                {'key': '2', 'name': _('Manhua')},
                {'key': '3', 'name': _('Webtoon')},
                {'key': '4', 'name': _('Comic')},
                {'key': '5', 'name': _('Oneshot')},
                {'key': '6', 'name': _('Light Novel')},
            ]
        },
        {
            'key': 'mature',
            'type': 'select',
            'name': _('Age Rating'),
            'description': _('Maturity'),
            'value_type': 'single',
            'default': None,
            'options': [
                {'key': '-1', 'name': _('Without')},
                {'key': '1', 'name': _('16+')},
                {'key': '2', 'name': _('18+')},
            ]
        },
    ]

    re_csrf_token = re.compile(r'.*\"_token\": \"([a-zA-Z0-9]*)\".*')

    def __init__(self):
        # Data retrieved by parsing JS code in home page (genres, latest updates)
        self.csrf_token = None
        self.data = None

        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    @CompleteChallenge()
    @get_data
    def get_manga_data(self, initial_data):
        """
        Returns manga data using API

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        slug = convert_old_slug(initial_data['slug'])

        r = self.session_get(self.api_manga_url.format(slug), headers={
            'Content-Type': 'application/json, text/plain, */*',
            'Referer': self.manga_url.format(initial_data['slug']),
            'Use-Parameter': 'manga_slug',
            'X-Csrf-TOKEN': self.csrf_token,
            'X-Requested-With': 'XMLHttpRequest',
        })
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/plain':
            return None

        resp_data = r.json()['data']['manga']

        data = dict(
            slug=slug,
            name=resp_data['title'],
            authors=[],
            scanlators=[],
            genres=[],
            status=None,
            synopsis=resp_data['description'],
            chapters=[],
            server_id=self.id,
            cover=resp_data['cover'],
        )

        # Details
        for artist in resp_data['artist']:
            data['authors'].append(artist['name'])
        for author in resp_data['author']:
            if author['name'] not in data['authors']:
                data['authors'].append(author['name'])

        if self.data and self.data.get('genres'):
            for genre_id in resp_data['genre']:
                data['genres'].append(self.data['genres'][genre_id])

        if resp_data['status'] == 0:
            data['status'] = 'ongoing'
        elif resp_data['status'] == 1:
            data['status'] = 'hiatus'
        elif resp_data['status'] == 3:
            data['status'] = 'suspended'
        elif resp_data['status'] == 4:
            data['status'] = 'complete'

        # Chapters
        r = self.session_get(self.api_chapters_url.format(initial_data['slug']), headers={
            'Content-Type': 'application/json, text/plain, */*',
            'Include-Teams': 'true',
            'Referer': self.manga_url.format(initial_data['slug']),
            'Use-Parameter': 'manga_slug',
            'X-Csrf-TOKEN': self.csrf_token,
            'X-Requested-With': 'XMLHttpRequest',
        })
        if r.status_code != 200:
            return data

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/plain':
            return None

        chapters = r.json()['data']['chapters']

        for chapter in reversed(chapters):
            number = chapter['number']
            if chapter['subNumber']:
                number = f'{number}.{chapter["subNumber"]}'

            title = f'[Band {chapter["volume"]}] Kapitel {number} - {chapter["name"]}'

            data['chapters'].append(dict(
                slug=chapter['id'],
                title=title,
                num=number,
                num_volume=chapter['volume'],
                date=convert_date_string(chapter['publishedAt'].split(' ')[0], format='%Y-%m-%d'),
                scanlators=[team['name'] for team in chapter['teams']],
            ))

        return data

    @CompleteChallenge()
    @get_data
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data using API

        Currently, only pages are expected.
        """
        r = self.session_get(self.api_chapter_url.format(manga_slug, chapter_slug), headers={
            'Content-Type': 'application/json, text/plain, */*',
            'Referer': self.chapter_url.format(manga_slug, chapter_slug),
            'Use-Parameter': 'manga_slug',
            'X-Csrf-TOKEN': self.csrf_token,
            'X-Requested-With': 'XMLHttpRequest',
        })
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/plain':
            return None

        data = dict(
            pages=[],
        )
        for index, page in enumerate(r.json()['data']['chapter']['pages']):
            data['pages'].append(dict(
                slug=None,
                image=page['url'],
                index=index + 1,
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(page['image'], headers={
            'Referer': f'{self.base_url}/',
        })
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name='{0:03d}.{1}'.format(page['index'], mime_type.split('/')[-1]),
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    @CompleteChallenge()
    @get_data
    def get_latest_updates(self, **kwargs):
        return self.data['latest_updates'] if self.data else None

    @CompleteChallenge()
    def get_most_populars(self, type=None, mature=None):
        return self.search(populars=True, type=type, mature=mature)

    @CompleteChallenge()
    def search(self, term=None, populars=False, type=None, mature=None):
        params = {
            'year[]': [1970, datetime.date.today().year],
            'type': type if type is not None else -1,
            'status': -1,
            'mature': mature if mature is not None else -1,
            'query': term if term is not None else '',
            'rating[]': [1, 5],
            'page': 1,
            'sort': 'desc' if populars else 'asc',
            'order': 'rating' if populars else 'name',
        }

        r = self.session_get(self.api_search_url, params=params, headers={
            'Content-Type': 'application/json, text/plain, */*',
            'Referer': self.search_url,
            'X-Requested-With': 'XMLHttpRequest',
        })
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/plain':
            return None

        resp_data = r.json()

        results = []
        for item in resp_data['data']:
            results.append(dict(
                slug=item['slug'],
                name=item['title'],
                cover=item['cover'],
            ))

        return results
