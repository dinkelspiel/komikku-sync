# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import datetime
from gettext import gettext as _
import time
from urllib.parse import parse_qs
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests
from urllib.parse import urlsplit

from komikku.consts import DOWNLOAD_MAX_DELAY
from komikku.consts import USER_AGENT
from komikku.consts import USER_AGENT_MOBILE
from komikku.servers import Server
from komikku.servers.utils import get_soup_element_inner_text
from komikku.utils import get_buffer_mime_type
from komikku.utils import get_response_elapsed
from komikku.utils import is_number

CHAPTERS_PER_REQUEST = 30
LANGUAGES_CODES = dict(
    en='en',
    es='es',
    fr='fr',
    id='id',
    th='th',
    zh_Hant='zh-hant',  # diff
)

SERVER_NAME = 'WEBTOON'


class Webtoon(Server):
    id = 'webtoon'
    name = SERVER_NAME
    lang = 'en'
    status = 'disabled'  # commercial platforms are no supported

    base_url = 'https://www.webtoons.com'
    logo_url = 'https://webtoons-static.pstatic.net/image/favicon/favicon.ico?dt=2017082301'
    search_url = base_url + '/{0}/search/{1}'
    most_populars_url = base_url + '/{0}/ranking/{1}'
    manga_url = base_url + '{0}'
    api_chapters_url = 'https://m.webtoons.com/api/v1/{type}/{sid}/episodes'
    chapter_url = base_url + '{0}'

    filters = [
        {
            'key': 'type',
            'type': 'select',
            'name': _('Type'),
            'description': _('Filter by Type'),
            'value_type': 'single',
            'default': 'all',
            'options': [
                {'key': 'all', 'name': _('All')},
                {'key': 'originals', 'name': _('Originals')},
                {'key': 'canvas', 'name': _('Canvas')},
            ],
        },
    ]

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()

    @classmethod
    def get_manga_initial_data_from_url(cls, url):
        return dict(url=url.replace(cls.base_url, ''), slug=url.split('=')[-1])

    def _get_manga_cover_url(self, url):
        # No cover in manga page, use RSS feed
        r = self.session_get(self.manga_url.format(url.replace('list?', 'rss?')), headers={'User-Agent': USER_AGENT})
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/xml':
            return None

        soup = BeautifulSoup(r.text, features='xml')
        if element := soup.select_one('image url'):
            return element.text.strip()

        return None

    def _parse_results_page(self, response):
        soup = BeautifulSoup(response.text, 'lxml')

        results = []
        for a_element in soup.select('.webtoon_list > li > a'):
            # Small difference here compared to the majority of servers
            # slug can't be used to forge manga URL, we must store the full url (relative)
            results.append(dict(
                slug=a_element.get('href').split('=')[-1],
                url=a_element.get('href').replace(self.base_url, ''),
                name=a_element.select_one('.info_text .title').text.strip(),
                cover=a_element.select_one('img').get('src'),
            ))

        return results

    def _search_by_ranking(self, ranking):
        # Clear cookies
        # Seems to help to bypass some region-based restrictions?!?
        self.session.cookies.clear()

        r = self.session_get(
            self.most_populars_url.format(LANGUAGES_CODES[self.lang], ranking),
            headers={
                'User-Agent': USER_AGENT,
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        return self._parse_results_page(r)

    def _search_by_type(self, term, type):
        # Clear cookies
        # Seems to help to bypass some region-based restrictions?!?
        self.session.cookies.clear()

        r = self.session_get(
            self.search_url.format(LANGUAGES_CODES[self.lang], type),
            params=dict(
                keyword=term,
                searchMode='ALL',
            ),
            headers={'User-Agent': USER_AGENT}
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        return self._parse_results_page(r)

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's url (provided by search)
        """
        assert 'url' in initial_data, 'Manga url is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['url']), headers={'User-Agent': USER_AGENT})
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        # Get true URL after redirects
        split_url = urlsplit(r.url)
        url = '{0}?{1}'.format(split_url.path, split_url.query)

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update(dict(
            url=url,
            authors=[],
            scanlators=[],
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        data['name'] = get_soup_element_inner_text(soup.find(class_='subj'))

        # Details
        info_element = soup.find('div', class_='info')
        for element in info_element.find_all(class_='genre'):
            data['genres'].append(get_soup_element_inner_text(element))

        if 'canvas' in data['url']:
            # Canvas/Challenge
            detail_element = soup.find('div', class_='detail')

            data['cover'] = soup.find('div', class_='detail_header').img.get('src')

            for element in info_element.find_all(class_='author'):
                data['authors'].append(get_soup_element_inner_text(element))
        else:
            # Original/Webtoon
            detail_element = soup.find('div', class_='detail_body')

            data['cover'] = self._get_manga_cover_url(data['url'])

            try:
                for element in soup.find('div', class_='_authorInnerContent').find_all('h3'):
                    data['authors'].append(element.text.strip())
            except Exception:
                for element in info_element.find_all(class_='author'):
                    data['authors'].append(get_soup_element_inner_text(element))

            status_class = ''.join(detail_element.find('p', class_='day_info').span.get('class'))
            if 'completed' in status_class:
                data['status'] = 'complete'
            else:
                data['status'] = 'ongoing'

        data['synopsis'] = detail_element.find('p', class_='summary').text.strip()

        # Chapters
        data['chapters'] = self.get_manga_chapters_data(data['url'])

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(chapter_url), headers={'User-Agent': USER_AGENT})
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        imgs = soup.find('div', id='_imageList').find_all('img')

        data = dict(
            pages=[],
        )
        for index, img in enumerate(imgs):
            data['pages'].append(dict(
                index=index + 1,
                slug=None,  # slug can't be used to forge image URL
                image=img.get('data-url').strip(),
            ))

        return data

    def get_manga_chapters_data(self, url):
        """
        Returns manga chapters data using API of mobile site
        """
        chapters = []
        sid = parse_qs(urlparse(url).query)['title_no'][0]
        if '/canvas/' in url:
            type = 'canvas'
        else:
            type = 'webtoon'

        def get_page(cursor):
            params = dict(
                pageSize=CHAPTERS_PER_REQUEST,
            )
            if cursor:
                params['cursor'] = cursor

            r = self.session_get(
                self.api_chapters_url.format(type=type, sid=sid),
                params=params,
                headers={
                    'User-Agent': USER_AGENT_MOBILE,
                }
            )
            if r.status_code != 200:
                return None

            next_cursor = r.json()['result']['nextCursor']

            return r.json()['result']['episodeList'], next_cursor, get_response_elapsed(r)

        chapters = []
        cursor = None
        delay = None
        while cursor != 0:
            if delay:
                time.sleep(delay)

            episodes, cursor, rtime = get_page(cursor)
            for episode in episodes:
                title = episode['episodeTitle']
                if episode.get('hasBgm'):
                    title += ' ♫'
                num = episode['episodeNo']

                chapters.append(dict(
                    slug=str(num),  # slug nust be a string
                    title=title,
                    num=num if is_number(num) else None,
                    date=datetime.datetime.fromtimestamp(episode['exposureDateMillis'] / 1000).date(),
                    url=episode['viewerLink'],
                ))

            delay = min(rtime * 2, DOWNLOAD_MAX_DELAY) if rtime else None

        return chapters

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(page['image'], headers={'Referer': self.base_url, 'User-Agent': USER_AGENT})
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
        Returns manga absolute URL
        """
        return self.manga_url.format(url)

    def get_most_populars(self, type='all'):
        """
        Returns popular manga
        """
        results = None

        if type == 'all' or type == 'originals':
            if originals_results := self._search_by_ranking('popular'):
                results = originals_results

        if type == 'all' or type == 'canvas':
            if canvas_results := self._search_by_ranking('canvas'):
                if results is None:
                    results = canvas_results
                else:
                    results += canvas_results

        return results

    def is_long_strip(self, _manga_data):
        return True

    def search(self, term, type='all'):
        results = None

        if type == 'all' or type == 'originals':
            if originals_results := self._search_by_type(term, 'originals'):
                results = originals_results

        if type == 'all' or type == 'canvas':
            if canvas_results := self._search_by_type(term, 'canvas'):
                if results is None:
                    results = canvas_results
                else:
                    results += canvas_results

        return results


class Dongmanmanhua(Webtoon):
    id = 'dongmanmanhua:webtoon'
    name = 'Dongman Manhua'
    lang = 'zh_Hans'

    base_url = 'https://www.dongmanmanhua.cn'
    search_url = base_url + '/search'
    most_populars_url = base_url + '/top'
    manga_url = base_url + '{0}'
    chapters_url = 'https://m.dongmanmanhua.cn/{0}'
    chapter_url = base_url + '{0}'


class Webtoon_es(Webtoon):
    id = 'webtoon_es'
    name = SERVER_NAME
    lang = 'es'


class Webtoon_fr(Webtoon):
    id = 'webtoon_fr'
    name = SERVER_NAME
    lang = 'fr'


class Webtoon_id(Webtoon):
    id = 'webtoon_id'
    name = SERVER_NAME
    lang = 'id'


class Webtoon_th(Webtoon):
    id = 'webtoon_th'
    name = SERVER_NAME
    lang = 'th'


class Webtoon_zh_hant(Webtoon):
    id = 'webtoon_zh_hant'
    name = SERVER_NAME
    lang = 'zh_Hant'
