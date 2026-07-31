# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import base64
import datetime
from gettext import gettext as _
import time
from urllib.parse import urlparse

import requests

from komikku.consts import DOWNLOAD_MAX_DELAY
from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.utils import get_buffer_mime_type
from komikku.utils import get_response_elapsed
from komikku.utils import is_number

LANGUAGES_CODES = {
    'en': 'en',
    'es': 'es',
    'es_419': 'es-la',
    'fr': 'fr',
    'ja': 'ja',
    'pt': 'pt',
    'pt_BR': 'pt-br',
}
SEARCH_RESULTS_PAGES = 3
SEARCH_RESULTS_PAGE_LIMIT = 30
CHAPTERS_PAGE_LIMIT = 100

VRF_STAGES = [
    {
        'table': base64.b64decode('yINlmUNho8VYJT+ibTIP+9ESiULpVEtMOoD6U6lRE0R/xwXo/Xp9NrUgC4cw/Lmo33vUyjUE40kUoEWIr/fxfNNcq2s79ShQ5NhNrFnJ4hXPwOu/SuXzIbuTQKGFvfm08E9jvCfqAtoDqvQq3dVWPQFmJjgvkISBeXY3BgANR+yVnjGbcxZ47d6kLNfZPIayTq3/YGySb1KuVZodWp/WGNAO5pfMcpaK53Hhs0allBszaMaxuouOwdxbwgxIw6YunSsXjI05Yi0j9j4eHKfSXR8Ifo/Od+8iamRfCXTyvm7NGRGYdcQ0ywcK/u6RXhrbcCm4t2eCtrDgQVecJGkQ+A=='),
        'key': base64.b64decode('0Ec58JOY3uBzJK9m3zqIOpdlF7UFiax9DmA='),
        'iv': 0x5A,
    },
    {
        'table': base64.b64decode('IUFltCxD3Oc2cwCgkJffthaOg9cgPUb0LgW6H/VtfcF0kc5F25t+aWj6JH9VOhOaY0rAFdUxlDnl5BLNvwEJvQtP5qcw7vdb/K+chnbwnspSHT8mz5lqwz41TezG0hkO06FTjJZhsyNuFLDpD2ZZxQj/QIRcF90zpmQ7Byu483WsQqUE0C342HL+JXngRB6fRzxRyVTaKu83h7UYTJ0QMt6ixFh6S3F8gqkKwrGTL3jHNBsD45UnifK8+RGtishQV2K3rujLKEkiZxpr2dYcudFW4oFsDKhad3CLBvuyTqsCo4B7mL5IKQ1vXo/MOOvq1I1d8ar9X6Ttu5KF4fZgiA=='),
        'key': base64.b64decode('AAdjb1iPY8CiDmq9H34tKTBF8a3oDQ=='),
        'iv': 0x35,
    },
    {
        'table': base64.b64decode('NQHlu1/wVO5EmkwQymF810qqY2xG1k2obcas4Z9mCsPEIFl9pRIjFxbJ7ybMHbBckT5Ton85E0FOeHezbh/mjlEYpmpnlXOS8dgrqeq2KfxImTh1YK9y0PeMNhzA1OQzSY9brYOJq/l2QnE/hwOeZIhPixVSKIUlDb5vLcH6RWKxkIEMuP0bDwIqQ71AJJaEaMJL7A6YtyIwoRT+L5v4aZzodN/0+3nOGsfblFjgxSfPzVDjNFeNl5P26+kEC/8AHgdrpAbt3hHz3HrRN1Y6e+JHgF7ncFWnoF0y3THL1S71WgWGCa6KtSzTCCG58n68nTyj2T3Sshk7utqCtMi/ZQ=='),
        'key': base64.b64decode('DELOJgPsVaCcblDtTGMdHzM='),
        'iv': 0xBA,
    },
]


def convert_old_slug(slug):
    # Old format: slug.hid
    # New format: hid-slug
    if '.' in slug:
        slug, hid = slug.split('.')
        slug = f'{hid}:{slug}'

    return slug if ':' in slug else None


