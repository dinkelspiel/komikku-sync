# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import time

import requests

from komikku.consts import DOWNLOAD_MAX_DELAY
from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import get_response_elapsed
from komikku.utils import is_number

SEARCH_RESULTS_PAGES = 2
SEARCH_RESULTS_PAGE_LIMIT = 98


class Weebdex(Server):
    id = 'weebdex'
    name = 'WeebDex'
    lang = 'en'
    lang_code = 'en'

    is_nsfw = True

    base_url = 'https://weebdex.org'
    logo_url = base_url + '/favicon.ico'

    manga_url = base_url + '/title/{0}'
    chapter_url = base_url + '/chapter/{0}'
    cover_url = base_url + '/covers/{0}/{1}.256.webp'

    api_url = 'https://api.weebdex.org'
    api_search_url = api_url + '/manga'
    api_manga_url = api_url + '/manga/{0}'
    api_chapters_url = api_url + '/manga/{0}/chapters'
    api_chapter_url = api_url + '/chapter/{0}'

    filters = [
        {
            'key': 'ratings',
            'type': 'select',
            'name': _('Rating'),
            'description': _('Filter by Content Ratings'),
            'value_type': 'multiple',
            'options': [
                {'key': 'safe', 'name': _('Safe'), 'default': True},
                {'key': 'suggestive', 'name': _('Suggestive'), 'default': True},
                {'key': 'erotica', 'name': _('Erotica'), 'default': False},
                {'key': 'pornographic', 'name': _('Pornographic'), 'default': False},
            ]
        },
        {
            'key': 'statuses',
            'type': 'select',
            'name': _('Status'),
            'description': _('Filter by Statuses'),
            'value_type': 'multiple',
            'options': [
                {'key': 'ongoing', 'name': _('Ongoing'), 'default': False},
                {'key': 'complete', 'name': _('Completed'), 'default': False},
                {'key': 'hiatus', 'name': _('Hiatus'), 'default': False},
                {'key': 'cancelled', 'name': _('Canceled'), 'default': False},
            ]
        },
        {
            'key': 'demographics',
            'type': 'select',
            'name': _('Demographic'),
            'description': _('Filter by Publication Demographics'),
            'value_type': 'multiple',
            'options': [
                {'key': 'shounen', 'name': _('Shounen'), 'default': False},
                {'key': 'shoujo', 'name': _('Shoujo'), 'default': False},
                {'key': 'josei', 'name': _('Josei'), 'default': False},
                {'key': 'seinen', 'name': _('Seinen'), 'default': False},
            ]
        },
    ]

    headers = {
        'User-Agent': USER_AGENT,
    }

    long_strip_genres = [
        'Long Strip',
    ]

    params = [
        {
            'key': 'data_saver',
            'type': 'checkbox',
            'name': _('Data Saver Mode'),
            'description': _('Fetch lower quality images to save bandwidth'),
            'default': False,
        },
    ]

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers = self.headers

    def get_manga_data(self, initial_data):
        """
        Returns manga data from API

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(self.api_manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        resp_data = r.json()

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

        data['name'] = resp_data['title']
        if cover := resp_data['relationships'].get('cover'):
            data['cover'] = self.cover_url.format(resp_data['id'], cover['id'])

        # Details
        if resp_data['status'] == 'completed':
            data['status'] = 'complete'
        elif resp_data['status'] == 'ongoing':
            data['status'] = 'ongoing'
        elif resp_data['status'] == 'hiatus':
            data['status'] = 'hiatus'
        elif resp_data['status'] == 'cancelled':
            data['status'] = 'suspended'

        if tags := resp_data['relationships'].get('tags'):
            for tag in tags:
                data['genres'].append(tag['name'])

        if rating := resp_data.get('content_rating'):
            if rating != 'safe':
                data['genres'].append(rating.capitalize())

        if demographic := resp_data.get('demographic'):
            data['genres'].append(demographic.capitalize())

        if authors := resp_data['relationships'].get('authors'):
            for author in authors:
                data['authors'].append(author['name'])

        if artists := resp_data['relationships'].get('artists'):
            for artist in artists:
                if artist['name'] in data['authors']:
                    continue
                data['authors'].append(artist['name'])

        if groups := resp_data['relationships'].get('available_groups'):
            for group in groups:
                data['scanlators'].append(group['name'])

        if synopsis := resp_data.get('description'):
            data['synopsis'] = synopsis

        # Chapters
        data['chapters'] = self.get_manga_chapters_data(data['slug'])

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data from API

        Currently, only pages are expected.
        """
        r = self.session_get(
            self.api_chapter_url.format(chapter_slug),
            headers={
                'Referer': self.chapter_url.format(chapter_slug),
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()

        data_saver = self.get_param('data_saver')
        if data_saver and resp_data.get('data_optimized'):
            pages = resp_data['data_optimized']
        else:
            pages = resp_data['data']

        data = dict(
            pages=[],
        )
        node_url = resp_data['node']
        for index, page in enumerate(pages, start=1):
            data['pages'].append(dict(
                slug=None,
                image=f'{node_url}/data/{chapter_slug}/{page["name"]}',
                index=index,
            ))

        return data

    def get_manga_chapters_data(self, slug, page=1, chapters=None):
        if chapters is None:
            chapters = []

        r = self.session_get(
            self.api_chapters_url.format(slug),
            params={
                'tlang': self.lang_code,
                'page': page,
                'limit': 250,
            },
            headers={
                'Referer': self.manga_url.format(slug),
            }
        )
        if r.status_code != 200:
            return None

        rtime = get_response_elapsed(r)
        resp_data = r.json()

        if resp_data['total'] == 0:
            return chapters

        for chapter in resp_data['data']:
            title = []
            if num_volume := chapter.get('volume'):
                title.append(f'Vol. {num_volume}')
            if num := chapter.get('chapter'):
                title.append(f'Ch. {num}')
            if chapter.get('title'):
                title.append(chapter['title'])

            groups = chapter['relationships'].get('groups')

            chapters.append(dict(
                slug=chapter['id'],
                title=' '.join(title),
                num=num if is_number(num) else None,
                num_volume=num_volume if is_number(num_volume) else None,
                scanlators=[group['name'] for group in groups] if groups else None,
                date=convert_date_string(chapter['published_at'].split('T')[0], '%Y-%m-%d'),
            ))

        if page * 250 < resp_data['total']:
            if rtime:
                time.sleep(min(rtime * 4, DOWNLOAD_MAX_DELAY))

            self.get_manga_chapters_data(slug, page=page+1, chapters=chapters)

        return list(reversed(chapters))

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
            name='{0:03d}.{1}'.format(page['index'], mime_type.split('/')[-1]),
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_manga_list(self, term=None, demographics=None, ratings=None, statuses=None, orderby=None):
        def get_page(page):
            params = {
                'hasChapters': 'true',
                'availableTranslatedLang': [self.lang_code],
                'limit': SEARCH_RESULTS_PAGE_LIMIT,
            }
            if term:
                params['title'] = term

            if demographics:
                params['demographic'] = demographics
            if ratings:
                params['contentRating'] = ratings
            if statuses:
                params['status'] = statuses

            if orderby == 'popular':
                params['sort'] = 'views'
            elif term:
                params['sort'] = 'relevance'

            r = self.session_get(
                self.api_search_url,
                params=params,
                headers={
                    'Referer': f'{self.base_url}/',
                }
            )
            if r.status_code != 200:
                return [], False, None

            resp_data = r.json()

            more = page * SEARCH_RESULTS_PAGE_LIMIT < resp_data['total'] and page < SEARCH_RESULTS_PAGES

            return resp_data.get('data', []), more, get_response_elapsed(r)

        results = []
        delay = None
        more = True
        page = 1
        while more:
            if delay:
                time.sleep(delay)

            items, more, rtime = get_page(page)
            for item in items:
                cover = item['relationships'].get('cover')

                results.append(dict(
                    slug=item['id'],
                    name=item['title'],
                    cover=self.cover_url.format(item['id'], cover['id']) if cover else None,
                    last_chapter=item.get('last_chapter'),
                ))

            delay = min(rtime * 4, DOWNLOAD_MAX_DELAY) if rtime else None
            page += 1

        return results

    def get_latest_updates(self, demographics=None, ratings=None, statuses=None):
        return self.get_manga_list(demographics=demographics, ratings=ratings, statuses=statuses, orderby='latest')

    def get_most_populars(self, demographics=None, ratings=None, statuses=None):
        return self.get_manga_list(demographics=demographics, ratings=ratings, statuses=statuses, orderby='popular')

    def search(self, term, demographics=None, ratings=None, statuses=None):
        return self.get_manga_list(term=term, demographics=demographics, ratings=ratings, statuses=statuses)
