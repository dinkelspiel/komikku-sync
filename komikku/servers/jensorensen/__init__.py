# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _

from bs4 import BeautifulSoup
import requests
import textwrap

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.servers.utils import TextImage
from komikku.utils import get_buffer_mime_type
from komikku.utils import html_escape
from komikku.utils import ServerContent


class Jensorensen(Server):
    id = 'jensorensen'
    name = 'Jen Sorensen'
    lang = 'en'
    content = ServerContent(
        type=[_('Webcomic'), _('Self-publishing')]
    )
    true_search = False

    base_url = 'https://jensorensen.com'
    donate_url = base_url + '/subscribe/'
    logo_url = base_url + '/wp-content/uploads/2019/04/jen-head-500px-32x32.png'
    chapters_url = base_url + '/wp-json/wp/v2/posts'
    chapter_url = base_url + '/{0}'
    cover_url = base_url + '/wp-content/uploads/2022/03/cropped-newbanner3.png'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Returns comic data by scraping comic HTML page content
        """
        r = self.session_get(self.base_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update(dict(
            authors=['Jen Sorensen'],
            scanlators=[],
            genres=['Humor', 'Satire', 'Politic'],
            status='ongoing',
            synopsis=soup.select_one('#text-2').text.strip(),
            chapters=[],
            server_id=self.id,
            cover=self.cover_url,
        ))

        # Chapters
        done = False
        page = 1
        while not done:
            params = {
                'page': page,
                'per_page': 100,
            }
            r = self.session_get(self.chapters_url, params=params)
            if r.status_code != 200:
                continue

            resp_json = r.json()

            for post in resp_json:
                if 7 not in post['categories']:
                    continue

                date = post['date'][:10]
                slug = post['link'].replace(f'{self.base_url}/', '')

                data['chapters'].append(dict(
                    slug=slug,
                    date=convert_date_string(date, '%Y-%m-%d'),
                    title=html_escape(post['title']['rendered']),
                ))

            if len(resp_json) == 100:
                page += 1
            else:
                done = True

        data['chapters'].reverse()

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

        if element := soup.select_one('.entry'):
            img_element = element.select_one('.js_featured img')
            return dict(
                pages=[
                    dict(
                        slug=None,
                        image=img_element.get('src'),
                    ),
                    dict(
                        slug=None,
                        image=None,
                        text=element.p.text.strip(),
                    ),
                ]
            )

        return None

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        if page.get('image'):
            r = self.session_get(page['image'])
            if r.status_code != 200:
                return None

            mime_type = get_buffer_mime_type(r.content)
            if not mime_type.startswith('image'):
                return None

            name = page['image'].split('/')[-1]
            content = r.content
        else:
            text = '\n'.join(textwrap.wrap(page['text'], 40))
            image = TextImage(text, font_size=48)

            mime_type = image.mime_type
            name = f'{chapter_slug.split("/")[-2]}-alt-text.{image.format}'
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
            slug='archives',
            name='Weekly Cartoon',
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
