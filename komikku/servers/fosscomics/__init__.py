# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import html
import textwrap

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.servers.utils import TextImage
from komikku.utils import get_buffer_mime_type
from komikku.utils import ServerContent


class Fosscomics(Server):
    id = 'fosscomics'
    name = 'F/OSS Comics'
    lang = 'en'
    content = ServerContent(
        type=[_('Webcomic'), _('Self-publishing')]
    )
    true_search = False

    base_url = 'https://fosscomics.com'
    donate_url = 'https://github.com/sponsors/joone'
    logo_url = base_url + '/images/favicon.png'
    manga_url = base_url + '/all_posts/'
    chapter_url = base_url + '/{0}'
    image_url = base_url + '/{0}/images/{1}'
    cover_url = base_url + '/8.%20The%20Origins%20of%20Unix%20and%20the%20C%20Language/images/feature.png'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'user-agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Returns comic data by scraping manga HTML page content
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
            authors=['Joone Hur', ],
            scanlators=[],
            genres=[],
            status='ongoing',
            synopsis='Comics about Free and Open Source Software',
            chapters=[],
            server_id=self.id,
            cover=self.cover_url,
        ))

        # Chapters
        for element in reversed(soup.select('.posts .post')):
            slug = element.a.get('href').split('/')[-1]

            data['chapters'].append(dict(
                slug=slug,
                date=convert_date_string(element.span.text.strip(), '%a %b %d %Y'),
                title=element.a.text.strip(),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns comic chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(chapter_slug))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )
        i_index = 0  # images index
        p_index = 1  # paragraphs index
        for element in soup.select('section.body > p, section.body figure > img'):
            if element.name == 'p':
                # Text paragraph
                data['pages'].append(dict(
                    slug=None,
                    image=None,
                    text=html.unescape(element.text.strip()),
                    index=i_index,
                    subindex=p_index,
                ))
                p_index += 1
            else:
                # Image
                data['pages'].append(dict(
                    slug=None,
                    image=element.get('src').split('/')[-1],
                    index=i_index + 1,
                ))
                i_index += 1
                p_index = 1

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        chapter_num = int(chapter_slug.split('.')[0])

        if page.get('image'):
            r = self.session_get(self.image_url.format(chapter_slug, page['image']))
            if r.status_code != 200:
                return None

            mime_type = get_buffer_mime_type(r.content)
            if not mime_type.startswith('image'):
                return None

            name = f'{chapter_num:02d}_{page["index"]:02d}.{mime_type.split("/")[-1]}'  # noqa: E231
            content = r.content
        else:
            text = '\n'.join(textwrap.wrap(page['text'], 25))
            image = TextImage(text)

            mime_type = image.mime_type
            name = f'{chapter_num:02d}_{page["index"]:02d}_text_{page["subindex"]:02d}.{image.format}'  # noqa: E231
            content = image.content

        return dict(
            buffer=content,
            mime_type=mime_type,
            name=name,
        )

    def get_manga_url(self, slug, url):
        """
        Returns comic absolute URL
        """
        return self.base_url

    def get_most_populars(self):
        return [dict(
            slug='',
            name='F/OSS Comics',
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
