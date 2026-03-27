# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

# Homepage: https://github.com/Suwayomi/Suwayomi-Server

import datetime
from gettext import gettext as _
import logging

from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth

from komikku.servers import Server
from komikku.servers.utils import do_login
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number

logger = logging.getLogger(__name__)

STATUSES = {
    'ONGOING': 'ongoing',
    'COMPLETED': 'complete',
    'PUBLISHING_FINISHED': 'complete',
    'CANCELLED': 'suspended',
    'ON_HIATUS': 'hiatus',
}


class Suwayomi(Server):
    id = 'suwayomi'
    name = 'Suwayomi'
    description = _('Manga reader server')
    lang = ''

    has_login = True
    sync = True

    base_url = None  # Customizable via the settings
    logo_url = 'https://raw.githubusercontent.com/Suwayomi/Suwayomi-Server/master/server/src/main/resources/icon/faviconlogo-128.png'

    headers = {
        'User-Agent': 'Komikku Suwayomi',
    }

    def __init__(self, username=None, password=None, address=None):
        if address:
            self.base_url = address

        if username and password:
            self.do_login(username, password)

    @property
    def api_base_url(self):
        return self.base_url + '/api/v1'

    @property
    def api_opds_base_url(self):
        return self.base_url + '/api/opds/v1.2'

    @property
    def api_graphql_url(self):
        return self.base_url + '/api/graphql'

    @property
    def api_chapters_url(self):
        return self.api_base_url + '/manga/{0}/chapters'

    @property
    def api_cover_url(self):
        return self.api_base_url + '/manga/{0}/thumbnail'

    @property
    def api_image_url(self):
        return self.api_base_url + '/manga/{0}/chapter/{1}/page/{2}'

    @property
    def api_manga_url(self):
        return self.api_base_url + '/manga/{0}'

    @property
    def api_search_url(self):
        return self.api_opds_base_url + '/mangas'

    @property
    def manga_url(self):
        return self.base_url + '/manga/{0}'

    @do_login
    def get_manga_data(self, initial_data):
        """
        Returns serie data using REST API

        Initial data should contain at least serie's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(self.api_manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        resp_data = r.json()

        data = initial_data.copy()
        data.update({
            'name': resp_data['title'].strip(),
            'authors': [],
            'scanlators': [],  # not available
            'genres': resp_data.get('genre'),
            'status': STATUSES.get(resp_data['status']),
            'synopsis': resp_data['description'].strip() if resp_data.get('description') else None,
            'chapters': [],
            'server_id': self.id,
            'cover': self.base_url + resp_data.get('thumbnailUrl'),
        })

        for key in ('author', 'artist'):
            if authors := resp_data.get(key):
                for author in authors.split(','):
                    author = author.strip()
                    if author not in data['authors']:
                        data['authors'].append(author)

        if last_fetched_at := resp_data.get('lastFetchedAt'):
            data['last_update'] = datetime.datetime.fromtimestamp(last_fetched_at, tz=datetime.UTC)

        # Chapters
        r = self.session_get(self.api_chapters_url.format(data['slug']))
        if r.status_code != 200:
            return None

        for chapter in reversed(r.json()):
            # Store Id and index in slug
            # Id is used to retrieve chapter data and reading sync
            # Index is used to retrieve page images
            slug = f'{chapter["id"]}:{chapter["index"]}'  # noqa

            chapter_data = {
                'slug': slug,
                'title': chapter['name'],
                'num': chapter['chapterNumber'] if is_number(chapter['chapterNumber']) else None,
                'read': 1 if chapter['read'] else 0,
                'scanlators': [chapter['scanlator']] if chapter.get('scanlator') else None,
            }

            if upload_date := chapter.get('uploadDate'):
                chapter_data['date'] = datetime.datetime.fromtimestamp(int(upload_date / 1000)).date()

            if last_read_at := chapter.get('lastReadAt'):
                chapter_data['last_read'] = datetime.datetime.fromtimestamp(last_read_at, tz=datetime.UTC)

                if data.get('last_read') is None or chapter_data['last_read'] > data['last_read']:
                    data['last_read'] = chapter_data['last_read']

            if last_page_read := chapter.get('lastPageRead'):
                chapter_data['last_page_read_index'] = last_page_read

            data['chapters'].append(chapter_data)

        return data

    @do_login
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns serie chapter data using GraphQL API

        Currently, only pages are expected.
        """
        id, _index = chapter_slug.split(':')

        r = self.session_post(
            self.api_graphql_url,
            json={
                'operationName': 'GET_CHAPTER_PAGES_FETCH',
                'variables': {
                    'input': {
                        'chapterId': int(id),
                    },
                },
                'query': """mutation GET_CHAPTER_PAGES_FETCH($input: FetchChapterPagesInput!) {
                    fetchChapterPages(input: $input) {
                        chapter {
                            id
                            pageCount
                            __typename
                        }
                        pages
                        __typename
                    }
                }""",
            }
        )
        if r.status_code != 200:
            return None

        data = {
            'pages': [],
        }
        for page in r.json()['data']['fetchChapterPages']['pages']:
            data['pages'].append({
                'slug': page.split('/')[-1],
                'image': None,
            })

        return data

    @do_login
    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        _id, index = chapter_slug.split(':')

        r = self.session_get(self.api_image_url.format(manga_slug, index, page['slug']))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return {
            'buffer': r.content,
            'mime_type': mime_type,
            'name': '{0:04d}.{1}'.format(int(page['slug']), mime_type.split('/')[-1]),
        }

    @do_login
    def get_manga_url(self, slug, url):
        """
        Returns serie absolute URL
        """
        return self.manga_url.format(slug)

    @do_login
    def get_most_populars(self):
        return self.search()

    def login(self, username, password):
        # Check authentication
        try:
            r = self.session.get(
                self.base_url,
                auth=HTTPBasicAuth(username, password)
            )
            if r.status_code != 200:
                return False

        except Exception as error:
            logger.warning(error)
            return False

        # Add credentials in session headers
        self.session.headers['Authorization'] = r.request.headers['Authorization']

        return True

    @do_login
    def search(self, term=None):
        """
        Searches series using OPDS API
        """
        def get_page_entries(page):
            params = {
                'pageNumber': page,
            }
            if term:
                params['query'] = term

            r = self.session_get(
                self.api_search_url,
                params=params
            )
            if r.status_code != 200:
                return None

            soup = BeautifulSoup(r.text, 'xml')

            return soup.select('entry'), soup.select_one('link[rel="next"]') is not None

        more = True
        page = 1
        results = []
        while more:
            entries, more = get_page_entries(page)
            if entries:
                for entry in entries:
                    slug = entry.id.text.strip().split(':')[-1]

                    results.append({
                        'name': entry.title.text.strip(),
                        'slug': slug,
                        'cover': self.api_cover_url.format(slug),
                    })
                page += 1

        return results

    @do_login
    def update_chapter_read_progress(self, data, manga_slug, manga_name, chapter_slug, chapter_url):
        id, _index = chapter_slug.split(':')

        r = self.session_post(
            self.api_graphql_url,
            json={
                'operationName': 'UPDATE_CHAPTERS',
                'variables': {
                    'input': {
                        'ids': [int(id)],
                        'patch': {
                            'lastPageRead': data['page'] - 1,
                        },
                    },
                    'getBookmarked': False,
                    'getRead': False,
                    'getLastPageRead': True,
                    'chapterIdsToDelete': [],
                    'deleteChapters': False,
                    'mangaId': -1,
                    'trackProgress': False,
                },
                'query': 'fragment TRACK_RECORD_BIND_FIELDS on TrackRecordType {\n  id\n  remoteId\n  trackerId\n  remoteUrl\n  title\n  status\n  lastChapterRead\n  totalChapters\n  score\n  displayScore\n  startDate\n  finishDate\n  private\n  __typename\n}\n\nmutation UPDATE_CHAPTERS($input: UpdateChaptersInput!, $getBookmarked: Boolean!, $getRead: Boolean!, $getLastPageRead: Boolean!, $chapterIdsToDelete: [Int!]!, $deleteChapters: Boolean!, $mangaId: Int!, $trackProgress: Boolean!) {\n  updateChapters(input: $input) {\n    chapters {\n      id\n      isBookmarked @include(if: $getBookmarked)\n      isRead @include(if: $getRead)\n      lastReadAt @include(if: $getRead)\n      lastPageRead @include(if: $getLastPageRead)\n      manga @include(if: $getRead) {\n        id\n        unreadCount\n        lastReadChapter {\n          id\n          __typename\n        }\n        latestReadChapter {\n          id\n          __typename\n        }\n        firstUnreadChapter {\n          id\n          __typename\n        }\n        __typename\n      }\n      manga @include(if: $getBookmarked) {\n        id\n        bookmarkCount\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  deleteDownloadedChapters(input: {ids: $chapterIdsToDelete}) @include(if: $deleteChapters) {\n    chapters {\n      id\n      isDownloaded\n      manga {\n        id\n        downloadCount\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  trackProgress(input: {mangaId: $mangaId}) @include(if: $trackProgress) {\n    trackRecords {\n      ...TRACK_RECORD_BIND_FIELDS\n      __typename\n    }\n    __typename\n  }\n}',
            }
        )

        return r.status_code == 200
