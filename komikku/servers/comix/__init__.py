# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import base64
import datetime
from gettext import gettext as _
import time
import urllib.parse

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

KEYS = {
    0: '13YDu67uDgFczo3DnuTIURqas4lfMEPADY6Jaeqky+w=',   # 0  RC4 key  round 1
    1: 'yEy7wBfBc+gsYPiQL/4Dfd0pIBZFzMwrtlRQGwMXy3Q=',   # 1  mut_key  round 1
    2: 'yrP+EVA1Dw==',                                   # 2  pref_key round 1
    3: 'vZ23RT7pbSlxwiygkHd1dhToIku8SNHPC6V36L4cnwM=',   # 3  RC4 key  round 2
    4: 'QX0sLahOByWLcWGnv6l98vQudWqdRI3DOXBdit9bxCE=',   # 4  mut_key  round 2
    5: 'WJwgqCmf',                                       # 5  pref_key round 2
    6: 'BkWI8feqSlDZKMq6awfzWlUypl88nz65KVRmpH0RWIc=',   # 6  RC4 key  round 3
    7: 'v7EIpiQQjd2BGuJzMbBA0qPWDSS+wTJRQ7uGzZ6rJKs=',   # 7  mut_key  round 3
    8: '1SUReYlCRA==',                                   # 8  pref_key round 3
    9: 'RougjiFHkSKs20DZ6BWXiWwQUGZXtseZIyQWKz5eG34=',   # 9  RC4 key  round 4
    10: 'LL97cwoDoG5cw8QmhI+KSWzfW+8VehIh+inTxnVJ2ps=',  # 10 mut_key  round 4
    11: '52iDqjzlqe8=',                                  # 11 pref_key round 4
    12: 'U9LRYFL2zXU4TtALIYDj+lCATRk/EJtH7/y7qYYNlh8=',  # 12 RC4 key  round 5
    13: 'e/GtffFDTvnw7LBRixAD+iGixjqTq9kIZ1m0Hj+s6fY=',  # 13 mut_key  round 5
    14: 'xb2XwHNB',                                      # 14 pref_key round 5
}


