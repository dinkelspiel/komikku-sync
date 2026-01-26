# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _

from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number
from komikku.webview import CompleteChallenge


class Phenixscans(Server):
    id = 'phenixscans'
    name = 'Phenix Scans'
    lang = 'fr'

    has_cf = True

    base_url = 'https://phenix-scans.co'
    logo_url = base_url + '/logo.png'
    api_base_url = 'https://api.phenix-scans.co/api'
    api_list_url = api_base_url + '/front/manga'
    api_search_url = api_base_url + '/front/manga/search'
    api_manga_url = api_base_url + '/front/manga/{0}'
    api_chapter_url = api_base_url + '/front/manga/{0}/chapter/{1}'
    manga_url = base_url + '/manga/{0}'
    media_url = 'https://api.phenix-scans.co' + '/{0}'

    filters = [
        {
            'key': 'type',
            'type': 'select',
            'name': _('Type'),
            'description': _('Filter by Type'),
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': _('All')},
                {'key': 'Manga', 'name': _('Manga')},
                {'key': 'Manhwa', 'name': _('Manhwa')},
                {'key': 'Manhua', 'name': _('Manhua')},
            ],
        },
    ]
    long_strip_genres = ['Manhua', 'Manhwa']

    def __init__(self):
        self.session = None

    @CompleteChallenge()
    def get_manga_data(self, initial_data):
        """
        Returns manga data using API

        Initial data should contain at least manga's slug (provided by search)
        """
        r = self.session_get(self.api_manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        resp_data = r.json()

        data = initial_data.copy()
        data.update(dict(
            name=resp_data['manga']['title'],
            authors=[],     # Not available
            scanlators=[],  # Not available
            genres=[genre['name'] for genre in resp_data['manga']['genres']],
            status=None,
            synopsis=resp_data['manga'].get('synopsis'),
            chapters=[],
            server_id=self.id,
            cover=self.media_url.format(resp_data['manga']['coverImage']),
        ))

        if resp_data['manga'].get('type'):
            data['genres'].append(resp_data['manga']['type'])

        if resp_data['manga']['status'] == 'Ongoing':
            data['status'] = 'ongoing'
        elif resp_data['manga']['status'] == 'Completed':
            data['status'] = 'complete'
        elif resp_data['manga']['status'] == 'Hiatus':
            data['status'] = 'hiatus'

        # Chapters
        for chapter in reversed(resp_data['chapters']):
            data['chapters'].append({
                'slug': chapter['number'],
                'title': f'Chapitre {chapter["number"]}',
                'num': chapter['number'] if is_number(chapter['number']) else None,
                'date': convert_date_string(chapter['createdAt'].split('T')[0], '%Y-%m-%d'),
            })

        return data

    @CompleteChallenge()
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        r = self.session_get(self.api_chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        resp_data = r.json()

        data = dict(
            pages=[],
        )
        for index, image in enumerate(resp_data['chapter']['images']):
            data['pages'].append({
                'slug': None,
                'image': image,
                'index': index + 1,
            })

        return data

    @CompleteChallenge()
    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            self.media_url.format(page['image']),
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

    def get_manga_list(self, orderby=None, type=None):
        params = {
            'page': 1,
            'limit': 18,
            'sort': orderby,
        }
        if type:
            params['type'] = type

        r = self.session_get(
            self.api_list_url,
            params=params
        )
        if r.status_code != 200:
            return None

        data = r.json()

        result = []
        for item in data['mangas']:
            result.append(dict(
                name=item['title'],
                slug=item['slug'],
                cover=self.media_url.format(item['coverImage']),
            ))

        return result

    @CompleteChallenge()
    def get_latest_updates(self, type=None):
        return self.get_manga_list(orderby='updatedAt', type=type)

    def get_manga_url(self, slug, url):
        return self.manga_url.format(slug)

    @CompleteChallenge()
    def get_most_populars(self, type=None):
        return self.get_manga_list(orderby='rating', type=type)

    @CompleteChallenge()
    def search(self, term, type=None):
        # Filtering by type is not available in search endpoint
        r = self.session_get(
            self.api_search_url,
            params={
                'query': term,
            }
        )
        if r.status_code != 200:
            return None

        data = r.json()

        result = []
        for item in data['mangas']:
            result.append(dict(
                name=item['title'],
                slug=item['slug'],
                cover=self.media_url.format(item['coverImage']),
            ))

        return result
