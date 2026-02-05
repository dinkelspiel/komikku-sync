# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import json
import logging
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type

logger = logging.getLogger('komikku.servers.legacyscans')


class Legacyscans(Server):
    id = 'legacyscans'
    name = 'LegacyScans'
    lang = 'fr'
    status = 'disabled'

    base_url = 'https://legacy-scans.com'
    logo_url = base_url + '/imgs/icon.webp'
    api_base_url = 'https://api.legacy-scans.com'
    api_search_url = api_base_url + '/misc/home/search'
    api_latest_updates_url = api_base_url + '/misc/comic/home/updates'
    api_most_popular_url = api_base_url + '/misc/views/monthly'
    manga_url = base_url + '/comics/{0}'
    chapter_url = base_url + '/comics/{0}/{1}'

    api_headers = {
        'Host': urlparse(api_base_url).netloc,
        'Accept': 'image/avif,image/webp,*/*',
        'Referer': f'{base_url}/'
    }

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
        assert 'slug' in initial_data, 'slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],  # not available
            genres=[],
            status=None,  # not available
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        data['name'] = soup.select_one('.serieTitle h1').text.strip()
        data['cover'] = soup.select_one('.serieImg img').get('src')

        #  Details
        for element in soup.select('.serieGenre > span'):
            data['genres'].append(element.text.strip())

        if author1 := soup.select_one('div.serieAdd > p:nth-child(2) > strong'):
            if author1.text.strip() != 'Inconnu':
                data['authors'].append(author1.text.strip())
        if author2 := soup.select_one('div.serieAdd > p:nth-child(3) > strong'):
            if author2.text.strip() != 'Inconnu':
                data['authors'].append(author2.text.strip())

        # Synopsis
        if synopsis_element := soup.select_one('.serieDescription > div'):
            data['synopsis'] = synopsis_element.text.strip()

        # Chapters
        for a_element in reversed(soup.select('.chapterList a')):
            data['chapters'].append(dict(
                slug='/'.join(a_element.get('href').split('/')[-2:]),
                title=a_element.select_one('div span:first-child').text.strip(),
                date=convert_date_string(a_element.select_one('div span:last-child').text.strip(), format='%d/%m/%Y'),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(
            self.chapter_url.format(manga_slug, chapter_slug),
            headers={
                'Referer': self.manga_url.format(manga_slug),
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )
        for script_element in soup.find_all('script'):
            script = script_element.string
            if not script or 'Reactive' not in script:
                continue

            for datum in json.loads(script):
                if not isinstance(datum, str) or not datum.startswith(f'public/uploads/{manga_slug}'):
                    continue

                data['pages'].append(dict(
                    slug=None,
                    image=f'{self.base_url}/{datum}',
                ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            page['image'],
            headers=self.api_headers,
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=page['image'].split('/')[-1],
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_latest_updates(self):
        r = self.session_get(
            self.api_latest_updates_url,
            params=dict(
                start=1,
                end=24,
            ),
            headers=self.api_headers
        )
        if r.status_code != 200:
            return None

        results = []
        for item in r.json()['results']:
            results.append(dict(
                cover='{0}/{1}'.format(self.api_base_url, item['cover']),
                slug=item['slug'],
                name=item['title'],
                last_chapter=item['chapters'][0]['chapterNumber'],
            ))

        return results

    def get_most_populars(self):
        r = self.session_get(
            self.api_most_popular_url,
            headers=self.api_headers
        )
        if r.status_code != 200:
            return None

        results = []
        for item in r.json()['results']:
            results.append(dict(
                cover='{0}/{1}'.format(self.api_base_url, item['cover']),
                slug=item['slug'],
                name=item['title'],
            ))

        return results

    def search(self, term=None, orderby=None):
        r = self.session_get(
            self.api_search_url,
            params=dict(
                title=term,
            ),
            headers=self.api_headers
        )
        if r.status_code != 200:
            return None

        results = []
        for item in r.json()['results']:
            results.append(dict(
                slug=item['slug'],
                name=item['title'],
            ))

        return results
