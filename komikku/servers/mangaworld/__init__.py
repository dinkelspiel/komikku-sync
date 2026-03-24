# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from functools import wraps
from gettext import gettext as _

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number
from komikku.webview import get_page_html


def get_mwcookie(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        server = args[0]

        found = False
        for name, _value in server.session.cookies.items():
            if name == 'MWCookie':
                found = True
                break

        if not found:
            _html, cookies = get_page_html(server.base_url, user_agent=USER_AGENT, with_cookies=True)

            for cookie in cookies:
                if cookie.name == 'MWCookie':
                    server.session.cookies.set_cookie(cookie)
                    break

        return func(*args, **kwargs)

    return wrapper


class Mangaworld(Server):
    id = 'mangaworld'
    name = 'MangaWorld'
    lang = 'it'
    is_nsfw = True

    base_url = 'https://www.mangaworld.cx'
    logo_url = base_url + '/public/assets/seo/favicon-32x32.png'
    search_url = base_url + '/archive'
    manga_url = base_url + '/manga/{0}'
    chapter_url = base_url + '/manga/{0}/read/{1}/1?style=list'

    filters = [
        {
            'key': 'types',
            'type': 'select',
            'name': _('Type'),
            'description': _('Filter by Types'),
            'value_type': 'multiple',
            'options': [
                {'key': 'manga', 'name': _('Manga'), 'default': False},
                {'key': 'manhua', 'name': _('Manhua'), 'default': False},
                {'key': 'manhwa', 'name': _('Manhwa'), 'default': False},
                {'key': 'oneshot', 'name': _('Oneshot'), 'default': False},
                {'key': 'thai', 'name': 'Thai', 'default': False},
                {'key': 'vietnamese', 'name': 'Vietnamita', 'default': False},
            ],
        },
        {
            'key': 'statuses',
            'type': 'select',
            'name': _('Status'),
            'description': _('Filter by Statuses'),
            'value_type': 'multiple',
            'options': [
                {'key': 'ongoing', 'name': _('Ongoing'), 'default': False},
                {'key': 'completed', 'name': _('Complete'), 'default': False},
                {'key': 'dropped', 'name': _('Suspended'), 'default': False},
                {'key': 'paused', 'name': _('Hiatus'), 'default': False},
                {'key': 'canceled', 'name': _('Canceled'), 'default': False},
            ],
        },
    ]

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': USER_AGENT,
            })

    @get_mwcookie
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
            scanlators=[],
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        info_element = soup.find(class_='comic-info')

        # Name & cover
        data['name'] = info_element.find('h1', class_='name').text.strip()
        data['cover'] = info_element.find(class_='thumb').img.get('src')

        # Details
        details_element = info_element.find(class_='meta-data')
        for element in details_element.find_all('div'):
            label = element.span.text.strip()
            if label.startswith('Generi'):
                for a_element in element.find_all('a'):
                    data['genres'].append(a_element.text.strip())
            elif label.startswith(('Autore', 'Artista', 'Autori', 'Artisti')):
                for a_element in element.find_all('a'):
                    author = a_element.text.strip()
                    if author not in data['authors']:
                        data['authors'].append(author)
            elif label.startswith('Stato'):
                status = element.a.text.strip().lower()
                if status == 'in corso':
                    data['status'] = 'ongoing'
                elif status == 'finito':
                    data['status'] = 'complete'
                elif status in ('cancellato', 'droppato'):
                    data['status'] = 'suspended'
                elif status == 'in pausa':
                    data['status'] = 'hiatus'

        # Synopsis
        data['synopsis'] = soup.select_one('.comic-description div:nth-child(2)').text.strip()

        # Chapters
        for element in reversed(soup.select('.chapters-wrapper .chapter')):
            title = element.span.text.strip()
            num = title.split(' ')[-1]  # Capitolo XXX[.X]

            data['chapters'].append(dict(
                slug=element.a.get('href').split('/')[-1],
                title=title,
                num=num if is_number(num) else None,
                date=convert_date_string(element.i.text.strip()),
            ))

        return data

    @get_mwcookie
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )
        for img_element in soup.find_all('img', class_='page-image'):
            data['pages'].append(dict(
                slug=None,
                image=img_element.get('src'),
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(page['image'])
        if r.status_code != 200:
            return None

        buffer = r.content
        mime_type = get_buffer_mime_type(buffer)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=buffer,
            mime_type=mime_type,
            name=page['image'].split('/')[-1],
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_latest_updates(self, types=None, statuses=None):
        return self.search('', types, statuses, orderby='latest')

    def get_most_populars(self, types=None, statuses=None):
        return self.search('', types, statuses, orderby='populars')

    @get_mwcookie
    def search(self, term, types=None, statuses=None, orderby=None):
        if orderby:
            params = {
                'sort': 'most_read' if orderby == 'populars' else 'newest',
            }
        else:
            params = {
                'keyword': term,
            }
        if types:
            params['type'] = types
        if statuses:
            params['status'] = statuses

        r = self.session_get(self.search_url, params=params)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for a_element in soup.select('.comics-grid .entry > a'):
            results.append(dict(
                name=a_element.get('title').strip(),
                slug='/'.join(a_element.get('href').split('/')[-2:]),
                cover=a_element.img.get('src'),
            ))

        return results
