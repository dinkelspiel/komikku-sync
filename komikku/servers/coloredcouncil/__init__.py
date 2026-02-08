# SPDX-FileCopyrightText: 2021-2024 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import base64
from gettext import gettext as _
import logging

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.servers.utils import parse_nextjs_hydration
from komikku.utils import get_buffer_mime_type

logger = logging.getLogger(__name__)


class Coloredcouncil(Server):
    id = 'coloredcouncil'
    name = 'Colored Manga'
    lang = 'en'
    status = 'disabled'

    base_url = 'https://coloredmanga.net'
    search_url = base_url + '/manga'
    manga_url = base_url + '/manga/{0}'
    chapter_url = base_url + '/manga/{0}/{1}'
    image_url = base_url + '/api/dynamicImages'

    filters = [
        {
            'key': 'format',
            'type': 'select',
            'name': _('Format'),
            'description': _('Filter by format'),
            'value_type': 'single',
            'default': 'all',
            'options': [
                {'key': 'all', 'name': _('All')},
                {'key': 'Manwha', 'name': _('Manhwa')},
                {'key': 'Manga', 'name': _('Manga')},
            ],
        },
        {
            'key': 'version',
            'type': 'select',
            'name': _('Version'),
            'description': _('Filter by version'),
            'value_type': 'single',
            'default': 'all',
            'options': [
                {'key': 'all', 'name': _('All')},
                {'key': 'Color', 'name': _('Color')},
                {'key': 'B/W', 'name': _('B/W')},
            ],
        },
    ]

    manga_list = None

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

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

        if info := parse_nextjs_hydration(soup, 'totalImage'):
            info = info[3]['data']
        else:
            logger.error('Failed to retrieve manga data')
            return None

        initial_data.pop('date', None)
        initial_data.pop('totalViews', None)

        data = initial_data.copy()
        data.update(dict(
            name=info['name'],
            authors=[],
            scanlators=[],
            genres=info['tags'],
            status=None,
            synopsis=info['synopsis'],
            chapters=[],
            server_id=self.id,
            cover=self.base_url + info['cover'],
        ))

        if info['author']:
            data['authors'].append(info['author'])
        if info['artist'] != info['author']:
            data['authors'].append(info['artist'])

        if info['status'] == 'Ongoing':
            data['status'] = 'ongoing'
        elif info['status'] == 'Completed':
            data['status'] = 'complete'
        elif info['status'] == 'Cancelled':
            data['status'] = 'suspended'
        elif info['status'] == 'Hiatus':
            data['status'] = 'hiatus'

        if volume := info.get('volume'):
            for volume in info['volume']:
                for chapter in volume['chapters']:
                    if volume.get('number'):
                        title = f'[{volume["number"]}] '
                        chapter_path = [volume['number']]
                    else:
                        title = ''
                        chapter_path = []

                    title = f'{title}{chapter["number"]}'
                    if chapter.get('title'):
                        title = f'{title} - {chapter["title"]}'
                        chapter_path.append(f'{chapter["number"]} - {chapter["title"]}')
                    else:
                        chapter_path.append(chapter['number'])

                    data['chapters'].append(dict(
                        slug=chapter['id'],
                        title=title,
                        num=chapter['number'],
                        num_volume=volume.get('number'),
                        date=convert_date_string(chapter['date'][:-7], format='%B %d, %Y'),
                        url='/'.join(chapter_path),  # relative path used to retrieve chapter images
                    ))
        else:
            for chapter in info['chapters']:
                title = f'{chapter["number"]} - {chapter["title"]}' if chapter['title'] else chapter['number']

                data['chapters'].append(dict(
                    slug=chapter['id'],
                    title=title,
                    date=convert_date_string(chapter['date'][:-7], format='%B %d, %Y'),
                    url=title,  # relative path used to retrieve chapter images
                ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content
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

        nb_pages = None
        for element in soup.select('h1'):
            text = element.text.strip()
            if text.startswith('1/'):
                nb_pages = int(text.split('/')[-1])
                break

        if nb_pages is None:
            logger.error('Failed to retrieve chapter number of pages')
            return None

        data = dict(
            pages=[],
        )
        for index in range(nb_pages):
            data['pages'].append(dict(
                index=index + 1,
                path=chapter_url,
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_put(
            self.image_url,
            data={
                'number': f'{page["index"] + 1:04d}',  # noqa
                'path': f'/images/content/{manga_name}/{page["path"]}',
            },
            headers={
                'Referer': self.chapter_url.format(manga_slug, chapter_slug),
                'Cache-Control': 'no-cache',
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()
        if not resp_data.get('image'):
            logger.error('Failed to retrieve image data')
            return None

        # {"image": "data:image/png;base64,..."}
        content = base64.b64decode(resp_data['image'].split('base64,')[-1])

        mime_type = get_buffer_mime_type(content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=content,
            mime_type=mime_type,
            name='{0:03d}.{1}'.format(page['index'], mime_type.split('/')[-1]),
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_latest_updates(self, format=None, version=None):
        """
        Returns latest updates
        """
        return self.search(format=format, version=version, orderby='latest')

    def get_most_populars(self, format=None, version=None):
        """
        Returns most popular mangas
        """
        return self.search(format=format, version=version, orderby='popular')

    def search(self, term=None, format=None, version=None, orderby=None):
        if self.manga_list is None:
            # Retrieve manga list if not already done
            r = self.session_get(self.search_url)
            if r.status_code != 200:
                return None

            mime_type = get_buffer_mime_type(r.content)
            if mime_type != 'text/html':
                return None

            soup = BeautifulSoup(r.text, 'lxml')
            if info := parse_nextjs_hydration(soup, 'totalImage'):
                try:
                    info = info[3]['children'][3]['data']
                except Exception:
                    logger.error('Failed to retrieve manga list')
                    return None

                self.manga_list = info
            else:
                logger.error('Failed to retrieve manga list')
                return None

        results = []
        for item in self.manga_list:
            if item['name'] == 'test':
                continue
            if term and term.lower() not in item['name'].lower():
                continue
            if format and format != 'all' and format != item['type']:
                continue
            if version and version != 'all' and version != item['version']:
                continue

            last_chapter_title = None
            if item.get('chapters'):
                last = item['chapters'][-1]
                last_chapter_title = f'{last["number"]} - {last["title"]}' if last['title'] else last['number']

            data = dict(
                slug=item['id'],
                name=item['name'],
                cover=self.base_url + item['cover'],
                last_chapter=last_chapter_title,
            )
            if orderby == 'latest':
                data['date'] = convert_date_string(item['date'][:-7], format='%B %d, %Y')
            elif orderby == 'popular':
                data['totalViews'] = item['totalViews']

            results.append(data)

        if orderby == 'latest':
            return sorted(results, key=lambda m: m['date'], reverse=True)
        elif orderby == 'popular':
            return sorted(results, key=lambda m: m['totalViews'], reverse=True)
        else:
            return sorted(results, key=lambda m: m['name'])
