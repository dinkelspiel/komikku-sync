# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

# Hean CMS / Iken

# Supported servers:
# Aurora Scans [EN] (disabled)
# EZmanga [EN]
# Hijala Scans [EN]
# Hive Toon [EN]
# Mode Scanlator [pt_BR] (disabled)
# Qi Scans [EN]
# Reaper Scans [EN] (disabled)
# Reaper Scans [pt_BR] (disabled)
# Rezo Scans [EN] (disabled)


import logging
import time

from bs4 import BeautifulSoup
import requests

from komikku.consts import DOWNLOAD_MAX_DELAY
from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.servers.utils import parse_nextjs_hydration
from komikku.utils import get_buffer_mime_type
from komikku.utils import get_response_elapsed
from komikku.webview import CompleteChallenge

logger = logging.getLogger('komikku.servers.multi.heancms')


class HeanCMS(Server):
    base_url: str
    api_url: str

    logo_url: str = None
    manga_url: str = None
    chapter_url: str = None
    api_manga_url: str = None
    api_chapters_url: str = None

    def __init__(self):
        if self.logo_url is None:
            self.logo_url = self.base_url + '/favicon.ico'
        if self.manga_url is None:
            self.manga_url = self.base_url + '/series/{0}'
        if self.chapter_url is None:
            self.chapter_url = self.base_url + '/series/{0}/{1}'
        if self.api_manga_url is None:
            self.api_manga_url = self.api_url + '/post?postSlug={0}'
        if self.api_chapters_url is None:
            self.api_chapters_url = self.api_url + '/chapters?postId={0}&skip={1}&take={2}&order=desc&search=&userId=undefined'

        if self.session is None and not self.has_cf:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    @CompleteChallenge()
    def get_manga_data(self, initial_data):
        """
        Returns manga data via API request

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        r = self.session_get(self.api_manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        resp_data = r.json()['post']

        data = initial_data.copy()
        data.update(dict(
            name=resp_data['postTitle'],
            authors=[],
            scanlators=[],
            genres=[],
            status='ongoing',
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=resp_data['featuredImage'],
        ))

        for genre in resp_data['genres']:
            data['genres'].append(genre['name'])

        if resp_data['seriesStatus'] == 'COMPLETED':
            data['status'] = 'complete'
        elif resp_data['seriesStatus'] == 'ONGOING':
            data['status'] = 'ongoing'
        elif resp_data['seriesStatus'] == 'DROPPED':
            data['status'] = 'suspended'
        elif resp_data['seriesStatus'] == 'HIATUS':
            data['status'] = 'hiatus'

        if resp_data.get('author'):
            for author in resp_data['author'].split(','):
                data['authors'].append(author.strip())
        if resp_data.get('artist'):
            for artist in resp_data['artist'].split(','):
                data['authors'].append(artist.strip())

        if synopsis := resp_data['postContent']:
            data['synopsis'] = BeautifulSoup(synopsis, 'lxml').text.strip()

        # Chapters
        data['chapters'] = self.get_manga_chapters_data(resp_data['id'])

        return data

    @CompleteChallenge()
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Pages URLs are available in a <script> element
        """
        r = self.session_get(
            self.chapter_url.format(manga_slug, chapter_slug),
            headers={
                'Referer': self.manga_url.format(manga_slug),
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        if images := parse_nextjs_hydration(soup, 'images', key='images'):
            data = dict(
                pages=[],
            )
            for image in images:
                data['pages'].append(dict(
                    slug=None,
                    image=image['url'],
                ))

            return data

        return None

    def get_manga_chapters_data(self, serie_id):
        """
        Returns manga chapters list via API
        """
        chapters = []

        def get_page(serie_id, page):
            r = self.session_get(
                self.api_chapters_url.format(serie_id, (page - 1) * 50, page * 50),
                headers={
                    'Referer': f'{self.base_url}/',
                }
            )
            if r.status_code != 200:
                return None, False, None

            data = r.json()
            if not data.get('post'):
                return None, False, None

            more = data['totalChapterCount'] > page * 50

            return data['post']['chapters'], more, get_response_elapsed(r)

        chapters = []
        delay = None
        more = True
        page = 1
        while more:
            if delay:
                time.sleep(delay)

            chapters_page, more, rtime = get_page(serie_id, page)
            if chapters_page:
                for chapter in chapters_page:
                    prefix = '🔒 ' if not chapter.get('isAccessible', True) else ''

                    chapters.append(dict(
                        slug=chapter['slug'],
                        title=f'{prefix}Chapter {chapter["number"]}',
                        num=chapter['number'],
                        date=convert_date_string(chapter['createdAt'].split('T')[0], '%Y-%m-%d') if 'createdAt' in chapter else None,
                    ))
                page += 1
                delay = min(rtime * 2, DOWNLOAD_MAX_DELAY) if rtime else None

            elif chapters_page is None:
                # Failed to retrieve a chapters list page, abort
                break

        return list(reversed(chapters))

    @CompleteChallenge()
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

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    @CompleteChallenge()
    def get_latest_updates(self):
        """
        Returns latest updates
        """
        return self.get_manga_list(orderby='latest')

    def get_manga_list(self, term=None, orderby=None):
        params = dict(
            page=1,
            perPage=21,
        )
        if term:
            params['searchTerm'] = term
        else:
            if orderby == 'latest':
                params['orderBy'] = 'updatedAt'
            elif orderby == 'popular':
                params['orderBy'] = 'totalViews'

        r = self.session_get(
            self.api_url + '/query',
            params=params,
            headers={
                'Accept': 'application/json, text/plain, */*',
                'Origin': self.base_url,
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        results = []
        for item in r.json()['posts']:
            cover = item['featuredImage']

            results.append(dict(
                slug=item['slug'],
                name=item['postTitle'],
                cover=cover,
                last_chapter=item['chapters'][0]['number'] if item.get('chapters') else None,
            ))

        return results

    @CompleteChallenge()
    def get_most_populars(self):
        """
        Returns most popular mangas
        """
        return self.get_manga_list(orderby='popular')

    @CompleteChallenge()
    def search(self, term):
        return self.get_manga_list(term=term)
