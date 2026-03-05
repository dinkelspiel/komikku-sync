# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from urllib.parse import parse_qs
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number


class Zerobyway(Server):
    id = 'zerobyway'
    name = 'zero搬运网'
    lang = 'zh_Hans'

    base_url = 'https://www.zerobywai.com'
    logo_url = base_url + '/favicon.ico'
    search_url = base_url + '/pc/pc.php'
    manga_url = base_url + '/pc/manga_pc.php?kuid={0}'
    chapter_url = base_url + '/pc/manga_read_pc.php?zjid={0}'

    filters = [
        {
            'key': 'language',
            'type': 'select',
            'name': '语言',
            'description': None,
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': '全部'},
                {'key': '全中文', 'name': '全中文'},  # All in Chinese
                {'key': '一半中文一半生肉', 'name': '一半中文一半生肉'},  # Half in Chinese, half raw
                {'key': '全生肉', 'name': '全生肉'},  # All raw
            ],
        },
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers = {
            'User-Agent': USER_AGENT,
        }

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
            scanlators=[self.name, ],
            genres=[],
            status='ongoing',
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        data['name'] = soup.find('h1').text.strip()
        data['cover'] = soup.select_one('main > div:first-child img').get('src')

        # Details
        if '【已完结】' in data['name']:
            data['status'] = 'complete'
            data['name'] = data['name'].replace('【已完结】', '').strip()

        for element in soup.select('main > div:first-child div > span'):
            value = element.text.strip()
            if '人气' in value or '收藏' in value:
                continue
            if '作者' in value:
                data['authors'].append(value.split(':')[1].strip())
            else:
                data['genres'].append(value)

        if element := soup.select_one('[x-ref="summaryText"]'):
            data['synopsis'] = element.text.strip()

        # Chapters
        for element in soup.select('main > div:nth-child(2) a'):
            url = element.get('href')
            if 'manga_read_pc' not in url:
                continue

            slug = parse_qs(urlparse(url).query)['zjid'][0]
            num = element.text.strip()
            data['chapters'].append({
                'slug': slug,
                'title': num,
                'num': num if is_number(num) else None,
                'date': None,
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

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )
        for img_element in soup.select('img.manga-image'):
            data['pages'].append(dict(
                slug=None,
                image='https:' + img_element.get('src'),
            ))

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

    def get_manga_list(self, term=None, language=None, orderby=None):
        params = {}
        if language:
            params['shuxing'] = language
        if term:
            params['keyword'] = term
        elif orderby:
            params['order'] = orderby

        r = self.session_get(self.search_url, params=params)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('main div a.group.block'):
            slug = parse_qs(urlparse(element.get('href')).query)['kuid'][0]
            img_element = element.select_one('img')
            if last_chapter_element := element.select_one('p'):
                last_chapter = last_chapter_element.text.split('第')[1][:-1]
            else:
                last_chapter = None

            results.append({
                'slug': slug,
                'name': img_element.get('alt').strip(),
                'cover': img_element.get('src'),
                'last_chapter': last_chapter,
            })

        return results

    def get_latest_updates(self, language=None):
        return self.get_manga_list(language=language, orderby='addtime')

    def get_most_populars(self, language=None):
        return self.get_manga_list(language=language, orderby='views')

    def search(self, term, language=None):
        return self.get_manga_list(term=term, language=language)
