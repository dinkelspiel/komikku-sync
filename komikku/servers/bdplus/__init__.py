# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import base64
from gettext import gettext as _
import json
import logging
import time
from urllib.parse import quote
from urllib.parse import unquote

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.utils import get_buffer_mime_type

logger = logging.getLogger(__name__)


def b36encode(number, alphabet='0123456789abcdefghijklmnopqrstuvwxyz'):
    base36 = ''
    sign = ''

    if number < 0:
        sign = '-'
        number = -number

    if 0 <= number < len(alphabet):
        return sign + alphabet[number]

    while number != 0:
        number, i = divmod(number, len(alphabet))
        base36 = alphabet[i] + base36

    return sign + base36


class Bdplus(Server):
    id = 'bdplus'
    name = 'BDplus'
    lang = 'fr'

    base_url = 'https://bdplus.cc'
    logo_url = base_url + '/favicon.ico'
    search_url = base_url + '/catalogue.html'
    manga_url = base_url + '/serie_static/{0}.html'
    chapter_url = base_url + '/lecture.html?b={0}'
    chapter_pages_url = base_url + '/_converted/{0}/{1}/pages.json'
    image_url = base_url + '/_converted/{0}/{1}/{2}'

    filters = [
        {
            'key': 'genre',
            'type': 'select',
            'name': _('Genre'),
            'description': _('Filter by Genre'),
            'value_type': 'single',
            'default': 'Tous',
            'options': [
                {'key': 'Tous', 'name': 'Tous'},
                {'key': 'Science-Fiction', 'name': 'Science-Fiction'},
                {'key': 'Fantasy', 'name': 'Fantasy'},
                {'key': 'Aventure', 'name': 'Aventure'},
                {'key': 'Humour', 'name': 'Humour'},
                {'key': 'Historique', 'name': 'Historique'},
                {'key': 'Thriller / Policier', 'name': 'Thriller / Policier'},
                {'key': 'Horreur / Mystique', 'name': 'Horreur / Mystique'},
                {'key': 'Western', 'name': 'Western'},
                {'key': 'Sport', 'name': 'Sport'},
                {'key': 'Autre', 'name': 'Autre'},
            ],
        },
        {
            'key': 'epoque',
            'type': 'select',
            'name': 'Époque',
            'description': 'Filtrer par époque',
            'value_type': 'single',
            'default': 'Toutes',
            'options': [
                {'key': 'Toutes', 'name': 'Toutes'},
                {'key': 'Classiques', 'name': 'Classiques (<1980)'},
                {'key': '1980s', 'name': 'Années 80-90'},
                {'key': '2000s', 'name': 'Années 2000'},
                {'key': '2010s', 'name': 'Années 2010'},
                {'key': 'Recentes', 'name': 'Récentes (2020+)'},
            ],
        },
    ]

    manga_list = []

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

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
            'scanlators': [],  # Not available
            'genres': [],
            'status': None,  # Not available
            'synopsis': None,
            'chapters': [],
            'server_id': self.id,
            'cover': None,
        })

        data['name'] = soup.select_one('h1.serie-main-title').text.strip()
        if element := soup.select_one('img.serie-cover'):
            data['cover'] = f'{self.base_url}{element.get("src")}'

        # Details
        if element := soup.select_one('.meta-authors'):
            for author in element.text.split(','):
                author = author.strip()
                if author not in data['authors']:
                    data['authors'].append(author)

        for element in soup.select('.genre-pill'):
            data['genres'].append(element.text.strip())

        if element := soup.select_one('.synopsis-text'):
            synopsis = [element.text.strip(), ]
            if element := soup.select_one('#synopsis-more'):
                soup_synopsis = BeautifulSoup(element.get('data-content'), 'lxml')
                for element in soup_synopsis.select('p'):
                    synopsis.append(element.text.strip())
            data['synopsis'] = '\n\n'.join(synopsis)

        # Chapters
        for element in soup.select('#tomes-grid a.card'):
            data['chapters'].append({
                'slug': element.get('data-path').split('/')[-1],
                'title': element.select_one('.card-title').text.strip(),
            })

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data
        """

        # Compute encoded path
        # See `encodePathObfuscated` func of `/assets/js/serie_static_secure.min.xxxxxxxxxx.js` script
        path = f'_converted/{manga_slug}/{chapter_slug}'
        t = 3
        a = b36encode(int(time.time() * 1000)).lower()
        n = base64.b64encode(unquote(quote(f'{path}/{a}')).encode()).decode()
        t %= len(n)
        encoded_path = n[-t:] + n[:-t]

        r = self.session_get(
            self.chapter_pages_url.format(manga_slug, chapter_slug),
            headers={
                'Referer': self.chapter_url.format(encoded_path),
            }
        )
        if r.status_code != 200:
            return None

        data = {
            'pages': [],
        }
        for page in r.json()['pages']:
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
            self.image_url.format(manga_slug, chapter_slug, page['image']),
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
            'name': page['image'].split('/')[-1],
        }

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_latest_updates(self, genre=None, epoque=None):
        """
        Returns latest updates
        """
        r = self.session_get(self.base_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('#nouveautes-carousel a.nouveaute-card'):
            results.append({
                'slug': element.get('href').split('/')[-1].replace('.html', ''),
                'name': element.select_one('.card-title').text.strip(),
                'cover': self.base_url + element.select_one('img').get('src'),
            })

        return results

    def search(self, term=None, genre=None, epoque=None):
        if not self.manga_list:
            # Retrieve manga list if not already done
            r = self.session_get(self.search_url)
            if r.status_code != 200:
                return None

            soup = BeautifulSoup(r.text, 'lxml')

            if script_element := soup.select_one('script#catalogue-data'):
                if data := script_element.string:
                    self.manga_list = json.loads(data)

        if not self.manga_list:
            return None

        results = []
        for serie in self.manga_list:
            if term and term.lower() not in serie[1].lower():
                continue

            if genre and genre != 'Tous' and genre != serie[3]:
                continue

            if epoque and epoque != 'Toutes':
                if epoque == 'Classiques' and serie[6] >= 1980:
                    continue
                if epoque == '1980s' and (serie[6] < 1980 or serie[6] > 1999):
                    continue
                if epoque == '2000s' and (serie[6] < 2000 or serie[6] > 2009):
                    continue
                if epoque == '2010s' and (serie[6] < 2010 or serie[6] > 2019):
                    continue
                if epoque == 'Recentes' and serie[6] < 2020:
                    continue

            results.append({
                'slug': serie[0],
                'name': serie[1],
                'cover': self.base_url + serie[2],
            })

        return results
