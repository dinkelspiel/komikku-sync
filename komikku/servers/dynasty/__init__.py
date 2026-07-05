# SPDX-FileCopyrightText: 2020-2026 Liliana Prikler
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Liliana Prikler <liliana.prikler@gmail.com>
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import json
import logging
import re

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import skip_past

logger = logging.getLogger(__name__)


class Dynasty(Server):
    id = 'dynasty'
    name = 'Dynasty Reader'
    lang = 'en'
    is_nsfw = True

    base_url = 'https://dynasty-scans.com'
    logo_url = base_url + '/assets/favicon-96599a954b862bfaaa71372cc403a6ab.png'
    search_url = base_url + '/search'
    manga_url = base_url + '/{0}'
    chapter_url = base_url + '/chapters/{0}'
    tags_url = base_url + '/tags/suggest/'

    filters = [
        {
            'key': 'classes',
            'type': 'select',
            'name': _('Categories'),
            'description': _('Filter by Types'),
            'value_type': 'multiple',
            'options': [
                {'key': 'Anthology', 'name': _('Anthologies'), 'default': True},
                {'key': 'Doujin', 'name': _('Doujins'), 'default': True},
                {'key': 'Issue', 'name': _('Issues'), 'default': True},
                {'key': 'Series', 'name': _('Series'), 'default': True},
                {'key': 'Chapter', 'name': _('Chapters'), 'default': False},
            ],
        },
        {
            'key': 'with_tags',
            'type': 'entry',
            'name': _('With Tags'),
            'description': _('Comma separated list of tags to search for'),
            'default': '',
        },
        {
            'key': 'without_tags',
            'type': 'entry',
            'name': _('Without Tags'),
            'description': _('Comma separated list of tags to exclude from search'),
            'default': '',
        },
    ]
    long_strip_genres = ['Long strip', ]

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'user-agent': USER_AGENT})

    @classmethod
    def get_manga_initial_data_from_url(cls, url):
        if idx := skip_past(url, 'dynasty-scans.com/'):
            return {'slug': url[idx:]}

        return None

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
            'scanlators': [],
            'genres': [],
            'status': None,
            'synopsis': None,
            'chapters': [],
            'server_id': self.id,
            'cover': None,
        })

        class_ = initial_data['slug'].split('/')[0]

        return {
            'anthologies': self._fill_data_multi,
            'chapters': self._fill_data_single,
            'doujins': self._fill_data_multi,
            'issues': self._fill_data_multi,
            'series': self._fill_data_multi,
        }[class_](class_, data, soup)

    def _fill_data_single(self, class_, data, soup):
        # Fill metadata
        name_element = soup.select_one('#chapter-title')
        data['name'] = name_element.b.text.strip()
        data['authors'] = [elt.text.strip() for elt in name_element.select('a')]

        details = soup.select_one('#chapter-details')
        data['scanlators'] = [elt.text.strip() for elt in details.select('span.scanlators a')]

        data['genres'] = [elt.text.strip() for elt in details.select('span.tags a')]

        date_text = details.select_one('span.released').text.strip()

        data['chapters'].append({
            'slug': data['slug'].split('/')[-1],
            'title': data['name'],
            'date': convert_date_string(date_text),
        })

        # Use first page as cover
        for script_element in soup.select('script'):
            script = script_element.string
            if script is None:
                continue

            for line in script.split('\n'):
                line = line.strip()
                if line.startswith('var pages'):
                    pages = line.replace('var pages = ', '')[:-1]
                    break
            if pages is not None:
                pages = json.loads(pages)
                break

        if pages is not None:
            data['cover'] = self.base_url + pages[0]['image']

        return data

    def _fill_data_multi(self, class_, data, soup):
        status = None

        if class_ in ('anthologies', 'series'):
            name_element = soup.select_one('.tag-title > b')
            authors_elements = soup.select('.tag-title > a')
            cover_element = soup.select_one('.cover-chapters .cover img.thumbnail')
            full_title = soup.select_one('.tag-title').text
            if len(full_title.split('—')) == 2:
                status = full_title.split('—')[1].strip()
            data['name'] = name_element.text.split('›')[-1].strip()

        elif class_ == 'doujins':
            name_element = soup.select_one('h2')
            authors_elements = soup.select('.tag-tags a')
            cover_element = soup.select_one('.tag-images a.thumbnail img')
            data['name'] = name_element.text.split('›')[-1].strip()

        elif class_ == 'issues':
            name_element = soup.select_one('.tag-title b')
            authors_elements = None
            cover_element = soup.select_one('.cover-chapters .cover img.thumbnail')
            full_title = soup.select_one('.tag-title').text
            if len(full_title.split('—')) == 2:
                status = full_title.split('—')[1].strip()
            data['name'] = name_element.text.strip()

        if cover_element:
            data['cover'] = self.base_url + cover_element.get('src')

        if authors_elements:
            data['authors'] = [element.text.strip() for element in authors_elements]

        if status == 'Ongoing':
            data['status'] = 'ongoing'
        elif status == 'Completed':
            data['status'] = 'complete'
        elif status == 'On Hiatus':
            data['status'] = 'hiatus'
        elif status in ('Abandoned', 'Cancelled', 'Dropped', 'Not Updated', 'Removed'):
            data['status'] = 'suspended'

        # Genres
        for element in soup.select('.tag-tags a.label'):
            value = element.text.strip()
            if value not in data['genres']:
                data['genres'].append(value)

        # Synopsis
        if elements := soup.select('.description p'):
            data['synopsis'] = '\n\n'.join([p.text.strip() for p in elements])

        # Chapters
        for element in soup.select('dl.chapter-list dd'):
            if a_element := element.select_one('a'):
                date_text = None
                if small := element.select_one('small:-soup-contains("release")'):
                    date_text = small.text[8:].strip()

                data['chapters'].append({
                    'slug': a_element.get('href').split('/')[-1],
                    'title': a_element.text.strip(),
                    'date': convert_date_string(date_text) if date_text else None,
                })

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

        pages = None
        for script_element in soup.select('script'):
            script = script_element.string
            if script is None:
                continue

            for line in script.split('\n'):
                line = line.strip()
                if line.startswith('var pages'):
                    pages = line.replace('var pages = ', '')[:-1]
                    break
            if pages is not None:
                pages = json.loads(pages)
                break

        if pages is None:
            return None

        data = {
            'pages': [],
        }
        for page in pages:
            data['pages'].append({
                'slug': None,  # not necessary, we know image url directly
                'image': self.base_url + page['image'],
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

        return {
            'buffer': r.content,
            'mime_type': mime_type,
            'name': page['image'].split('?')[0].split('/')[-1],
        }

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def resolve_tag(self, search_tag):
        r = self.session_post(self.tags_url, params={'query': search_tag})
        if r.status_code != 200:
            return None

        for tag in r.json():
            if tag['name'].lower() == search_tag.lower():
                return tag['id']

        return None

    def get_manga_list(self, term=None, classes=None, with_tags='', without_tags=''):
        with_tags = [self.resolve_tag(t.strip()) for t in with_tags.split(',') if t]
        without_tags = [self.resolve_tag(t.strip()) for t in without_tags.split(',') if t]
        classes = sorted(classes, key=str.lower) if classes else []

        params = {
            'q': '',
            'classes[]': classes,
            'with[]': with_tags,
            'without[]': without_tags,
            'sort': '',
        }

        if term:
            # Search
            params['q'] = term
        else:
            # Latest
            params['sort'] = 'created_at'

        r = self.session_get(self.search_url, params=params)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for a_element in soup.select('dl.chapter-list dd a.name'):
            slug = a_element.get('href').lstrip('/')
            if slug.startswith('chapters/'):
                # Check if chapter belongs to a serie
                if matches := re.search(r'([a-z_\/]*)_ch[0-9_]*', slug):
                    slug = matches.group(1).replace('chapters/', 'series/')

            results.append({
                'slug': slug,
                'name': a_element.text.strip(),
            })

        return results

    def get_latest_updates(self, classes=None, with_tags='', without_tags=''):
        return self.get_manga_list(classes=classes, with_tags=with_tags, without_tags=without_tags)

    def search(self, term, classes=None, with_tags='', without_tags=''):
        return self.get_manga_list(term=term, classes=classes, with_tags=with_tags, without_tags=without_tags)
