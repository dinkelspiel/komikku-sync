# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import json
import time

from bs4 import BeautifulSoup
import requests

from komikku.consts import DOWNLOAD_MAX_DELAY
from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import get_response_elapsed

SEARCH_RESULTS_PAGES = 4
SEARCH_RESULTS_PAGE_LIMIT = 24


class Mangak(Server):
    id = 'mangak'
    name = 'MangaK'
    lang = 'en'

    is_nsfw = True

    base_url = 'https://mangak.io'
    logo_url = base_url + '/static/sites/mangak/icons/favicon-32x32.png'

    search_url = base_url + '/search'
    manga_url = base_url + '/{0}'
    chapter_url = base_url + '/{0}/{1}'

    api_url = 'https://api.mangak.io'
    api_search_url = api_url + '/titles/search'
    api_chapters_url = api_url + '/titles/{0}/chapters'

    filters = [
        {
            'key': 'content_rating',
            'type': 'select',
            'name': _('Content Rating'),
            'description': _('Filter by Content Rating'),
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': _('Any')},
                {'key': 'safe', 'name': _('Safe')},
                {'key': 'suggestive', 'name': _('Suggestive')},
                {'key': 'erotica', 'name': _('Erotica')},
                {'key': 'pornographic', 'name': _('Pornographic')},
            ]
        },
        {
            'key': 'type',
            'type': 'select',
            'name': _('Type'),
            'description': _('Filter by Type'),
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': _('Any')},
                {'key': 'manga', 'name': _('Manga')},
                {'key': 'manhwa', 'name': _('Manhwa')},
                {'key': 'manhua', 'name': _('Manhua')},
            ]
        },
        {
            'key': 'demographic',
            'type': 'select',
            'name': _('Demographic'),
            'description': _('Filter by Publication Demographic'),
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': _('Any')},
                {'key': 'shounen,seinen', 'name': _('Boy (Shounen + Seinen)')},
                {'key': 'shoujo,josei', 'name': _('Girl (Shoujo + Josei)')},
                {'key': 'shounen', 'name': _('Shounen')},
                {'key': 'shoujo', 'name': _('Shoujo')},
                {'key': 'seinen', 'name': _('Seinen')},
                {'key': 'josei', 'name': _('Josei')},
            ]
        },
        {
            'key': 'status',
            'type': 'select',
            'name': _('Status'),
            'description': _('Filter by Status'),
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': _('Any')},
                {'key': 'ongoing', 'name': _('Ongoing')},
                {'key': 'completed', 'name': _('Completed')},
                {'key': 'hiatus', 'name': _('Hiatus')},
                {'key': 'cancelled', 'name': _('Canceled')},
            ]
        },
    ]

    headers = {
        'User-Agent': USER_AGENT,
    }

    long_strip_genres = [
        'Webtoons',
    ]

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers = self.headers

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        id_, slug = initial_data['slug'].split(':')

        r = self.session_get(self.manga_url.format(slug))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        props = None
        if script_element := soup.select_one('script#__NEXT_DATA__'):
            script = script_element.string
            if script:
                props = json.loads(script)['props']['pageProps']['initialManga']

        if props is None:
            return None

        data = initial_data.copy()
        data.update(dict(
            name=props['name'],
            authors=[],
            scanlators=[],  # not available?
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=props.get('cover'),
        ))

        # Details
        if authors := props.get('authors'):
            for author in authors:
                data['authors'].append(author['name'])
        if artists := props.get('artists'):
            for artist in artists:
                artist = artist['name']
                if artist not in data['authors']:
                    data['authors'].append(artist)

        if props['status'] == 'Completed':
            data['status'] = 'complete'
        elif props['status'] == 'Ongoing':
            data['status'] = 'ongoing'
        elif props['status'] == 'Hiatus':
            data['status'] = 'hiatus'
        elif props['status'] == 'Cancelled':
            data['status'] = 'suspended'

        if genres := props.get('genres'):
            for genre in genres:
                data['genres'].append(genre['name'])
        if demographics := props.get('demographics'):
            for demographic in demographics:
                demographic = demographic['name']
                if demographic not in data['genres']:
                    data['genres'].append(demographic)
        if type_ := props.get('type'):
            type_ = type_['name']
            if type_ not in data['genres']:
                data['genres'].append(type_)
        if content_rating := props.get('contentRating'):
            data['genres'].append(content_rating)

        if synopsis := props.get('summary'):
            data['synopsis'] = synopsis

        # Chapters
        r = self.session_get(
            self.api_chapters_url.format(id_),
            params={
                'cv': int(time.time() * 1000),
            },
            headers={
                'Referer': self.manga_url.format(slug),
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()
        if not resp_data.get('success'):
            return None

        for chapter in reversed(resp_data['data']['chapters']):
            # `chapter_number` field can't be used, it's an internal sorting index
            data['chapters'].append({
                'slug': f'{chapter["id"]}:{chapter["slug"]}',  # noqa
                'title': chapter['name'],
                'scanlators': [chapter['group']] if chapter.get('group') else None,
                'date': convert_date_string(chapter['updated_at'].split('T')[0], format='%Y-%m-%d'),
            })

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns chapter data by scraping HTML page content

        Currently, only pages are expected.
        """
        _manga_id, manga_slug = manga_slug.split(':')
        chapter_id_, chapter_slug = chapter_slug.split(':')

        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        images = None
        if script_element := soup.select_one('script#__NEXT_DATA__'):
            script = script_element.string
            if script:
                images = json.loads(script)['props']['pageProps']['initialChapter']['images']

        if images is None:
            return None

        data = dict(
            pages=[],
        )
        for index, image in enumerate(images, start=1):
            data['pages'].append(dict(
                slug=None,
                image=image,
                index=index,
            ))

        return data

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

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name='{0:03d}.{1}'.format(page['index'], mime_type.split('/')[-1]),
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        _id, slug = slug.split(':')
        return self.manga_url.format(slug)

    def get_manga_list(self, term=None, content_rating=None, type=None, demographic=None, status=None, orderby=None):
        def get_page(page):
            params = {
                'limit': SEARCH_RESULTS_PAGE_LIMIT,
                'min_ch': 1,
                'page': page,
            }
            if term:
                params['q'] = term

            if content_rating:
                params['content_rating'] = content_rating
            if type:
                params['type'] = type
            if demographic:
                params['demographic'] = demographic
            if status:
                params['status'] = status

            if orderby == 'popular':
                params['sort'] = 'views'
            elif orderby == 'latest':
                params['sort'] = 'latest'

            r = self.session_get(
                self.api_search_url,
                params=params,
                headers={
                    'Referer': f'{self.search_url}',
                }
            )
            if r.status_code != 200:
                return [], False, None

            resp_data = r.json()
            if not resp_data.get('success'):
                return [], False, None

            more = resp_data['data']['pagination']['has_next'] and page < SEARCH_RESULTS_PAGES

            return resp_data['data']['items'], more, get_response_elapsed(r)

        results = []
        delay = None
        more = True
        page = 1
        while more:
            if delay:
                time.sleep(delay)

            items, more, rtime = get_page(page)
            for item in items:
                lastest_chapters = item.get('latest_chapters')

                results.append(dict(
                    slug=f'{item["id"]}:{item["slug"]}',  # noqa
                    name=item['name'],
                    cover=item['cover'],
                    last_chapter=lastest_chapters[0]['name'] if lastest_chapters else None,
                ))

            delay = min(rtime * 4, DOWNLOAD_MAX_DELAY) if rtime else None
            page += 1

        return results

    def get_latest_updates(self, content_rating=None, type=None, demographic=None, status=None):
        return self.get_manga_list(
            content_rating=content_rating, type=type, demographic=demographic, status=status, orderby='latest'
        )

    def get_most_populars(self, content_rating=None, type=None, demographic=None, status=None):
        return self.get_manga_list(
            content_rating=content_rating, type=type, demographic=demographic, status=status, orderby='popular'
        )

    def search(self, term, content_rating=None, type=None, demographic=None, status=None):
        return self.get_manga_list(
            term=term, content_rating=content_rating, type=type, demographic=demographic, status=status
        )
