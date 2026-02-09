# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import textwrap

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import TextImage
from komikku.utils import get_buffer_mime_type
from komikku.utils import ServerContent


class Existentialcomics(Server):
    id = 'existentialcomics'
    name = 'Existential Comics'
    lang = 'en'
    content = ServerContent(
        type=[_('Webcomic'), _('Self-publishing')]
    )
    true_search = False

    base_url = 'https://existentialcomics.com'
    donate_url = base_url
    logo_url = 'https://static.existentialcomics.com/favicon.ico'
    manga_url = base_url + '/archive/byDate'
    chapter_url = base_url + '/comic/{0}'
    image_url = 'https://static.existentialcomics.com/comics/{0}'
    cover_url = 'https://i.ibb.co/pykMVYM/existential-comics.png'

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
            authors=['Corey Mohler', ],
            scanlators=[],
            genres=['Philosophy', 'Jokes'],
            status='ongoing',
            synopsis='A philosophy webcomic about the inevitable anguish of living a brief life in an absurd world. Also Jokes',
            chapters=[],
            server_id=self.id,
            cover=self.cover_url,
        ))

        # Chapters
        for a_element in soup.select('#date-comics ul li > a:first-child'):
            slug = a_element.get('href').split('/')[-1]

            data['chapters'].append(dict(
                slug=slug,
                title=a_element.text.strip(),
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

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        img_element = soup.select_one('.comicImg')

        return dict(
            pages=[
                dict(
                    slug=img_element.get('src').split('/')[-1],
                    image=None,
                ),
                dict(
                    slug=None,
                    image=None,
                    name=img_element.get('src').split('/')[-1].split('.')[0],
                    text=img_element.get('title'),
                )
            ]
        )

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        if page.get('slug'):
            r = self.session_get(self.image_url.format(page['slug']))
            if r.status_code != 200:
                return None

            mime_type = get_buffer_mime_type(r.content)
            if not mime_type.startswith('image'):
                return None

            name = page['slug']
            content = r.content
        else:
            text = '\n'.join(textwrap.wrap(page['text'], 25))
            image = TextImage(text)

            mime_type = image.mime_type
            name = f'{page["name"]}-alt-text.{image.format}'
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
        return self.base_url

    def get_most_populars(self):
        return [dict(
            slug='',
            name=self.name,
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
