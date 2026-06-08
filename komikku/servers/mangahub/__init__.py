# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: ISO-morphism <me@iso-morphism.name>

from functools import wraps
import logging

from bs4 import BeautifulSoup
try:
    # This server requires JA3/TLS and HTTP2 fingerprints impersonation
    from curl_cffi import requests
except Exception:
    # Server will be disabled
    requests = None

from komikku.consts import REQUESTS_TIMEOUT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number

logger = logging.getLogger('komikku.servers.mangahub')


def get_api_key(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        server = args[0]
        if not server.api_key:
            server.session_get(server.base_url)
            for name, value in server.session.cookies.items():
                if name == 'mhub_access':
                    server.api_key = value
                    break

        return func(*args, **kwargs)

    return wrapper


class Mangahub(Server):
    id = 'mangahub'
    name = 'MangaHub'
    lang = 'en'
    is_nsfw = True
    status = 'enabled' if requests is not None else 'disabled'

    http_client = 'curl_cffi'

    base_url = 'https://mangahub.io'
    logo_url = base_url + '/favicon-32x32.png'
    api_url = 'https://api.mghcdn.com/graphql'
    manga_url = base_url + '/manga/{0}'
    chapter_url = base_url + '/chapter/{0}/{1}'
    cover_url = 'https://thumb.mghcdn.com/{0}'

    long_strip_genres = ['Webtoon', 'Webtoons', 'LONG STRIP', 'LONG STRIP ROMANCE', ]

    def __init__(self):
        self.api_key = None

        if self.session is None and requests is not None:
            self.session = requests.Session(allow_redirects=True, impersonate='chrome', timeout=(REQUESTS_TIMEOUT, REQUESTS_TIMEOUT * 2))

    @get_api_key
    def get_manga_data(self, initial_data):
        """
        Returns manga data via GraphQL API.

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        query = {
            'query': '{latestPopular(x:m01){id,rank,title,slug,image,latestChapter,isLicensed,updatedDate}manga(x:m01,slug:"%s"){id,rank,title,slug,status,image,latestChapter,author,artist,genres,description,alternativeTitle,mainSlug,isYaoi,isPorn,isSoftPorn,isLicensed,noCoverAd,createdDate,updatedDate,chapters{id,number,title,slug,date}}}' % initial_data['slug']
        }
        r = self.session.post(
            self.api_url,
            json=query,
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Referer': self.base_url + '/',
                'Origin': self.base_url,
                'x-mhub-access': self.api_key,
            }
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
            cover=None,
        ))

        manga = r.json()['data']['manga']

        data['name'] = manga['title']
        data['cover'] = self.cover_url.format(manga['image'])

        # Details
        data['authors'] = [author.strip() for author in manga['author'].split(',')]
        for artist in manga['artist'].split(','):
            artist = artist.strip()
            if artist not in data['authors']:
                data['authors'].append(artist)

        data['genres'] = [genre.strip() for genre in manga['genres'].split(',')]

        if manga['status'] == 'ongoing':
            data['status'] = 'ongoing'
        elif manga['status'] == 'completed':
            data['status'] = 'complete'

        data['synopsis'] = manga['description']

        # Chapters
        for chapter in manga['chapters']:
            if chapter['title']:
                title = '#{0} - {1}'.format(chapter['number'], chapter['title'])
            else:
                title = '#{0}'.format(chapter['number'])

            data['chapters'].append(dict(
                slug='chapter-{}'.format(chapter['number']),
                title=title,
                num=chapter['number'] if is_number(chapter['number']) else None,
                date=convert_date_string(chapter['date'].split('T')[0], format='%Y-%m-%d'),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns chapter's data via GraphQL API

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )
        for element in soup.select('#mangareader img[loading="lazy"]'):
            data['pages'].append(dict(
                slug=None,
                image=element.get('src'),
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            page['image'],
            headers={
                'Accept': 'image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5',
                'Referer': f'{self.base_url}/',
                'Sec-Fetch-Dest': 'image',
                'Sec-Fetch-Mode': 'no-cors',
                'Sec-Fetch-Site': 'cross-site',
            },
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

    def get_latest_updates(self):
        """
        Returns latest manga
        """
        return self.search('', orderby='latest')

    def get_most_populars(self):
        """
        Returns popular manga
        """
        return self.search('', orderby='popular')

    @get_api_key
    def search(self, term, orderby=None):
        if orderby is not None:
            query = {
                'query': '{search(x:m01,mod:%s,count:true,offset:0){rows{id,rank,title,slug,status,author,genres,image,latestChapter,isLicensed,createdDate},count}}' % orderby.upper()
            }
        else:
            query = {
                'query': '{search(x:m01,q:"%s",limit:10){rows{id,title,slug,image,rank,latestChapter,createdDate}}}' % term
            }

        r = self.session_post(self.api_url, json=query, headers={
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Origin': self.base_url,
            'Referer': self.base_url + '/',
            'x-mhub-access': self.api_key,
        })
        if r.status_code != 200:
            return None

        results = []
        for row in r.json()['data']['search']['rows']:
            results.append(dict(
                slug=row['slug'],
                name=row['title'],
                cover=self.cover_url.format(row['image']),
                last_chapter=row['latestChapter'],
            ))

        return results
