# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import logging

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number

logger = logging.getLogger(__name__)


class Invinciblecomicsvf(Server):
    id = 'invinciblecomicsvf'
    name = 'Invincible ComicsVF'
    lang = 'fr'
    status = 'disabled'

    base_url = 'https://invinciblecomicsvf.fr'
    logo_url = base_url + '/wp-content/uploads/2025/05/cropped-5xhpykwda6w61-32x32.png'
    search_url = base_url
    latest_updates_url = base_url
    most_populars_url = base_url
    manga_url = base_url + '/{0}/'
    chapter_url = base_url + '/lecture/?tome={0}&comic_title={1}'

    filters = [
        {
            'key': 'type_',
            'type': 'select',
            'name': _('Type'),
            'description': _('Filter by Type'),
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': _('All')},
                {'key': 'comic', 'name': 'Comic'},
                {'key': 'bande_dessine', 'name': 'Bande dessinée'},
            ],
        },
    ]

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Returns comic data by scraping comic HTML page content

        Initial data should contain at least comic's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Comic slug is missing in initial data'

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
            scanlators=[],
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
        ))

        data['name'] = soup.select_one('.comic-infos h1').text.strip()
        data['cover'] = soup.select_one('.comic-thumbnail img').get('data-src')

        if element := soup.select_one('p:-soup-contains("Auteur")'):
            data['authors'].append(element.text.replace('Auteur :', '').strip())

        if element := soup.select_one('p:-soup-contains("Status")'):
            status = element.text.replace('Status :', '').strip()
            if status == 'Términé':
                data['status'] = 'complete'

        if element := soup.select_one('p:-soup-contains("Genre")'):
            data['genres'] = [genre.strip() for genre in element.text.replace('Genre :', '').strip().split(',')]

        if element := soup.select_one('p:-soup-contains("Résumé")'):
            data['synopsis'] = element.text.replace('Résumé :', '').strip()

        for a_element in soup.select('.tome-link'):
            num_volume = a_element.get('data-tome')

            data['chapters'].append(dict(
                slug=num_volume,
                title=a_element.text.strip(),
                num_volume=num_volume if is_number(num_volume) else None,
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns comic chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(chapter_slug, manga_name))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        base_url = None
        nb_pages = None
        for script_element in soup.find_all('script'):
            script = script_element.string
            if not script or 'const imageBase' not in script:
                continue

            for line in script.split('\n'):
                line = line.strip()
                if line.startswith('const imageBase'):
                    base_url = line.split()[-1][1:-2]
                if line.startswith('const totalPages'):
                    nb_pages = int(line.split()[-1][:-1])

                if base_url and nb_pages:
                    break

        if base_url is None or nb_pages is None:
            return None

        data = dict(
            pages=[],
        )
        for index in range(1, nb_pages + 1):
            data['pages'].append(dict(
                slug=None,
                image=f'{base_url}{index:03d}.jpg',  # noqa E231
                index=index,
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(page['image'], headers={
            'Referer': f'{self.base_url}/',
        })
        if r.status_code == 404:
            # Try image in PNG format
            r = self.session_get(page['image'].replace('.jpg', '.png'), headers={
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
        Returns comic absolute URL
        """
        return self.manga_url.format(slug)

    def get_latest_updates(self, type_=None):
        r = self.session_get(self.latest_updates_url)
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.comic-card.horizontal'):
            a_element = element.a

            results.append(dict(
                slug='/'.join(a_element.get('href').split('/')[-3:-1]),
                name=a_element.h3.text.strip(),
                cover=a_element.img.get('data-src'),
            ))

        return results

    def get_most_populars(self, type_=None):
        r = self.session_get(self.most_populars_url)
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        selector = []
        if not type_ or type_ == 'comic':
            selector.append('.top-comics .comic-card')
        if not type_ or type_ == 'bande_dessine':
            selector.append('.top-bd .comic-card')

        results = []
        for element in soup.select(', '.join(selector)):
            a_element = element.a

            results.append(dict(
                slug='/'.join(a_element.get('href').split('/')[-3:-1]),
                name=a_element.h3.text.strip(),
                cover=a_element.img.get('data-src'),
            ))

        return results

    def search(self, term=None, type_=None):
        params = {
            's': term,
            'ct_post_type': type_ or 'comic:bande_dessine',
        }

        r = self.session_get(self.search_url, params=params, headers={
            'Referer': f'{self.base_url}',
        })
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.entries article'):
            a_element = element.select_one('a.ct-media-container')

            results.append(dict(
                slug='/'.join(a_element.get('href').split('/')[-3:-1]),
                name=element.select_one('h2').text.strip(),
                cover=a_element.img.get('data-src'),
            ))

        return results
