# SPDX-FileCopyrightText: 2023-2024 Pierre-Emmanuel Devin
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Pierre-Emmanuel Devin <pierreemmanuel.devin@posteo.net>
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import logging
import time
from urllib.parse import unquote

from bs4 import BeautifulSoup
import requests

from komikku.consts import DOWNLOAD_MAX_DELAY
from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import parse_nextjs_hydration
from komikku.utils import get_buffer_mime_type
from komikku.utils import get_response_elapsed
from komikku.utils import is_number

logger = logging.getLogger(__name__)


class Littlexgarden(Server):
    id = 'littlexgarden'
    name = 'Punk Records (Little Garden)'
    lang = 'fr'

    base_url = 'https://punkrecordz.com'
    logo_url = base_url + '/favicon.ico'
    manga_list_url = base_url + '/mangas'
    manga_url = base_url + '/mangas/{0}'
    chapter_url = base_url + '/mangas/{0}/{1}?display=vertical'

    api_base_url = 'https://api.punkrecordz.com'
    api_url = api_base_url + '/graphql'
    image_url = api_base_url + '/images/webp/{0}.webp'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Returns manga data via GraphQL API

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        # Chapters
        def get_page(cursor, limit):
            r = self.session_post(
                self.api_url,
                json={
                    'operationName': 'chapters',
                    'query': 'query chapters($slug: String, $number: Float, $limit: Int = 12, $skip: Int = 0, $order: Float = -1) {\n  chapters(\n    limit: $limit\n    skip: $skip\n    where: {number: $number, deleted: false, published: true, manga: {slug: $slug, published: true, deleted: false}}\n    order: [{field: \"number\", order: $order}]\n  ) {\n    id\n    likes\n    number\n    thumb\n  }\n}',
                    'variables': {
                        'limit': limit,
                        'order': 1,
                        'skip': cursor,
                        'slug': initial_data['slug'],
                    },
                },
                headers={
                    'Content-Type': 'application/json',
                    'Referer': f'{self.base_url}/',
                }
            )
            if r.status_code != 200:
                return None, None

            chunk = r.json()['data']['chapters']
            count = len(chunk)
            next_cursor = cursor + count if count > 0 else None

            return chunk, next_cursor, get_response_elapsed(r)

        chapters = []
        cover = None
        cursor = 0
        delay = None
        while cursor is not None:
            if delay:
                time.sleep(delay)

            chunk, cursor, rtime = get_page(cursor, 500)
            for chapter in chunk:
                num = chapter['number']

                chapters.append(dict(
                    slug=str(num),  # slug nust be a string
                    title=f'Chapitre {num}',
                    num=num if is_number(num) else None,
                    date=None,
                ))

                if cover is None:
                    # Use 1st image of 1st chapter as cover
                    cover = self.image_url.format(chapter['thumb'])

            delay = min(rtime * 2, DOWNLOAD_MAX_DELAY) if rtime else None

        data = initial_data.copy()
        data.update(dict(
            authors=[],  # not available
            scanlators=[],  # not available
            genres=[],  # not available
            status=None,  # not available
            synopsis=None,  # not available
            chapters=chapters,
            server_id=self.id,
            cover=cover,
        ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = {
            'pages': [],
        }
        for index, element in enumerate(soup.select('img[data-nimg="1"]'), start=1):
            data['pages'].append(dict(
                slug=unquote(element.get('src')).split('/')[-1].split('.webp')[0],
                image=None,
                index=index,
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(self.image_url.format(page['slug']))
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
        Returns manga absolute url
        """
        return self.manga_url.format(slug)

    def get_latest_updates(self):
        """
        Returns latest updated manga
        """
        r = self.session_get(self.base_url)
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        slugs = []
        for a_element in soup.select('section:-soup-contains("Les derniers scans") a'):
            slug = a_element.get('href').split('/')[1]
            if slug in slugs:
                continue

            cover = None
            if cover_element := a_element.select_one('div > div > div:last-child > div'):
                for style in cover_element.get('style').split(';'):
                    if not style.startswith('background-image'):
                        continue
                    cover = style[21:-1]

            results.append(dict(
                name=a_element.select_one('h4').text.strip(),
                slug=slug,
                cover=cover,
                last_chapter=a_element.select_one('p.chakra-text').text.strip(),
            ))
            slugs.append(slug)

        return results

    def get_manga_list(self):
        """
        Returns all manga
        """
        r = self.session_get(self.manga_list_url)
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        info = parse_nextjs_hydration(soup, 'slug')
        if info is None:
            return None

        results = []
        for item in info[3]['children'][3]['data']:
            results.append(dict(
                name=item['name'],
                slug=item['slug'],
                cover=self.image_url.format(item['thumb']),
            ))

        return results

    def get_most_populars(self):
        return self.get_manga_list()

    def search(self, term):
        mangas = self.get_manga_list()
        if mangas is None:
            return None

        results = []
        for manga in mangas:
            if term.lower() in manga['name'].lower():
                results.append(manga)

        return results
