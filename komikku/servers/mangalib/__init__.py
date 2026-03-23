# SPDX-FileCopyrightText: 2020-2024 GrownNed
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: GrownNed <grownned@gmail.com>
# Author: valos <vfebvre@easter-eggs.com>

import uuid

try:
    # For some reasons, under flatpak sandbox, HTTP requests return 403 errors!
    # Only solution found, use curl_cffi (JA3/TLS and HTTP2 fingerprints impersonation) in place of requests
    # What's wrong with sandbox?
    from curl_cffi import requests
except Exception:
    # Server will be disabled
    requests = None

from komikku.consts import REQUESTS_TIMEOUT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number


class Mangalib(Server):
    id = 'mangalib'
    name = 'MangaLIB'
    lang = 'ru'

    base_url = 'https://mangalib.org'
    logo_url = base_url + '/static/images/logo/ml/favicon.ico?529e41ba742f20a52986d0dea3e6ab1b'
    manga_url = base_url + '/ru/manga/{0}'
    api_base_url = 'https://api.cdnlibs.org/api'
    api_search_url = api_base_url + '/manga'
    api_manga_url = api_base_url + '/manga/{0}'
    api_chapters_url = api_base_url + '/manga/{0}/chapters'
    api_chapter_url = api_base_url + '/manga/{0}/chapter'
    image_base_url = 'https://img3.mixlib.me/'  # beware, an additional slash is required

    site_id = 1

    api_headers = {
        'Accept': '*/*',
        'Accept-Language': 'en-US;q=0.5,en;q=0.3',
        'Client-Time-Zone': 'Atlantic/Reykjavik',
        'Content-Type': 'application/json',
        'Referer': f'{base_url}/',
        'Site-Id': site_id,
    }

    def __init__(self):
        if self.session is None and requests is not None:
            self.session = requests.Session(
                allow_redirects=True,
                impersonate='chrome',
                timeout=(REQUESTS_TIMEOUT, REQUESTS_TIMEOUT * 2),
            )

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        params = {
            'fields[]': ['background', 'eng_name', 'otherNames', 'summary', 'releaseDate', 'type_id', 'caution', 'views', 'close_view', 'rate_avg', 'rate', 'genres', 'tags', 'teams', 'user', 'franchise', 'authors', 'publisher', 'userRating', 'moderated', 'metadata', 'metadata.count', 'metadata.close_comments', 'manga_status_id', 'chap_count', 'status_id', 'artists', 'format']
        }
        r = self.session_get(
            self.api_manga_url.format(initial_data['slug']),
            params=params,
            headers=self.api_headers
        )
        if r.status_code != 200:
            return None

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
        ))

        resp_data = r.json()['data']

        data['name'] = resp_data['rus_name']
        data['cover'] = resp_data['cover']['thumbnail']

        # Details
        for genre in resp_data['genres']:
            data['genres'].append(genre['name'])
        data['genres'].append(resp_data['type']['label'])

        for author in resp_data['authors']:
            data['authors'].append(author['name'])
        for artist in resp_data['artists']:
            author = artist['name']
            if author in data['authors']:
                continue
            data['authors'].append(author)

        for team in resp_data['teams']:
            data['scanlators'].append(team['name'])

        status = resp_data['status']['label']
        if status == 'Онгоинг':
            data['status'] = 'ongoing'
        elif status == 'Завершён':
            data['status'] = 'complete'
        elif status == 'Приостановлен':
            data['status'] = 'suspended'
        elif status == 'Выпуск прекращён':
            data['status'] = 'suspended'

        data['synopsis'] = resp_data['summary']

        # Chapters
        r = self.session_get(
            self.api_chapters_url.format(initial_data['slug']),
            headers=self.api_headers
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()['data']

        for chapter in resp_data:
            chapter_id = chapter['id']
            date = None
            scanlators = []
            for branch in chapter['branches']:
                if branch['id'] != chapter_id:
                    continue

                date = branch['created_at'][:10]
                for team in branch['teams']:
                    scanlators.append(team['name'])

            data['chapters'].append(dict(
                slug=f'v{chapter["volume"]}/c{chapter["number"]}',
                title=f'Том {chapter["volume"]} Глава {chapter["number"]} - {chapter["name"]}',
                num=chapter['number'] if is_number(chapter['number']) else None,
                num_volume=chapter['volume'] if is_number(chapter['volume']) else None,
                date=convert_date_string(date, format='%Y-%m-%d') if date else None,
                scanlators=scanlators if scanlators else None,
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        volume, number = chapter_slug.split('/')
        r = self.session_get(
            self.api_chapter_url.format(manga_slug),
            params={
                'number': number[1:],
                'volume': volume[1:],
            },
            headers=self.api_headers
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()['data']

        data = dict(
            pages=[],
        )
        for page in resp_data['pages']:
            data['pages'].append(dict(
                slug=None,
                image=page['url'][1:],
                index=page['slug'],
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            self.image_base_url + page['image'],
            headers={
                'Referer': f'{self.base_url}/'
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
            name='{0:03d}.{1}'.format(page['index'], mime_type.split('/')[-1]),
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_latest_updates(self):
        """
        Returns latest updates
        """
        return self.search('', orderby='latest')

    def get_most_populars(self):
        """
        Returns best noted manga list
        """
        return self.search('', orderby='populars')

    def search(self, term, orderby=None):
        params = {
            'fields[]': ['rate', 'rate_avg', 'userBookmark'],
            'seed': uuid.uuid1().hex,
            'site_id[]': self.site_id,
        }
        r = self.session_get(
            self.api_search_url,
            params=params,
            headers=self.api_headers,
        )
        seed = r.json()['meta']['seed']

        if orderby == 'latest':
            params.update({
                'sort_by': 'last_chapter_at',
                'seed': seed,
            })
        elif orderby == 'populars':
            params.update({
                'sort_by': 'views',
                'seed': seed,
            })
        else:
            params.update({
                'q': term,
                'seed': seed,
            })

        r = self.session_get(
            self.api_search_url,
            params=params,
            headers=self.api_headers,
        )
        if r.status_code != 200:
            return None

        results = []
        for item in r.json()['data']:
            results.append(dict(
                name=item['name'],
                slug=item['slug_url'],
                cover=item['cover']['thumbnail'],
            ))

        return results


# NSFW
class Hentailib(Mangalib):
    id = 'hentailib:mangalib'
    name = 'HentaiLIB'
    lang = 'ru'
    is_nsfw_only = True

    # Unfortunately, user authentication (via social networks) is required to get chapter data
    status = 'disabled'

    base_url = 'https://hentailib.me'
    manga_url = base_url + '/ru/manga/{0}'
    api_base_url = 'https://hapi.hentaicdn.org/api'
    api_search_url = api_base_url + '/manga'
    api_manga_url = api_base_url + '/manga/{0}'
    api_chapters_url = api_base_url + '/manga/{0}/chapters'
    api_chapter_url = api_base_url + '/manga/{0}/chapter'

    site_id = 4

    api_headers = {
        'Accept': '*/*',
        'Accept-Language': 'en-US;q=0.5,en;q=0.3',
        'Client-Time-Zone': 'Atlantic/Reykjavik',
        'Content-Type': 'application/json',
        'Referer': f'{base_url}/',
        'Site-Id': f'{site_id}',
    }
