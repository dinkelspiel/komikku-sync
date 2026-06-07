# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import json
import logging
import re

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.utils import get_buffer_mime_type

logger = logging.getLogger(__name__)


class Lanortrad(Server):
    id = 'lanortrad'
    name = 'LanorTrad'
    lang = 'fr'

    base_url = 'https://lanortrad.com'
    logo_url = base_url + '/images/icons/icon-192x192.png'
    search_url = base_url + '/js/utile/mangaData.js'
    manga_url = base_url + '/manga/{0}'
    chapter_url = base_url + '/manga/{0}/{1}'
    image_url = base_url + '/manga/{0}/{1}'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers = {
                'User-Agent': USER_AGENT,
            }

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update({
            'authors': [],
            'scanlators': [self.name, ],
            'genres': [],
            'status': 'ongoing',
            'synopsis': None,
            'chapters': [],
            'server_id': self.id,
            'cover': None,
        })

        data['name'] = soup.find('h1').text.strip()
        if element := soup.select_one('.card > img'):
            path = element.get('src')
            data['cover'] = f'{self.base_url}/{path}'

        # Details
        for element in soup.select('div.grid div:-soup-contains("Auteur") p, div.grid div:-soup-contains("Artiste") p'):
            author = element.text.strip()
            if author not in data['authors']:
                data['authors'].append(author)

        if element := soup.select_one('div.grid div:-soup-contains("Statut") p'):
            status = element.text.strip()
            if status == 'En cours':
                data['status'] = 'ongoing'
            elif status == 'Terminé':
                data['status'] = 'complete'

        for element in soup.select('div.flex.flex-wrap > span.rounded-full'):
            data['genres'].append(element.text.strip())

        if element := soup.select_one('div.card:-soup-contains("Synopsis") p'):
            data['synopsis'] = element.text.strip()

        # Chapters
        if 'Oneshot' in data['genres']:
            # Oneshot (single chapter)
            data['chapters'].append({
                'slug': 'oneshot',
                'title': 'Chapitre unique',
                'date': None,
            })

        else:
            js_url = None
            for script_element in soup.select('script'):
                if path := script_element.get('src'):
                    if 'js/manga/' in path:
                        path = path.replace('../', '')
                        js_url = f'{self.base_url}/{path}'
                        break

            if js_url is None:
                logger.warning('Failed to get URL of JS file containing manga info')
                return data

            r = self.session_get(
                js_url,
                headers={
                    'Referer': self.manga_url.format(data['slug']),
                }
            )
            if r.status_code != 200:
                return None

            js_code = r.text
            chapters_nums = None
            if matches := re.search(r'\s*maxChapters: (\d*)', js_code):
                chapters_nums = list(range(1, int(matches.group(1)) + 1))

            if chapters_nums is None:
                logger.warning('Failed to retrieve the number of chapters')
                return data

            # Get bonus chapters numbers
            if matches := re.search(r'\s*number: (\d*.\d)', js_code):
                for num in matches.groups():
                    chapters_nums.append(float(num))

            for num in sorted(chapters_nums):
                data['chapters'].append({
                    'slug': f'chapitre {num}',
                    'title': f'Chapitre {num}',
                    'num': num,
                    'date': None,
                })

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        nb_digits = None
        nb_pages = None
        path = None
        for script_element in soup.select('script'):
            script = script_element.string
            if not script or 'generateImages' not in script:
                continue

            if matches := re.search(r'\s*padStart\((\d),', script):
                nb_digits = int(matches.group(1))
            if matches := re.search(r'\s*for \(let i = 1; i <= (\d*)\s*; i\+\+\)', script):
                nb_pages = int(matches.group(1))
            if matches := re.search(r'\s*imgElement\.src = `(.*)`', script):
                path = matches.group(1)

            break

        if nb_digits is None:
            logger.warning('Failed to retrieve the number of digits of image filenames')
            return None
        if nb_pages is None:
            logger.warning('Failed to retrieve the number of pages of the chapter')
            return None
        if path is None:
            logger.warning('Failed to retrieve the images path')
            return None

        data = {
            'pages': [],
        }
        for num in range(1, nb_pages + 1):
            data['pages'].append({
                'image': None,
                'url': path.replace('${num}', f'{num:0{nb_digits}}'),  # noqa
            })

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            self.image_url.format(manga_slug, page['url']),
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
            'name': page['url'].split('/')[-1],
        }

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_most_populars(self):
        return self.search()

    def search(self, term=None):
        """
        Return all manga by scraping a JS file
        """
        r = self.session_get(
            self.search_url,
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        lines = []
        for line in r.text.split('\n'):
            if not line or line.strip().startswith('//'):
                # Empty or comment
                continue

            if line.startswith('window.MANGA_DATA'):
                lines.append('[')
            elif line.strip() == '];':
                lines.append(']')
            elif matches := re.search(r'\s*([a-zA-Z]*): (.*)', line):
                lines.append(f'"{matches.group(1)}": {matches.group(2)}')
            else:
                lines.append(line)

        data = json.loads('\n'.join(lines))

        results = []
        for item in data:
            if term and term.lower() not in item['title'].lower():
                continue

            cover = item['coverImage']
            if not cover.startswith('http'):
                # Oneshots have no cover
                cover = f'{self.base_url}/{item["image"]}'

            results.append({
                'slug': item['id'].lower(),
                'name': item['title'],
                'cover': cover,
            })

        return results