def compute_vrf(url, params):
    def encrypt_stage(data, table, key, iv):
        key_size = len(key)
        prev = iv

        out = b''
        for index, value in enumerate(data):
            prev = table[(value ^ key[index % key_size] ^ prev) & 0xFF] & 0xFF
            out += prev.to_bytes()

        return out

    new_params = []
    if params:
        params = dict(sorted(params.items()))
        for name in params.keys():
            if name.endswith('[]'):
                for index, value in enumerate(params[name]):
                    new_name = name.replace('[]', f'[{index}]')
                    new_params.append(f'{new_name}={value}')
            else:
                new_params.append(f'{name}={params[name]}')

    data = urlparse(url).path.replace('/api', '')
    if new_params:
        data += '?'
        data += '&'.join(new_params)

    data = data.encode()
    for stage in VRF_STAGES:
        data = encrypt_stage(data, stage['table'], stage['key'], stage['iv'])

    return base64.b64encode(data, altchars=b'-_').rstrip(b'=')


class Mangafire(Server):
    id = 'mangafire'
    name = 'MangaFire'
    lang = 'en'

    is_nsfw = True

    base_url = 'https://mangafire.to'
    logo_url = base_url + '/assets/mangafire/logo-sm.png'

    search_url = base_url + '/browse'
    manga_url = base_url + '/title/{0}'
    chapter_url = base_url + 'title/{0}/chapter/{1}'

    api_url = base_url + '/api'
    api_search_url = api_url + '/titles'
    api_manga_url = api_url + '/titles/{0}'  # hid
    api_chapters_url = api_url + '/titles/{0}/chapters'  # hid
    api_chapter_url = api_url + '/chapters/{0}'

    filters = [
        {
            'key': 'content_rating',
            'type': 'select',
            'name': _('Content Rating'),
            'description': _('Filter by Content Rating'),
            'value_type': 'multiple',
            'options': [
                {'key': 'safe', 'name': _('Safe'), 'default': True},
                {'key': 'suggestive', 'name': _('Suggestive'), 'default': True},
                {'key': 'erotica', 'name': _('Erotica'), 'default': False},
                {'key': 'pornographic', 'name': _('Pornographic'), 'default': False},
            ]
        },
        {
            'key': 'types',
            'type': 'select',
            'name': _('Types'),
            'description': _('Filter by Types'),
            'value_type': 'multiple',
            'options': [
                {'key': 'manga', 'name': _('Manga'), 'default': False},
                {'key': 'manhwa', 'name': _('Manhwa'), 'default': False},
                {'key': 'manhua', 'name': _('Manhua'), 'default': False},
                {'key': 'other', 'name': _('Other'), 'default': False},
            ]
        },
        {
            'key': 'demographics',
            'type': 'select',
            'name': _('Demographics'),
            'description': _('Filter by Publication Demographics'),
            'value_type': 'multiple',
            'options': [
                {'key': 'josei', 'name': _('Josei'), 'default': False},
                {'key': 'seinen', 'name': _('Seinen'), 'default': False},
                {'key': 'shoujo', 'name': _('Shoujo'), 'default': False},
                {'key': 'shounen', 'name': _('Shounen'), 'default': False},
            ]
        },
        {
            'key': 'statuses',
            'type': 'select',
            'name': _('Statuses'),
            'description': _('Filter by Statuses'),
            'value_type': 'multiple',
            'options': [
                {'key': 'releasing', 'name': _('Ongoing'), 'default': False},
                {'key': 'finished', 'name': _('Completed'), 'default': False},
                {'key': 'on_hiatus', 'name': _('Hiatus'), 'default': False},
                {'key': 'discontinued', 'name': _('Canceled'), 'default': False},
            ]
        },
    ]

    headers = {
        'User-Agent': USER_AGENT,
    }

    long_strip_genres = [
        'manhwa',
    ]

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers = self.headers

    def get_manga_data(self, initial_data):
        """
        Returns manga data using API

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        if ':' not in initial_data['slug']:
            if slug := convert_old_slug(initial_data['slug']):
                initial_data['slug'] = slug
            else:
                # Invalid/obsolete slug
                return None

        hid, slug = initial_data['slug'].split(':')
        url = self.api_manga_url.format(hid)

        r = self.session_get(
            url,
            params={
                'vrf': compute_vrf(url, None),
            },
            headers={
                'Accept': 'application/json',
                'Referer': self.get_manga_url(initial_data['slug'], None),
                'X-Requested-With': 'XMLHttpRequest',
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()['data']

        data = initial_data.copy()
        data.update({
            'name': resp_data['title'],
            'authors': [],
            'scanlators': [],  # not available?
            'genres': [],
            'status': None,
            'synopsis': None,
            'chapters': [],
            'server_id': self.id,
            'cover': None,
        })

        if resp_data.get('poster') and resp_data['poster'].get('medium'):
            data['cover'] = resp_data['poster']['medium']

        for author in resp_data.get('authors', []):
            data['authors'].append(author['title'])
        for artist in resp_data.get('artists', []):
            artist = artist['title']
            if artist not in data['authors']:
                data['authors'].append(artist.strip())

        if resp_data['status'] == 'releasing':
            data['status'] = 'ongoing'
        elif resp_data['status'] == 'finished':
            data['status'] = 'complete'
        elif resp_data['status'] == 'on_hiatus':
            data['status'] = 'hiatus'
        elif resp_data['status'] == 'discontinued':
            data['status'] = 'suspended'

        for genre in resp_data.get('genres', []):
            data['genres'].append(genre['title'])
        for demographic in resp_data.get('demographics', []):
            data['genres'].append(demographic['title'])
        if type_ := resp_data.get('type'):
            data['genres'].append(type_)

        if synopsis := resp_data.get('synopsisHtml'):
            synopsis = synopsis.replace('<br>', '')
            synopsis = synopsis.replace('target="_blank"', '')
            synopsis = synopsis.replace('rel="noopener noreferrer"', '')
            data['synopsis'] = synopsis.strip()

        data['chapters'] = self.get_manga_chapters_data(data['slug'])

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns chapter data using API

        Currently, only pages are expected.
        """
        url = self.api_chapter_url.format(chapter_slug)

        r = self.session_get(
            url,
            params={
                'vrf': compute_vrf(url, None),
            },
            headers={
                'Accept': 'application/json',
                'Referer': self.chapter_url.format(manga_slug.replace(':', '-'), chapter_slug),
                'X-Requested-With': 'XMLHttpRequest',
            }
        )
        if r.status_code != 200:
            return None

        data = {
            'pages': [],
        }
        for index, page in enumerate(r.json()['data']['pages'], start=1):
            data['pages'].append({
                'slug': None,
                'image': page['url'],
                'index': index,
            })

        return data

    def get_manga_chapters_data(self, slug, page=1, chapters=None):
        if chapters is None:
            chapters = []

        hid, _slug = slug.split(':')
        url = self.api_chapters_url.format(hid)
        params = {
            'language': LANGUAGES_CODES[self.lang],
            'order': 'desc',
            'page': page,
            'limit': CHAPTERS_PAGE_LIMIT,
        }
        params['vrf'] = compute_vrf(url, params)

        r = self.session_get(
            url,
            params=params,
            headers={
                'Accept': 'application/json',
                'Referer': self.get_manga_url(slug, None),
                'X-Requested-With': 'XMLHttpRequest',
            }
        )
        if r.status_code != 200:
            return None

        rtime = get_response_elapsed(r)
        resp_data = r.json()

        for chapter in resp_data['items']:
            title = []
            if num := chapter.get('number'):
                title.append(f'Ch. {num}')
            if name := chapter.get('name'):
                title.append(name)
            type_ = chapter.get('type')

            chapters.append({
                'slug': chapter['id'],
                'title': ' '.join(title),
                'scanlators': [type_] if type_ else None,
                'num': num if is_number(num) else None,
                'date': datetime.datetime.fromtimestamp(chapter['createdAt']).date(),
            })

        if resp_data['meta']['hasNext']:
            if rtime:
                time.sleep(min(rtime * 4, DOWNLOAD_MAX_DELAY))

            self.get_manga_chapters_data(slug, page=page + 1, chapters=chapters)

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

        return {
            'buffer': r.content,
            'mime_type': mime_type,
            'name': '{0:03d}.{1}'.format(page['index'], mime_type.split('/')[-1]),
        }

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        slug = slug.replace(':', '-')
        return self.manga_url.format(slug)

    def get_manga_list(self, term=None, content_rating=None, types=None, demographics=None, statuses=None, orderby=None):
        def get_page(page):
            params = {}
            if term:
                params['keyword'] = term

            if content_rating:
                params['content_rating[]'] = content_rating
            if types:
                params['types[]'] = types
            if demographics:
                params['demographics[]'] = demographics
            if statuses:
                params['statuses[]'] = statuses

            if orderby == 'popular':
                params['order[trending]'] = 'desc'
            elif orderby == 'latest':
                params['order[chapter_updated_at]'] = 'desc'
            else:
                params['order[relevance]'] = 'desc'

            params.update({
                'page': page,
                'limit': SEARCH_RESULTS_PAGE_LIMIT,
            })

            params['vrf'] = compute_vrf(self.api_search_url, params)

            r = self.session_get(
                self.api_search_url,
                params=params,
                headers={
                    'Accept': 'application/json',
                    'Referer': f'{self.base_url}/',
                    'X-Requested-With': 'XMLHttpRequest',
                }
            )
            if r.status_code != 200:
                return [], False, None

            resp_data = r.json()

            more = resp_data['meta']['hasNext'] and page < SEARCH_RESULTS_PAGES

            return resp_data['items'], more, get_response_elapsed(r)

        results = []
        delay = None
        more = True
        page = 1
        while more:
            if delay:
                time.sleep(delay)

            items, more, rtime = get_page(page)
            for item in items:
                results.append({
                    'slug': f'{item["hid"]}:{item["slug"]}',  # noqa
                    'name': item['title'],
                    'cover': item['poster']['medium'],
                    'last_chapter': item.get('latestChapter'),
                })

            delay = min(rtime * 4, DOWNLOAD_MAX_DELAY) if rtime else None
            page += 1

        return results

    def get_latest_updates(self, content_rating=None, types=None, demographics=None, statuses=None):
        return self.get_manga_list(
            content_rating=content_rating, types=types, demographics=demographics, statuses=statuses, orderby='latest'
        )

    def get_most_populars(self, content_rating=None, types=None, demographics=None, statuses=None):
        return self.get_manga_list(
            content_rating=content_rating, types=types, demographics=demographics, statuses=statuses, orderby='popular'
        )

    def search(self, term, content_rating=None, types=None, demographics=None, statuses=None):
        return self.get_manga_list(
            term=term, content_rating=content_rating, types=types, demographics=demographics, statuses=statuses
        )


class Mangafire_es(Mangafire):
    id = 'mangafire_es'
    name = 'MangaFire'
    lang = 'es'


class Mangafire_es_419(Mangafire):
    id = 'mangafire_es_419'
    name = 'MangaFire'
    lang = 'es_419'


class Mangafire_fr(Mangafire):
    id = 'mangafire_fr'
    name = 'MangaFire'
    lang = 'fr'


class Mangafire_ja(Mangafire):
    id = 'mangafire_ja'
    name = 'MangaFire'
    lang = 'ja'


class Mangafire_pt(Mangafire):
    id = 'mangafire_pt'
    name = 'MangaFire'
    lang = 'pt'


class Mangafire_pt_br(Mangafire):
    id = 'mangafire_pt_br'
    name = 'MangaFire'
    lang = 'pt_BR'
