# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import datetime
from gettext import gettext as _
import time

from bs4 import BeautifulSoup

from komikku.consts import DOWNLOAD_MAX_DELAY
from komikku.servers import Server
from komikku.servers.utils import get_soup_element_inner_text
from komikku.servers.utils import parse_nextjs_hydration
from komikku.utils import get_buffer_mime_type
from komikku.utils import get_response_elapsed
from komikku.utils import is_number
from komikku.webview import CompleteChallenge

SEARCH_RESULTS_PAGES = 4


class Comix(Server):
    id = 'comix'
    name = 'Comix'
    lang = 'en'
    is_nsfw = True

    has_cf = True

    base_url = 'https://comix.to'
    logo_url = base_url + '/icon.png?icon.530a1f27.png'
    api_url = 'https://comix.to/api/v2'
    api_search_url = api_url + '/manga'
    manga_url = base_url + '/title/{0}'
    api_chapters_url = api_url + '/manga/{0}/chapters'
    chapter_url = base_url + '/title/{0}/{1}'

    filters = [
        {
            'key': 'statuses',
            'type': 'select',
            'name': _('Status'),
            'description': _('Filter by Statuses'),
            'value_type': 'multiple',
            'options': [
                {'key': 'releasing', 'name': _('Ongoing'), 'default': False},
                {'key': 'finished', 'name': _('Completed'), 'default': False},
                {'key': 'on_hiatus', 'name': _('Hiatus'), 'default': False},
                {'key': 'discontinued', 'name': _('Canceled'), 'default': False},
            ]
        },
        {
            'key': 'types',
            'type': 'select',
            'name': _('Type'),
            'description': _('Filter by Types'),
            'value_type': 'multiple',
            'options': [
                {'key': 'manga', 'name': _('Manga'), 'default': False},
                {'key': 'manhwa', 'name': _('Manhwa'), 'default': False},
                {'key': 'manhua', 'name': _('Manhua'), 'default': False},
                {'key': 'other', 'name': _('Other'), 'default': False},
            ],
        },
        {
            'key': 'demographics',
            'type': 'select',
            'name': _('Publication Demographic'),
            'description': _('Filter by Publication Demographics'),
            'value_type': 'multiple',
            'options': [
                {'key': 3, 'name': _('Josei'), 'default': False},
                {'key': 4, 'name': _('Seinen'), 'default': False},
                {'key': 1, 'name': _('Shoujo'), 'default': False},
                {'key': 2, 'name': _('Shounen'), 'default': False},
            ]
        },
    ]

    long_strip_genres = ['Manhua', 'Manhwa']

    params = [
        {
            'key': 'hide_nsfw',
            'type': 'checkbox',
            'name': _('Hide NSFW Content'),
            'description': _('Hide NSFW content from popular, latest, and search lists'),
            'default': True,
        },
    ]

    def __init__(self):
        self.session = None

    @CompleteChallenge()
    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content and API for chapters

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

        data['name'] = soup.select_one('h1.title').text.strip()
        data['cover'] = soup.select_one('img[itemprop="image"]').get('src')

        # Details
        if element := soup.select_one('.status'):
            status = element.text.strip()
            if 'FINISHED' in status:
                data['status'] = 'complete'
            elif 'RELEASING' in status:
                data['status'] = 'ongoing'
            elif 'ON HIATUS' in status:
                data['status'] = 'hiatus'
            elif 'DISCONTINUED' in status:
                data['status'] = 'suspended'

        for element in soup.select('#metadata li:-soup-contains("Authors") a'):
            data['authors'].append(element.text.strip())

        for element in soup.select('#metadata li:-soup-contains("Artists") a'):
            artist = element.text.strip()
            if artist not in data['authors']:
                data['authors'].append(artist)

        for element in soup.select('#metadata li:-soup-contains("Genres") a'):
            data['genres'].append(element.text.strip())

        for element in soup.select('#metadata li:-soup-contains("Type") a'):
            data['genres'].append(element.text.strip())

        if element := soup.select_one('.content'):
            data['synopsis'] = get_soup_element_inner_text(element, sep='\n\n')

        # Chapters
        data['chapters'] = self.get_manga_chapters_data(data['slug'])

        return data

    @CompleteChallenge()
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Pages URLs are available in a <script> element
        """
        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        info = parse_nextjs_hydration(soup, 'images')
        if info is None:
            return None

        data = dict(
            pages=[],
        )
        for image in info[3]['chapter']['images']:
            data['pages'].append(dict(
                slug=None,
                image=image['url'],
            ))

        return data

    def get_manga_chapters_data(self, slug):
        """
        Returns manga chapters data using API
        """
        chapters = []
        hash_id = slug.split('-')[0]

        def get_page(page):
            r = self.session_get(
                self.api_chapters_url.format(hash_id),
                params={
                    'order[number]': 'desc',
                    'limit': 100,
                    'page': page,
                },
                headers={
                    'Referer': self.manga_url.format(slug),
                }
            )
            if r.status_code != 200:
                return None

            resp_data = r.json()
            if resp_data['status'] != 200:
                return None

            more = page < resp_data['result']['pagination']['last_page']

            return r.json()['result']['items'], more, get_response_elapsed(r)

        chapters = []
        delay = None
        more = True
        page = 1
        while more:
            if delay:
                time.sleep(delay)

            items, more, rtime = get_page(page)
            for item in items:
                title = f'Ch. {item["number"]}'
                if item['volume']:
                    title = f'{title} Vol {item["volume"]}'
                if item['name']:
                    title = f'{title} {item["name"]}'
                if item['scanlation_group']:
                    scanlators = [item['scanlation_group']['name']]
                elif item['is_official']:
                    scanlators = ['Official']
                else:
                    scanlators = []

                chapters.append(dict(
                    slug=f'{item["chapter_id"]}-chapter-{item["number"]}',
                    title=title,
                    scanlators=scanlators,
                    num=item['number'] if is_number(item['number']) else None,
                    num_volume=item['volume'] if is_number(item['volume']) else None,
                    date=datetime.datetime.fromtimestamp(item['updated_at']).date(),
                ))

            delay = min(rtime * 4, DOWNLOAD_MAX_DELAY) if rtime else None
            page += 1

        return list(reversed(chapters))

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            page['image'],
            headers={
                'Referer': self.chapter_url.format(manga_slug, chapter_slug),
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

    def get_manga_list(self, term=None, statuses=None, types=None, demographics=None, orderby=None):
        def get_page(page):
            params = {
                'limit': 28,
                'page': page,
            }

            if term:
                params.update({
                    'keyword': term,
                    'order[relevance]': 'desc',
                })
            elif orderby == 'latest':
                params.update({
                    'order[chapter_updated_at]': 'desc',
                })
            elif orderby == 'popular':
                params.update({
                    'order[views_30d]': 'desc',
                })

            if statuses:
                params['statuses[]'] = statuses
            if types:
                params['types[]'] = types
            if demographics:
                params['demographics[]'] = demographics

            if self.get_param('hide_nsfw'):
                params['genres[]'] = [-87264, -87266, -87268, -87265]

            r = self.session_get(
                self.api_search_url,
                params=params,
                headers={
                    'Referer': f'{self.base_url}/browser',
                }
            )
            if r.status_code != 200:
                return [], False, None

            resp_data = r.json()
            if resp_data['status'] != 200:
                return [], False, None

            more = page < resp_data['result']['pagination']['last_page'] and page < SEARCH_RESULTS_PAGES

            return resp_data['result']['items'], more, get_response_elapsed(r)

        results = []
        delay = None
        more = True
        page = 1
        while more:
            if delay:
                time.sleep(delay)

            items, more, rtime = get_page(page)
            for item in items:
                results.append(dict(
                    slug=f'{item["hash_id"]}-{item["slug"]}',
                    name=item['title'],
                    cover=item['poster']['medium'],
                    last_chapter=item['latest_chapter'],
                    nb_chapters=item['final_chapter'],
                ))

            delay = min(rtime * 4, DOWNLOAD_MAX_DELAY) if rtime else None
            page += 1

        return results

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    @CompleteChallenge()
    def get_latest_updates(self, statuses=None, types=None, demographics=None):
        """
        Returns latest updated mangas
        """
        return self.get_manga_list(statuses=statuses, types=types, demographics=demographics, orderby='latest')

    @CompleteChallenge()
    def get_most_populars(self, statuses=None, types=None, demographics=None):
        """
        Returns most popular mangas
        """
        return self.get_manga_list(statuses=statuses, types=types, demographics=demographics, orderby='popular')

    @CompleteChallenge()
    def search(self, term, statuses=None, types=None, demographics=None):
        return self.get_manga_list(term=term, statuses=statuses, types=types, demographics=demographics)