def generate_hash(path, body_size=0, time=1):
    """
    :param path: API path, e.g. '/manga/some-hash/chapters'
    :param body_size: encodeURIComponent(body) length for POST, or 0 for GET
    :param time: 1 for GET manga requests, `System.currentTimeMillis()` for POST
    """

    def get_key_bytes(index):
        b64 = KEYS.get(index)
        if not b64:
            return []

        key = []
        for c in base64.b64decode(b64):
            key.append(int(c) & 0xFF)

        return key

    def get_mut_key(mk, idx):
        if mk and (idx % 32) < len(mk):
            return mk[idx % 32]
        return 0

    def mut_s(e):
        return (e + 143) % 256

    def mut_l(e):
        return ((e >> 1) | (e << 7)) & 255

    def mut_c(e):
        return (e + 115) % 256

    def mut_m(e):
        return e ^ 177

    def mut_f(e):
        return (e - 188 + 256) % 256

    def mut_g(e):
        return ((e << 2) | (e >> 6)) & 255

    def mut_h(e):
        return (e - 42 + 256) % 256

    def mut_dollar(e):
        return ((e << 4) | (e >> 4)) & 255

    def mut_b(e):
        return (e - 12 + 256) % 256

    def mut_underscore(e):
        return (e - 20 + 256) % 256

    def mut_y(e):
        return ((e >> 1) | (e << 7)) & 255

    def mut_k(e):
        return (e - 241 + 256) % 256

    def RC4(key, data):
        if not key:
            return data
        s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + s[i] + key[i % len(key)]) % 256
            temp = s[i]
            s[i] = s[j]
            s[j] = temp

        i = 0
        j = 0
        out = [0] * len(data)
        for k in range(len(data)):
            i = (i + 1) % 256
            j = (j + s[i]) % 256
            temp = s[i]
            s[i] = s[j]
            s[j] = temp
            out[k] = data[k] ^ s[(s[i] + s[j]) % 256]

        return out

    def round1(data):
        enc = RC4(get_key_bytes(0), data)
        mut_key = get_key_bytes(1)
        pref_key = get_key_bytes(2)
        out = []

        for i, c in enumerate(enc):
            if i < 7 and i < len(pref_key):
                out.append(pref_key[i])

            v = c ^ get_mut_key(mut_key, i)
            if i % 10 in (0, 9):
                v = mut_c(v)
            elif i % 10 == 1:
                v = mut_b(v)
            elif i % 10 == 2:
                v = mut_y(v)
            elif i % 10 == 3:
                v = mut_dollar(v)
            elif i % 10 in (4, 6):
                v = mut_h(v)
            elif i % 10 == 5:
                v = mut_s(v)
            elif i % 10 == 7:
                v = mut_k(v)
            elif i % 10 == 8:
                v = mut_l(v)

            out.append(v & 255)

        return out

    def round2(data):
        enc = RC4(get_key_bytes(3), data)
        mut_key = get_key_bytes(4)
        pref_key = get_key_bytes(5)
        out = []

        for i, c in enumerate(enc):
            if i < 6 and i < len(pref_key):
                out.append(pref_key[i])

            v = c ^ get_mut_key(mut_key, i)
            if i % 10 in (0, 8):
                v = mut_c(v)
            elif i % 10 == 1:
                v = mut_b(v)
            elif i % 10 in (2, 6):
                v = mut_dollar(v)
            elif i % 10 == 3:
                v = mut_h(v)
            elif i % 10 in (4, 9):
                v = mut_s(v)
            elif i % 10 == 5:
                v = mut_k(v)
            elif i % 10 == 7:
                v = mut_underscore(v)

            out.append(v & 255)

        return out

    def round3(data):
        enc = RC4(get_key_bytes(6), data)
        mut_key = get_key_bytes(7)
        pref_key = get_key_bytes(8)
        out = []

        for i, c in enumerate(enc):
            if i < 7 and i < len(pref_key):
                out.append(pref_key[i])

            v = c ^ get_mut_key(mut_key, i)
            if i % 10 == 0:
                v = mut_c(v)
            elif i % 10 == 1:
                v = mut_f(v)
            elif i % 10 in (2, 8):
                v = mut_s(v)
            elif i % 10 == 3:
                v = mut_g(v)
            elif i % 10 == 4:
                v = mut_y(v)
            elif i % 10 == 5:
                v = mut_m(v)
            elif i % 10 == 6:
                v = mut_dollar(v)
            elif i % 10 == 7:
                v = mut_k(v)
            elif i % 10 == 9:
                v = mut_b(v)

            out.append(v & 255)

        return out

    def round4(data):
        enc = RC4(get_key_bytes(9), data)
        mut_key = get_key_bytes(10)
        pref_key = get_key_bytes(11)
        out = []

        for i, c in enumerate(enc):
            if i < 8 and i < len(pref_key):
                out.append(pref_key[i])

            v = c ^ get_mut_key(mut_key, i)
            if i % 10 == 0:
                v = mut_b(v)
            elif i % 10 in (1, 9):
                v = mut_m(v)
            elif i % 10 in (2, 7):
                v = mut_l(v)
            elif i % 10 in (3, 5):
                v = mut_s(v)
            elif i % 10 in (4, 6):
                v = mut_underscore(v)
            elif i % 10 == 8:
                v = mut_y(v)

            out.append(v & 255)

        return out

    def round5(data):
        enc = RC4(get_key_bytes(12), data)
        mut_key = get_key_bytes(13)
        pref_key = get_key_bytes(14)
        out = []

        for i, c in enumerate(enc):
            if i < 6 and i < len(pref_key):
                out.append(pref_key[i])

            v = c ^ get_mut_key(mut_key, i)
            if i % 10 == 0:
                v = mut_underscore(v)
            elif i % 10 in (1, 7):
                v = mut_s(v)
            elif i % 10 == 2:
                v = mut_c(v)
            elif i % 10 in (3, 5):
                v = mut_m(v)
            elif i % 10 == 4:
                v = mut_b(v)
            elif i % 10 == 6:
                v = mut_f(v)
            elif i % 10 == 8:
                v = mut_dollar(v)
            elif i % 10 == 9:
                v = mut_g(v)

            out.append(v & 255)

        return out

    base_str = f'{path}:{body_size}:{time}'  # noqa: E231
    encoded = urllib.parse.quote_plus(base_str).replace('+', '%20').replace('*', '%2A').replace('%7E', '~')

    initial_bytes = []
    for i in encoded.encode():
        initial_bytes.append(int(i) & 0xFF)

    r1 = round1(initial_bytes)
    r2 = round2(r1)
    r3 = round3(r2)
    r4 = round4(r3)
    r5 = round5(r4)

    final_bytes = []
    for c in r5:
        final_bytes.append(c.to_bytes(1))

    return base64.b64encode(b''.join(final_bytes), altchars=b'-_').replace(b'=', b'')


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
        path = f'/manga/{hash_id}/chapters'
        hash_token = generate_hash(path, 0, 1)

        def get_page(page):
            r = self.session_get(
                self.api_chapters_url.format(hash_id),
                params={
                    'order[number]': 'desc',
                    'limit': 100,
                    'time': 1,
                    'page': page,
                    '_': hash_token,
                },
                headers={
                    'Content-Type': 'application/json',
                    'Referer': self.manga_url.format(slug),
                }
            )
            if r.status_code != 200:
                return None, False, 0

            resp_data = r.json()
            if resp_data['status'] != 200:
                return None, False, 0

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
            if not items:
                return []
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
