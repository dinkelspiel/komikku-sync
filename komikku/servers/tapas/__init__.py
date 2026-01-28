# SPDX-FileCopyrightText: 2021-2024 Lili Kurek
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Lili Kurek <lilikurek@proton.me>

import datetime
import logging
import time

from bs4 import BeautifulSoup
import requests

from komikku.consts import DOWNLOAD_MAX_DELAY
from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import get_response_elapsed

logger = logging.getLogger('komikku.servers.tapas')

# each page is 10 entries
SEARCH_RESULTS_PAGES = 10
CHAPTERS_PER_REQUEST = 20


class Tapas(Server):
    id = 'tapas'
    name = 'Tapas'
    lang = 'en'
    status = 'disabled'  # commercial platforms are no supported

    base_url = 'https://tapas.io'
    api_base_url = 'https://story-api.tapas.io'
    api_manga_list_url = api_base_url + '/cosmos/api/v1/landing/genre'
    search_url = base_url + '/search'
    manga_url = base_url + '/series/{0}'
    manga_info_url = base_url + '/series/{0}/info'
    chapters_url = base_url + '/series/{0}/episodes'
    chapter_url = base_url + '/episode/{0}'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'user-agent': USER_AGENT})
            for name in ('birthDate', 'adjustedBirthDate'):
                cookie = requests.cookies.create_cookie(
                    name=name,
                    value='2001-01-01',
                    domain='tapas.io',
                    path='/',
                    expires=None,
                )
                self.session.cookies.set_cookie(cookie)

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        r = self.session_get(self.manga_info_url.format(initial_data['slug']))
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
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

        data['name'] = soup.find(class_='section__top--simple').find(class_='title').text
        data['synopsis'] = soup.select_one('.description__body').text.strip()
        data['cover'] = soup.find(class_='section__top--simple').find(class_='thumb').img.get('src')

        for author_element in soup.find(class_='creator').find_all('a'):
            data['authors'].append(author_element.text)

        if element := soup.select_one('.tags'):
            # Community series
            for a_element in element.select('a'):
                data['genres'].append(a_element.text.strip().replace('#', ''))
        elif elements := soup.select('.detail-row__body--genre a'):
            for a_element in elements:
                data['genres'].append(a_element.text.strip())

        data['chapters'] = self.get_manga_chapters_data(initial_data['slug'])

        return data

    def get_manga_chapters_data(self, manga_slug):
        def get_page(page):
            r = self.session_get(
                self.chapters_url.format(manga_slug),
                params=dict(
                    page=page,
                    sort='OLDEST',
                    init_load=0,
                    max_limit=CHAPTERS_PER_REQUEST,
                    since=int(datetime.datetime.now().timestamp()) * 1000,
                    large='true',
                    last_access=0,
                )
            )
            if r.status_code != 200:
                return None

            resp_data = r.json()['data']
            more = resp_data['pagination']['has_next']

            return resp_data['episodes'], more, get_response_elapsed(r)

        chapters = []
        delay = None
        more = True
        page = 1
        while more:
            if delay:
                time.sleep(delay)

            episodes, more, rtime = get_page(page)
            for episode in episodes:
                if not episode['free'] or episode['must_pay'] or episode['scheduled']:
                    continue

                chapters.append(dict(
                    slug=str(episode['id']),  # slug nust be a string
                    title=episode['title'],
                    date=convert_date_string(episode['publish_date'].split('T')[0], format='%Y-%m-%d'),
                ))

            delay = min(rtime * 2, DOWNLOAD_MAX_DELAY) if rtime else None
            page += 1

        return chapters

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(chapter_slug))
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            slug=chapter_slug,
            title=soup.find(class_='title').text,
            pages=[],
            date=convert_date_string(soup.find(class_='date').text, format='%b %d, %Y'),
        )

        for page in soup.find(class_='js-episode-article').find_all('img'):
            data['pages'].append(dict(
                slug=None,
                image=page.get('data-src'),
            ))

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

    def get_manga_list(self, orderby):
        def get_page(page):
            r = self.session_get(
                self.api_manga_list_url,
                params=dict(
                    category_type='COMIC',
                    sort_option=orderby,
                    subtab_id=17,
                    page=page,
                    size=25,
                ),
                headers={
                    'Origin': self.base_url,
                    'Referer': f'{self.base_url}/',
                }
            )
            if r.status_code != 200:
                return None

            resp_data = r.json()

            more = not resp_data['meta']['pagination']['last'] and page < SEARCH_RESULTS_PAGES

            return resp_data['data']['items'], more, get_response_elapsed(r)

        delay = None
        more = True
        page = 0
        results = []
        while more:
            if delay:
                time.sleep(delay)

            items, more, rtime = get_page(page)
            for item in items:
                if item['bmType'] == 'WAIT_UNTIL_FREE':
                    continue

                if item['assetProperty'].get('backgroundCharacterImage'):
                    img_obj = item['assetProperty']['backgroundCharacterImage']
                else:
                    img_obj = item['assetProperty'].get('thumbnailImage')

                results.append(dict(
                    slug=item['seriesId'],
                    name=item['title'],
                    cover=img_obj['path'] + '.webp' if img_obj else None,
                ))

            delay = min(rtime * 2, DOWNLOAD_MAX_DELAY) if rtime else None
            page += 1

        return results

    def get_latest_updates(self):
        return self.get_manga_list(orderby='NEWEST_EPISODE')

    def get_most_populars(self):
        return self.get_manga_list(orderby='POPULAR')

    def search(self, term, page_number=1):
        r = self.session_get(
            self.search_url,
            params=dict(
                pageNumber=page_number,
                q=term,
                t='COMICS',
            ),
            headers={
                'Referer': self.search_url,
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for li_element in soup.select('.search-item-wrap'):
            a_element = li_element.select_one('.title-section a.link')

            if a_element.get('data-sale-type') not in ('EARLY_ACCESS', 'FREE', 'false', 'WAIT_OR_MUST_PAY'):
                continue

            results.append(dict(
                slug=a_element.get('data-series-id'),
                url=a_element.get('href'),
                name=a_element.text,
                cover=li_element.select_one('.item-thumb-wrap img').get('src'),
            ))

        if page_number == 1:
            if buttons := soup.select('a.paging__button--num'):
                last_page_number = int(buttons[-1].text)

                for page in range(2, min(SEARCH_RESULTS_PAGES + 1, last_page_number + 1)):
                    results += self.search(term, page)

        return results
