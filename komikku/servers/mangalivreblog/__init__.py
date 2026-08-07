# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import logging
import re

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number

logger = logging.getLogger(__name__)


class Mangalivreblog(Server):
    id = 'mangalivreblog'
    name = 'Manga Livre'
    lang = 'pt_BR'

    base_url = 'https://mangalivre.blog'
    most_populars_url = base_url + '/wp-admin/admin-ajax.php'
    logo_url = base_url + '/wp-content/uploads/2025/05/cropped-logopp-32x32.png'
    search_url = base_url + '/pesquisa/'
    manga_url = base_url + '/manga/{0}/'
    chapter_url = base_url + '/capitulo/{0}/'

    filters = [
        {
            'key': 'status',
            'type': 'select',
            'name': _('Status'),
            'description': _('Filter by Status'),
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': _('Any')},
                {'key': 'cancelado', 'name': _('Cancelado')},
                {'key': 'completo', 'name': _('Completo')},
                {'key': 'en-andamento', 'name': _('Em Andamento')},
                {'key': 'em-lancamento', 'name': _('Em Lançamento')},
                {'key': 'hiato', 'name': _('Hiato')},
            ],
        },
    ]
    long_strip_genres = ['Long Strip', 'Web Comic']

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'user-agent': USER_AGENT})

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
        data.update(dict(
            authors=[],
            scanlators=[],  # not available
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        data['name'] = soup.select_one('h1.manga-title').text.strip()
        data['cover'] = soup.select_one('.manga-cover img').get('src')

        # Details
        if element := soup.select_one('.manga-meta-item:-soup-contains("Status") .meta-value'):
            status = element.text.strip()
            if status in ('Em Andamento', 'Em Lançamento'):
                data['status'] = 'ongoing'
            elif status == 'Completo':
                data['status'] = 'complete'
            elif status == 'Cancelado':
                data['status'] = 'suspended'
            elif status in ('Hiato', 'Pausado'):
                data['status'] = 'hiatus'

        authors_selector = '.manga-meta-item:-soup-contains("Artista") .meta-value, .manga-meta-item:-soup-contains("Autor") .meta-value'
        for element in soup.select(authors_selector):
            authors = element.text.split(',')
            for author in authors:
                author = author.strip()
                if author not in data['authors']:
                    data['authors'].append(author)

        for element in soup.select('.manga-tag'):
            data['genres'].append(element.text.strip())

        # Synopsis
        data['synopsis'] = soup.select_one('.synopsis-content').text.strip()

        # Chapters
        for element in reversed(soup.select('.chapters-list .chapter-item')):
            a_element = element.select_one('.chapter-link')
            title_element = element.select_one('.chapter-number')
            date_element = element.select_one('.chapter-date')
            title = title_element.text.strip()
            num = title.split(' ')[-1]

            data['chapters'].append(dict(
                slug=a_element.get('href').split('/')[-2],
                title=title,
                num=num if is_number(num) else None,
                date=convert_date_string(date_element.text.strip(), languages=[self.lang]) if date_element else None,
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(chapter_slug))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = {
            'pages': [],
        }
        for element in soup.select('.chapter-image-container img'):
            data['pages'].append({
                'image': element.get('src'),
                'slug': None,
            })

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            page['image'],
            headers={
                'Referer': self.chapter_url.format(chapter_slug),
            }
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

    def get_latest_updates(self, status=None):
        """
        Returns latest mangas
        """
        r = self.session_get(self.base_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('section.latest-section .manga-card-modern'):
            a_element = element.select_one('.manga-title-modern a')
            img_element = element.select_one('.manga-cover-modern img')
            last_chapter_element = element.select_one('.chapter-list-modern .chapter-item-modern:first-child .chapter-number-modern')

            results.append({
                'slug': a_element.get('href').split('/')[-2],
                'name': a_element.text.strip(),
                'cover': img_element.get('src'),
                'last_chapter': last_chapter_element.text.strip() if last_chapter_element else None,
            })

        return results

    def get_most_populars(self, status=None):
        """
        Returns most popular mangas
        """
        r = self.session_get(self.base_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        nonce = None
        for script_element in soup.select('script'):
            script = script_element.string
            if not script or 'slimeReadPopular' not in script:
                continue

            if matches := re.search(r'nonce":"([^"]+)', script):
                nonce = matches.group(1)
            break

        if not nonce:
            return None

        r = self.session_post(
            self.most_populars_url,
            data={
                'action': 'get_popular_manga',
                'period': 'month',
                'nonce': nonce,
            },
            headers={
                'Referer': f'{self.base_url}/manga/',
                'X-Requested-With': 'XMLHttpRequest',
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()
        if 'success' not in resp_data or not resp_data['success']:
            return None

        soup = BeautifulSoup(resp_data['data']['html'], 'lxml')

        results = []
        for element in soup.select('.popular-manga-item'):
            a_element = element.select_one('.popular-manga-title a')
            img_element = element.select_one('.popular-manga-thumbnail img')

            results.append({
                'slug': a_element.get('href').split('/')[-2],
                'name': a_element.text.strip(),
                'cover': img_element.get('src'),
            })

        return results

    def search(self, term, status=None):
        params = {
            's': term,
        }
        if status:
            params['status'] = status

        r = self.session_get(self.base_url, params=params)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.manga-grid.search-results-grid .manga-card'):
            name_element = element.select_one('h3.manga-card-title')
            a_element = element.select_one('a.manga-card-link')
            img_element = element.img

            results.append({
                'slug': a_element.get('href').split('/')[-2],
                'name': name_element.text.strip(),
                'cover': img_element.get('src'),
            })

        return results
