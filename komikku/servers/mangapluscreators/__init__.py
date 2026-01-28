# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from functools import wraps
import json

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number

LANGUAGES_CODES = dict(
    en='en',
    es='es',
)


def set_lang(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        server = args[0]

        if not server.csrf_token:
            r = server.session_get(server.base_url)

            soup = BeautifulSoup(r.text, 'lxml')
            server.csrf_token = soup.select_one('meta[name="csrf-token"]')['content']

        if not server.is_lang_set:
            server.session_post(
                server.api_set_language,
                data={
                    'language': LANGUAGES_CODES[server.lang],
                },
                headers={
                    'X-CSRF-TOKEN': server.csrf_token,
                }
            )
            server.is_lang_set = True

        return func(*args, **kwargs)

    return wrapper


class Mangapluscreators(Server):
    id = 'mangapluscreators'
    name = 'MANGA Plus Creators by SHUEISHA'
    lang = 'en'
    status = 'disabled'  # commercial platforms are no supported

    is_lang_set = False
    csrf_token = None

    base_url = 'https://mangaplus-creators.jp/'
    logo_url = base_url + '/favicon.ico'
    search_url = base_url + '/keywords/'
    popular_url = base_url + '/titles/popular/'
    latest_updates_url = base_url + '/titles/recent?t=episode'
    manga_url = base_url + '/titles/{0}'
    chapter_url = base_url + '/episodes/{0}'
    api_url = base_url + '/api'
    api_set_language = api_url + '/language/set_language'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers = {'User-Agent': USER_AGENT}

    @set_lang
    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping chapter HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],
            genres=[],
            status='ongoing',
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        data['name'] = soup.select_one('.title').text.strip()
        data['cover'] = soup.select_one('.cover img').get('data-src')

        for element in soup.select('.tag-genre'):
            data['genres'].append(element.text.strip())

        for element in soup.select('.name-group .name'):
            data['authors'].append(element.text.strip())

        data['synopsis'] = soup.select_one('.summary').text.strip()

        for element in soup.select('.mod-item-series'):
            title = element.select_one('.number').text.strip()
            num = title[1:] if title.startswith('#') else None
            date = element.select_one('.latest-update').text.strip()

            data['chapters'].append({
                'slug': element.get('href').split('/')[-1],
                'title': title,
                'num': num if is_number(num) else None,
                'date': convert_date_string(date, '%Y-%m-%d'),
            })

        return data

    @set_lang
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(chapter_slug))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        if element := soup.select_one('div[react="viewer"]'):
            pages = json.loads(element.get('data-pages'))
        else:
            return None

        data = dict(
            pages=[],
        )
        for page in pages['pc']:
            data['pages'].append({
                'slug': None,
                'image': page['image_url'],
                'index': page['page_no'],
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

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name='{0:03d}.{1}'.format(page['index'], mime_type.split('/')[1]),
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    @set_lang
    def get_latest_updates(self):
        """
        Returns latest updates
        """
        r = self.session_get(self.latest_updates_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.item-recent'):
            name = element.select_one('.title-area .title').text.strip()
            cover = element.select_one('.image img').get('src')
            slug = cover.split('/')[5]  # serie slug is available in cover URL only
            last_chapter = element.select_one('.issue').text.strip()

            results.append(dict(
                slug=slug,
                name=name,
                cover=cover,
                last_chapter=last_chapter,
            ))

        return results

    @set_lang
    def get_most_populars(self):
        """
        Returns popular
        """
        r = self.session_get(self.popular_url, params={
            'p': 'm',  # 30 days
            'l': LANGUAGES_CODES[self.lang],
        })
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.item-recent'):
            name = element.select_one('.title-area .title').text.strip()
            cover = element.select_one('.image img').get('src')
            slug = cover.split('/')[5]  # serie slug is available in cover URL only
            last_chapter = element.select_one('.issue').text.strip()

            results.append(dict(
                slug=slug,
                name=name,
                cover=cover,
                last_chapter=last_chapter,
            ))

        return results

    def search(self, term):
        r = self.session_get(self.search_url, params={'q': term, 'l': self.lang})
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.item-search'):
            name = element.select_one('.title-area .title').text.strip()
            cover = element.select_one('.image img').get('src')
            slug = cover.split('/')[5]  # serie slug is available in cover URL only
            last_chapter = element.select_one('.issue').text.strip()

            results.append(dict(
                slug=slug,
                name=name,
                cover=cover,
                last_chapter=last_chapter,
            ))

        return results


class Mangapluscreators_es(Mangapluscreators):
    id = 'mangapluscreators_es'
    lang = 'es'
