# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
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
from komikku.servers.utils import get_soup_element_inner_text
from komikku.utils import get_buffer_mime_type
from komikku.utils import get_response_elapsed
from komikku.utils import is_number

SEARCH_RESULTS_PAGES = 2

# Seems to be linked to MangaHere


class Mangatown(Server):
    id = 'mangatown'
    name = 'MangaTown'
    lang = 'en'

    is_nsfw = True

    base_url = 'https://www.mangatown.com'
    logo_url = 'https://static.mangatown.com/v20251117/mangatown/images/favicon.ico'

    manga_url = base_url + '/title/{0}'
    search_url = base_url + '/search'
    manga_list_url = base_url + '/directory/{0}-{1}-{2}-{3}-{4}-{5}/'
    manga_url = base_url + '/manga/{0}/'
    chapter_url = base_url + '/manga/{0}/{1}/'
    page_url = base_url + '/manga/{0}/{1}/{2}.html'

    filters = [
        {
            'key': 'demographic',
            'type': 'select',
            'name': _('Demographic'),
            'description': _('Filter by Publication Demographic'),
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': _('All')},
                {'key': 'shounen', 'name': _('Shounen')},
                {'key': 'seinen', 'name': _('Seinen')},
                {'key': 'shoujo', 'name': _('Shoujo')},
                {'key': 'yaoi', 'name': _('Yaoi')},
                {'key': 'shoujo_ai', 'name': _('Shoujo Ai')},
                {'key': 'josei', 'name': _('Josei')},
                {'key': 'shounen_ai', 'name': _('Shounen Ai')},
                {'key': 'yuri', 'name': _('Yuri')},
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
                {'key': '', 'name': _('All')},
                {'key': 'new', 'name': _('New')},
                {'key': 'ongoing', 'name': _('Ongoing')},
                {'key': 'completed', 'name': _('Completed')},
            ]
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
                {'key': 'manga', 'name': _('Manga')},
                {'key': 'manhua', 'name': _('Manhua')},
                {'key': 'manhwa', 'name': _('Manhwa')},
            ]
        },
    ]

    headers = {
        'User-Agent': USER_AGENT,
    }

    long_strip_genres = [
        'Webtoons',
    ]

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers = self.headers

    def get_manga_data(self, initial_data):
        """
        Returns manga data from manga HTML page

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

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

        data['name'] = soup.select_one('h1.title-top').text.strip()
        data['cover'] = soup.select_one('.detail_info > img').get('src')

        if element := soup.select_one('.detail_info li:-soup-contains("Author") a'):
            data['authors'].append(element.text.strip())
        if element := soup.select_one('.detail_info li:-soup-contains("Artist") a'):
            artist = element.text.strip()
            if artist not in data['authors']:
                data['authors'].append(artist)

        if element := soup.select_one('.detail_info li:-soup-contains("Status")'):
            status = get_soup_element_inner_text(element, recursive=False).split()[0]
            if status == 'Ongoing':
                data['status'] = 'ongoing'
            elif status == 'Completed':
                data['status'] = 'complete'

        for element in soup.select('.detail_info li:-soup-contains("Genre") a'):
            data['genres'].append(element.text.strip())
        if element := soup.select_one('.detail_info li:-soup-contains("Demographic") a'):
            data['genres'].append(element.text.strip())
        if element := soup.select_one('.detail_info li:-soup-contains("Type") a'):
            data['genres'].append(element.text.strip())

        if element := soup.select_one('.detail_info li:-soup-contains("Summary") #show'):
            data['synopsis'] = element.text.replace('HIDE', '').strip()

        for element in reversed(soup.select('.chapter_list li')):
            slug = element.a.get('href').split('/')[-2]
            num = slug[1:]
            date = element.select_one('.time').text.replace('Today', '').replace('Yesterday', '').strip()

            data['chapters'].append({
                'slug': slug,
                'title': f'Ch. {num}',
                'num': num if is_number(num) else None,
                'date': convert_date_string(date, format='%b %d,%Y', languages=[self.lang]),
            })

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data from chapter HTML page
        """
        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )
        if soup.select_one('#viewer #image'):
            # Single page mode
            if element := soup.select_one('.page_select select'):
                for option_element in element.select('option'):
                    url = option_element.get('value')
                    slug = url.split('/')[-1].replace('.html', '')
                    if slug == 'featured':
                        continue
                    if slug == '':
                        slug = '1'

                    data['pages'].append({
                        'slug': slug,
                        'image': None,
                    })
        else:
            # Webtoon mode
            for img_element in soup.select('#viewer .image'):
                url = img_element.get('src')

                data['pages'].append({
                    'slug': None,
                    'image': img_element.get('src'),
                })

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        if slug := page['slug']:
            r = self.session_get(self.page_url.format(manga_slug, chapter_slug, slug))
            if r.status_code != 200:
                return None

            soup = BeautifulSoup(r.text, 'lxml')

            if img_element := soup.select_one('#image'):
                url = img_element.get('src')
            else:
                return None
        else:
            url = page['image']

        if not url.startswith('https:'):
            url = f'https:{url}'  # noqa

        r = self.session_get(
            url,
            headers={
                'Referer': self.page_url.format(manga_slug, chapter_slug, page['slug']),
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
            name=url.split('/')[-1],
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_manga_list(self, term=None, demographic=None, status=None, type=None, orderby=None):
        def get_page(page):
            params = {}

            if term:
                url = self.search_url

                params['page'] = page
                params['name_method'] = 'cw'
                params['name'] = term

                if type is not None:
                    params['type'] = type
                if demographic is not None:
                    params['demographic'] = demographic.replace('_', '').upper()
                if status is not None:
                    if status in ('new', 'ongoing'):
                        params['is_completed'] = 0
                    elif status == 'completed':
                        params['is_completed'] = 1
            else:
                url = self.manga_list_url
                if page > 1:
                    url = f'{url}{page}.html'
                if orderby == 'latest':
                    url = f'{url}?last_chapter_time.za'

                url = url.format(
                    demographic if demographic else 0,
                    0,  # genre
                    0,  # year
                    status if status else 0,
                    0,  # alphabetic
                    type if type else 0,
                )

            r = self.session_get(
                url,
                params=params,
                headers={
                    'Referer': f'{self.base_url}/',
                }
            )
            if r.status_code != 200:
                return [], False, None

            soup = BeautifulSoup(r.text, 'lxml')

            items = []
            for element in soup.select('.manga_pic_list li'):
                cover_element = element.select_one('.manga_cover img')
                a_element = element.select_one('.title a')
                last_chapter_element = element.select_one('.new_chapter a')

                items.append({
                    'slug': a_element.get('href').split('/')[-2],
                    'name': a_element.get('title'),
                    'cover': cover_element.get('src'),
                    'last_chapter': last_chapter_element.get('title').split()[-1],
                })

            more = 'javascript' not in soup.select_one('.next-page a.next').get('href') and page < SEARCH_RESULTS_PAGES

            return items, more, get_response_elapsed(r)

        results = []
        delay = None
        more = True
        page = 1
        while more:
            if delay:
                time.sleep(delay)

            items, more, rtime = get_page(page)
            results += items

            delay = min(rtime * 4, DOWNLOAD_MAX_DELAY) if rtime else None
            page += 1

        return results

    def get_latest_updates(self, demographic=None, status=None, type=None):
        return self.get_manga_list(demographic=demographic, status=status, type=type, orderby='latest')

    def get_most_populars(self, demographic=None, status=None, type=None):
        return self.get_manga_list(demographic=demographic, status=status, type=type, orderby='popular')

    def search(self, term, demographic=None, status=None, type=None):
        return self.get_manga_list(term=term, demographic=demographic, type=type, status=status)
