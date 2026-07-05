# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import time

from bs4 import BeautifulSoup
import requests

from komikku.consts import DOWNLOAD_MAX_DELAY
from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import get_response_elapsed
from komikku.utils import is_number


class Rncalation(Server):
    id = 'rncalation'
    name = 'Rncalation'
    lang = 'es'

    base_url = 'https://rncalation.online'
    logo_url = base_url + '/icons/icon-96.png'
    search_url = base_url + '/library'
    manga_url = base_url + '/comics/{0}'
    chapters_url = base_url + '/comics/{0}/chapters'
    chapter_url = base_url + '/comics/{0}/cap/{1}'

    filters = [
        {
            'key': 'type',
            'type': 'select',
            'name': _('Type'),
            'description': _('Filter by Type'),
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': _('Any')},
                {'key': 'Manga', 'name': _('Manga')},
                {'key': 'Manhwa', 'name': _('Manhwa')},
                {'key': 'Manhua', 'name': _('Manhua')},
                {'key': 'Doujinshi', 'name': _('Doujinshi')},
                {'key': 'Other', 'name': _('Other')},
            ]
        },
        {
            'key': 'status',
            'type': 'select',
            'name': _('Status'),
            'description': _('Filter by Status'),
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': _('Any')},
                {'key': 'Ongoing', 'name': _('Ongoing')},
                {'key': 'Completed', 'name': _('Completed')},
                {'key': 'Hiatus', 'name': _('Hiatus')},
                {'key': 'Cancelled', 'name': _('Canceled')},
            ]
        },
    ]

    headers = {
        'User-Agent': USER_AGENT,
    }

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers = self.headers

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

        data['name'] = soup.select_one('h1').text.strip()
        data['cover'] = self.base_url + soup.select_one('img.comic-cover__img').get('src')

        # Status
        if element := soup.select_one('.flex.items-baseline:-soup-contains("Estado") span.text-right'):
            status = element.text.strip()
            if status == 'Completado':
                data['status'] = 'complete'
            elif status == 'En emisión':
                data['status'] = 'ongoing'
            elif status == 'En pausa':
                data['status'] = 'hiatus'
            elif status == 'Cancelado':
                data['status'] = 'suspended'

        # Authors
        if element := soup.select_one('.flex.items-baseline:-soup-contains("Autor") span.text-right'):
            data['authors'].append(element.text.strip())

        if element := soup.select_one('.flex.items-baseline:-soup-contains("Arte") span.text-right'):
            artist = element.text.strip()
            if artist not in data['authors']:
                data['authors'].append(artist)

        # Genres
        for element in soup.select('span.inline-flex.items-center.rounded'):
            badge = element.text.strip().lower().capitalize()
            if badge in ('Manga', 'Manhwa', 'Manhua', 'Doujinshi'):
                data['genres'].append(badge)
                break

        if element := soup.select_one('.flex.items-baseline:-soup-contains("Demográfico") span.text-right'):
            demogrpahic = element.text.strip()
            if demogrpahic not in data['genres']:
                data['genres'].append(demogrpahic)

        if element := soup.select_one('.flex.items-baseline:-soup-contains("Géneros") span.text-right'):
            for genre in element.text.split(','):
                data['genres'].append(genre.strip())

        # Scanlators
        if element := soup.select_one('.flex.flex-col > a'):
            data['scanlators'].append(element.text.strip())

        # Synopsis
        data['synopsis'] = soup.select_one('p.m-0').text.strip()

        # Chapters
        data['chapters'] = self.get_manga_chapters_data(data['slug'])

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )
        for img_element in soup.select('img.page-img, .page-wrap img'):
            image = img_element.get('data-src') or img_element.get('src')
            if not image:
                continue

            data['pages'].append(dict(
                image=image,
                slug=None,
            ))

        return data

    def get_manga_chapters_data(self, manga_slug):
        def get_page(page):
            r = self.session_get(
                self.chapters_url.format(manga_slug),
                params=dict(
                    page=page,
                )
            )
            if r.status_code != 200:
                return None

            soup = BeautifulSoup(r.text, 'lxml')

            items = []
            for a_element in soup.select('a'):
                if date_element := a_element.select_one('span.uppercase'):
                    date = date_element.text.strip()
                else:
                    date = None
                num = a_element.get('data-chapter-num')

                items.append({
                    'title': a_element.get('data-chapter-label'),
                    'slug': a_element.get('href').split('/')[-1],
                    'num': num if is_number(num) else None,
                    'date': convert_date_string(date, format='%B %d, %Y'),
                })

            more = len(items) == 30

            return items, more, get_response_elapsed(r)

        chapters = []
        delay = None
        more = True
        page = 1
        while more:
            if delay:
                time.sleep(delay)

            items, more, rtime = get_page(page)
            chapters += items

            delay = min(rtime * 2, DOWNLOAD_MAX_DELAY) if rtime else None
            page += 1

        return list(reversed(chapters))

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            page['image'],
            headers={
                'Referer': f'{self.base_url}/',
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

    def get_manga_list(self, term=None, type=None, status=None, orderby=None):
        params = {
            'type': type,
            'status': status,
        }
        if term is not None:
            params['q'] = term
            params['sort'] = 'title'
        elif orderby == 'populars':
            params['sort'] = 'views'
        elif orderby == 'latest':
            params['sort'] = 'latest'

        r = self.session_get(self.search_url, params=params)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for a_element in soup.select('.lib-grid > a.comic-card'):
            type_ = a_element.select_one('.absolute.top-2.left-2').text.strip()
            if type_ == 'Novel':
                continue

            img_element = a_element.select_one('img.comic-cover__img')
            results.append(dict(
                slug=a_element.get('href').split('/')[-1],
                name=img_element.get('alt'),
                cover=self.base_url + img_element.get('src'),
            ))

        return results

    def get_latest_updates(self, type=None, status=None):
        """
        Returns latest updates
        """
        return self.get_manga_list(type=type, status=status, orderby='latest')

    def get_most_populars(self, type=None, status=None):
        """
        Returns most viewed
        """
        return self.get_manga_list(type=type, status=status, orderby='populars')

    def search(self, term, type=None, status=None):
        return self.get_manga_list(term=term, type=type, status=status)
