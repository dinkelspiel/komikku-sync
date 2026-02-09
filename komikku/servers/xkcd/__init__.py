# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import textwrap

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.servers.utils import TextImage
from komikku.utils import get_buffer_mime_type
from komikku.utils import ServerContent


class Xkcd(Server):
    id = 'xkcd'
    name = 'xkcd'
    lang = 'en'
    content = ServerContent(
        type=[_('Webcomic'), _('Self-publishing')],
        license='CC BY-NC 2.5'
    )
    true_search = False

    base_url = 'https://www.xkcd.com'
    logo_url = base_url + '/s/919f27.ico'
    manga_url = base_url + '/archive/'
    chapter_url = base_url + '/{0}/info.0.json'
    image_url = 'https://imgs.xkcd.com/comics/{0}'
    cover_url = base_url + '/s/0b7742.png'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'user-agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content
        """
        r = self.session_get(self.manga_url)
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update(dict(
            authors=['Randall Munroe', ],
            scanlators=[],
            genres=[],
            status='ongoing',
            synopsis='A webcomic of romance, sarcasm, math, and language.',
            chapters=[],
            server_id=self.id,
            cover=self.cover_url,
        ))

        # Chapters
        for a_element in reversed(soup.find('div', id='middleContainer').find_all('a')):
            slug = a_element.get('href')[1:-1]

            data['chapters'].append(dict(
                slug=slug,
                date=convert_date_string(a_element.get('title'), '%Y-%m-%d'),
                title='{0} - {1}'.format(slug, a_element.text.strip()),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(chapter_slug))
        if r.status_code != 200:
            return None

        try:
            data = r.json()
        except Exception:
            return None

        url_image = data['img']
        # The comic passed in HD after Chapter 1084
        if int(chapter_slug) >= 1084 and int(chapter_slug) not in (1097, 2042, 2202, ):
            url_image = url_image.replace('.png', '_2x.png')

        return dict(
            pages=[
                dict(
                    slug=None,
                    image=url_image.split('/')[-1],
                ),
                dict(
                    slug=None,
                    image=None,
                    text=data['alt'],
                )
            ]
        )

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        if page.get('image'):
            r = self.session_get(self.image_url.format(page['image']))
            if r.status_code != 200:
                return None

            mime_type = get_buffer_mime_type(r.content)
            if not mime_type.startswith('image'):
                return None

            name = page['image']
            content = r.content
        else:
            text = '\n'.join(textwrap.wrap(page['text'], 25))
            image = TextImage(text)

            mime_type = image.mime_type
            name = f'{chapter_slug}-alt-text.{image.format}'
            content = image.content

        return dict(
            buffer=content,
            mime_type=mime_type,
            name=name,
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url

    def get_most_populars(self):
        return [dict(
            slug='',
            name='xkcd',
            cover=self.cover_url,
        )]

    def search(self, term=None):
        # This server does not have a search
        # but a search method is needed for `Global Search` in `Explorer`
        # In order not to be offered in `Explorer`, class attribute `true_search` must be set to False

        results = []
        for item in self.get_most_populars():
            if term and term.lower() in item['name'].lower():
                results.append(item)

        return results
