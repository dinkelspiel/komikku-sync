# SPDX-FileCopyrightText: 2020-2024 Liliana Prikler
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Liliana Prikler <liliana.prikler@gmail.com>

from bs4 import BeautifulSoup
import json

from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.webview import CompleteChallenge

IMAGES_EXTS = {'g': 'gif', 'j': 'jpg', 'p': 'png', 'w': 'webp'}

# Mirrors
# https://nhentai.to
# https://nhentai.xxx


class Nhentai(Server):
    id = 'nhentai'
    name = 'NHentai'
    lang = 'en'
    lang_code = 'english'
    is_nsfw_only = True

    has_cf = True

    base_url = 'https://nhentai.net'
    search_url = base_url + '/search'
    manga_url = base_url + '/g/{0}'
    page_image_url = 'https://i.nhentai.net/galleries/{0}/{1}'

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

        data = initial_data.copy()
        data.update({
            'authors': [],
            'scanlators': [],  # Not available
            'genres': [],
            'status': None,    # Not available
            'synopsis': None,  # Not available
            'chapters': [],
            'server_id': self.id,
        })

        soup = BeautifulSoup(r.text, 'lxml')

        data['name'] = soup.find('meta', property='og:title')['content']
        data['cover'] = 'https:' + soup.find('meta', property='og:image')['content']

        # Genres & Artists + chapter date
        chapter_date = None
        info = soup.select_one('#info')
        for tag_container in info.select('#tags .tag-container'):
            category = tag_container.text.split(':')[0].strip()

            if category == 'Uploaded':
                if time_element := tag_container.select_one('time'):
                    chapter_date = time_element.get('datetime').split('T')[0]

            for tag in tag_container.select('.tag'):
                clean_tag = tag.select_one('span.name').text.strip()
                if category in ['Artists', 'Groups', ]:
                    data['authors'].append(clean_tag)
                if category in ['Tags', ]:
                    data['genres'].append(clean_tag)

        # Single chapter
        data['chapters'].append({
            'slug': data['cover'].rstrip('/').split('/')[-2],
            'title': data['name'],
            'date': convert_date_string(chapter_date, '%Y-%m-%d') if chapter_date else None,
        })

        return data

    @CompleteChallenge()
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.manga_url.format(manga_slug))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        pages = []
        for script_element in soup.find_all('script'):
            script = script_element.string
            if not script or not script.strip().startswith('window._gallery'):
                continue

            info = json.loads(script.strip().split('\n')[0][30:-3].replace('\\u0022', '"').replace('\\u005C', '\\'))
            if not info.get('images') or not info['images'].get('pages'):
                break

            for index, page in enumerate(info['images']['pages']):
                num = index + 1
                extension = IMAGES_EXTS[page['t']]
                page = {
                    'image': None,
                    'slug': f'{num}.{extension}',
                }
                pages.append(page)

        return {'pages': pages}

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        assert chapter_slug is not None
        r = self.session_get(self.page_image_url.format(chapter_slug, page['slug']))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return {
            'buffer': r.content,
            'mime_type': mime_type,
            'name': page['slug'],
        }

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def _search_common(self, params):
        r = self.session_get(self.search_url, params=params)

        if r.status_code == 200:
            try:
                results = []
                soup = BeautifulSoup(r.text, 'lxml')
                elements = soup.find_all('div', class_='gallery')

                for element in elements:
                    a_element = element.find('a', class_='cover')
                    caption_element = element.find('div', class_='caption')
                    results.append({
                        'slug': a_element.get('href').rstrip('/').split('/')[-1],
                        'name': caption_element.text.strip(),
                        'cover': 'https:' + a_element.img.get('data-src'),
                    })
            except Exception:
                return None
            else:
                return results

        return None

    @CompleteChallenge()
    def get_most_populars(self):
        """
        Returns most popular mangas (bayesian rating)
        """
        return self._search_common({'q': 'language:' + self.lang_code, 'sort': 'popular'})

    @CompleteChallenge()
    def search(self, term):
        term = term + ' language:' + self.lang_code
        return self._search_common({'q': term})


class Nhentai_chinese(Nhentai):
    id = 'nhentai_chinese'
    lang = 'zh_Hans'
    lang_code = 'chinese'


class Nhentai_japanese(Nhentai):
    id = 'nhentai_japanese'
    lang = 'ja'
    lang_code = 'japanese'
