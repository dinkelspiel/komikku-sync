# SPDX-FileCopyrightText: 2023-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

# Supported servers:
# JManga [JA]
# MangaReader [EN/FR/JA/KO/ZH_HANS] (disabled)

from gettext import gettext as _
from io import BytesIO
import urllib.parse

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.exceptions import ServerException
from komikku.servers.utils import unscramble_image_rc4
from komikku.utils import get_buffer_mime_type


class Mangareader(Server):
    base_url: str
    search_url: str
    list_url: str
    manga_url: str
    chapter_url: str
    api_chapter_images_url: str

    languages_codes: dict

    scrambled_images = False
    slug_position: int = -2

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'user-agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Returns manga data from API

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(
            self.manga_url.format(initial_data['slug']),
            headers={
                'Referer': self.list_url,
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update({
            'authors': [],
            'scanlators': [],  # not available
            'genres': [],
            'status': None,
            'cover': None,
            'synopsis': None,
            'chapters': [],
            'server_id': self.id,
        })

        data['name'] = soup.select_one('.manga-name').text.strip()
        data['cover'] = soup.select_one('.manga-poster img').get('data-src')

        # Details
        for element in soup.select('.genres > a'):
            data['genres'].append(element.text.strip())

        for element in soup.select('.anisc-info .item'):
            label = element.span.text.strip()

            if label.startswith('タイプ'):
                # Type
                data['genres'].append(element.select_one('.name').text.strip())

            elif label.startswith('地位'):
                # Status
                value = element.select_one('.name').text.strip()
                if value == 'Publishing':
                    data['status'] = 'ongoing'
                elif value == 'Completed':
                    data['status'] = 'complete'
                elif value == 'Discontinued':
                    data['status'] = 'suspended'
                elif value == 'On Hiatus':
                    data['status'] = 'hiatus'

            elif label.startswith('著者'):
                # Authors
                for a_element in element.select('a'):
                    data['authors'].append(a_element.text.strip())

        if synopsis_element := soup.select_one('.description'):
            data['synopsis'] = synopsis_element.text.strip()

        # Chapters
        if ul_element := soup.select_one(f'#{self.languages_codes[self.lang]}-chaps'):
            for element in reversed(ul_element.select('li')):
                a_element = element.a
                sid = element.get('data-id')
                slug = a_element.get('href').split('/')[self.slug_position]
                data['chapters'].append({
                    'slug': f'{sid}:{slug}',
                    'title': a_element.get('title').strip(),
                    'num': element.get('data-number'),
                })
        else:
            # Manga exists but has no chapters in self.lang (not filtered in search)
            raise ServerException(_('Not available in {0} language').format(self.lang.upper()))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        chapter_id, chapter_slug = chapter_slug.split(':')

        # Get chapter images (ajax)
        r = self.session_get(
            self.api_chapter_images_url.format(chapter_id),
            headers={
                'Referer': urllib.parse.quote_plus(self.chapter_url.format(
                    manga_slug, self.languages_codes[self.lang], chapter_slug
                )),
                'X-Requested-With': 'XMLHttpRequest',
            }
        )
        if r.status_code != 200:
            return None

        json_data = r.json()
        if not json_data['status']:
            return None

        soup = BeautifulSoup(json_data['html'], 'lxml')

        data = {
            'pages': [],
        }
        for element in soup.select('.iv-card'):
            data['pages'].append({
                'slug': None,
                'scrambled': 'shuffled' in element.get('class'),
                'image': element.img.get('data-src'),
            })

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            page['image'],
            headers={
                'Referer': self.base_url + '/',
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        if self.scrambled_images and page['scrambled']:
            # js/read.min.js: key is 2nd argument of unShuffle function
            image = unscramble_image_rc4(r.content, 'stay', 200)
            with BytesIO() as io_buffer:
                image.save(io_buffer, 'png')
                buffer = io_buffer.getvalue()
        else:
            buffer = r.content

        return {
            'buffer': buffer,
            'mime_type': mime_type,
            'name': page['image'].split('?')[0].split('/')[-1],
        }

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_manga_list(self, type=None, status=None, orderby='default'):
        params = {
            'type': type,
            'status': status,
            'language': self.languages_codes[self.lang],
            'sort': orderby,
        }

        r = self.session_get(
            self.list_url,
            params=params,
            headers={
                'Referer': self.list_url,
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for item in soup.select('.item-spc'):
            cover = None
            if cover_element := item.select_one('.manga-poster img'):
                cover = cover_element.get('data-src')
                if not cover:
                    cover = cover_element.get('src')

            results.append({
                'slug': item.select_one('.manga-name > a').get('href').split('/')[self.slug_position],
                'name': item.select_one('.manga-name').text.strip(),
                'cover': cover,
            })

        return results

    def get_latest_updates(self, type=None, status=None):
        return self.get_manga_list(type=type, status=status, orderby='latest-updated')

    def get_most_populars(self, type=None, status=None):
        return self.get_manga_list(type=type, status=status, orderby='most-viewed')

    def search(self, term, type=None, status=None):
        # Search does not take language into account
        r = self.session_get(
            self.search_url,
            params={
                'q': term,
            },
            headers={
                'Referer': self.base_url + '/',
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for item in soup.select('.item-spc'):
            langs = item.select_one('.tick-lang').text.strip().split('/')
            if self.languages_codes[self.lang].upper() not in langs:
                continue

            cover = None
            if cover_element := item.select_one('.manga-poster img'):
                cover = cover_element.get('data-src')
                if not cover:
                    cover = cover_element.get('src')

            results.append({
                'slug': item.select_one('.manga-name > a').get('href').split('/')[self.slug_position],
                'name': item.select_one('.manga-name').text.strip(),
                'cover': cover,
            })

        return results
