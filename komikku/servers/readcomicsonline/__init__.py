# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _

from bs4 import BeautifulSoup

from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.webview import CompleteChallenge


class Readcomicsonline(Server):
    id = 'readcomicsonline'
    name = 'Read Comics Online'
    lang = 'en'

    has_cf = True

    base_url = 'https://readcomicsonline.ru'
    search_url = base_url + '/advanced-search'
    manga_list_url = base_url + '/comic-list'
    manga_url = base_url + '/comic/{0}'
    chapter_url = base_url + '/comic/{0}/{1}'
    image_url = 'https://cdn.readcomicsonline.ru/uploads/manga/{0}/chapters/{1}/{2}'

    filters = [
        {
            'key': 'status',
            'type': 'select',
            'name': _('Status'),
            'description': _('Filter by Status'),
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': _('All')},
                {'key': '1', 'name': _('Ongoing')},
                {'key': '2', 'name': _('Complete')},
            ],
        },
        {
            'key': 'type',
            'type': 'select',
            'name': _('Type'),
            'description': _('Filter by Type'),
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': _('All')},
                {'key': '1', 'name': 'DC Comics'},
                {'key': '2', 'name': 'Marvel Comics'},
                {'key': '3', 'name': _('Other')},
            ],
        },
    ]

    def __init__(self):
        self.session = None

    @CompleteChallenge()
    def get_manga_data(self, initial_data):
        """
        Returns comic data by scraping comic HTML page content

        Initial data should contain at least comic's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Comic slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update({
            'authors': [],
            'scanlators': [],  # not available
            'genres': [],
            'status': None,
            'synopsis': None,
            'chapters': [],
            'server_id': self.id,
            'cover': None,
        })

        data['name'] = soup.select_one('main h1').text.strip()
        data['cover'] = soup.select_one('main img.object-cover').get('src')

        # Details
        if element := soup.select_one('main span.rounded-full'):
            status = element.text.strip()
            if status == 'Complete':
                data['status'] = 'complete'
            elif status == 'Ongoing':
                data['status'] = 'ongoing'

        for element in soup.select('div:-soup-contains("Genres") > a'):
            data['genres'].append(element.text.strip())

        for element in soup.select('div:-soup-contains("Author") > a'):
            data['authors'].append(element.text.strip())

        if element := soup.select_one('main p.leading-relaxed'):
            data['synopsis'] = element.text.strip()

        # Chapters
        for element in reversed(soup.select('section a')):
            slug = element.get('href').split('/')[-1]
            title = element.select_one('span:first-child > span').text.strip()
            date = element.select_one('span:last-child').text.strip()

            data['chapters'].append({
                'slug': slug,
                'title': title,
                'date': convert_date_string(date, languages=[self.lang], format='%d %b %Y'),
            })

        return data

    @CompleteChallenge()
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns comic chapter data by scraping chapter HTML page content

        Currently, only pages (list of images filenames) are expected.
        """
        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = {
            'pages': [],
        }
        for element in soup.select('#reader-all img'):
            slug = element.get('src').split('/')[-1]

            data['pages'].append({
                'slug': slug,
                'image': None,
            })

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            self.image_url.format(manga_slug, chapter_slug, page['slug']),
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
            'name': page['slug'],
        }

    def get_manga_url(self, slug, url):
        """
        Returns comic absolute URL
        """
        return self.manga_url.format(slug)

    def get_manga_list(self, term=None, orderby=None):
        r = self.session_get(
            self.manga_list_url,
            headers={
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Referer': self.manga_list_url,
            },
            params={
                'sort': orderby,
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.grid .group'):
            a_element = element.select_one('a.line-clamp-2')

            results.append({
                'name': a_element.text.strip(),
                'slug': a_element.get('href').split('/')[-1],
                'cover': element.select_one('img.object-cover').get('src'),
                'last_chapter': element.select_one('a.text-xs').text.strip(),
            })

        return results

    @CompleteChallenge()
    def get_latest_updates(self, status=None, type=None):
        """
        Returns list of latest updated comics
        """
        return self.get_manga_list(orderby='latest')

    @CompleteChallenge()
    def get_most_populars(self, status=None, type=None):
        """
        Returns list of most viewed comics
        """
        return self.get_manga_list(orderby='views')

    @CompleteChallenge()
    def search(self, term, status=None, type=None):
        r = self.session_get(self.search_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        if input := soup.select_one('input[name="_token"]'):
            token = input.get('value')
        else:
            return None

        r = self.session_post(
            self.search_url,
            params={
                '_token': token,
                'name':	term,
                'status_id': status if status is not None else '',
                'type_id': type if type is not None else '',
                'category':	'',
            }
        )

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.grid a.group'):
            slug = element.get('href').split('/')[-1]

            results.append({
                'name': element.p.text.strip(),
                'slug': slug,
                'cover': element.select_one('.rc-cover img').get('src'),
            })

        return results
