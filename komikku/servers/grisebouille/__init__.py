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


class Grisebouille(Server):
    id = 'grisebouille'
    name = 'Grise Bouille'
    lang = 'fr'
    content = ServerContent(
        type=[_('Webcomic'), _('Self-publishing')],
        license='CC BY-SA'
    )
    true_search = False

    long_strip_genres = ['Long Strip', ]

    base_url = 'https://grisebouille.net'
    donate_url = 'https://soutenir.ptilouk.net/'
    logo_url = base_url + '/content/img/favicon-32x32.png'
    search_url = base_url + '/series/'
    manga_url = base_url + '/serie/{0}/'
    chapter_url = base_url + '/{0}/'
    cover_url = base_url + '/content/img/logo-{0}.png'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content
        """
        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update(dict(
            authors=['Gee', ],
            scanlators=[],
            genres=['Humour', 'Long Strip'],
            status='ongoing',
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=self.cover_url,
        ))

        data['name'] = soup.select_one('title').text.split('|')[0].strip().encode('iso-8859-1').decode()
        data['cover'] = self.cover_url.format(data['slug'])

        data['synopsis'] = soup.select_one('.main.block p').text.strip().encode('iso-8859-1').decode()

        # Chapters
        for a_element in reversed(soup.select('.episodes a')):
            slug = a_element.get('href').split('/')[-1]
            if data['slug'] == 'superflu' and not slug.startswith('s0'):
                continue

            title = a_element.select_one('.episode-name').text.strip().encode('iso-8859-1').decode()
            num = a_element.select_one('.episode-nb').text.strip()[1:-1]
            date = a_element.select_one('.episode-date').text.strip()

            data['chapters'].append(dict(
                slug=slug,
                title=f'#{num} {title}',
                date=convert_date_string(date, '%Y-%m-%d'),
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

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )
        for index, element in enumerate(soup.select('.main.block > p, .main.block :has(> img)')):
            if img_element := element.img:
                url = img_element.get('src')
                if not url.startswith(self.base_url):
                    continue

                data['pages'].append(dict(
                    slug=None,
                    image=url.encode('iso-8859-1').decode(),
                ))
            else:
                text = element.text.strip()
                try:
                    text = text.encode('iso-8859-1').decode()
                except Exception:
                    pass
                data['pages'].append(dict(
                    slug=None,
                    image=None,
                    text=text,
                    index=index + 1,
                ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page (image or text) content
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
            text = '\n'.join(textwrap.wrap(page['text'], 25))
            image = TextImage(text)

            mime_type = image.mime_type
            name = f'txt_{page["index"]:03d}.{image.format}'  # noqa: E231
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
        return self.manga_url.format(slug)

    def get_most_populars(self):
        r = self.session_get(self.search_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = []
        for a_element in soup.select('.series-link'):
            slug = a_element.get('href').split('/')[-1]
            if slug not in ('comic-trip', 'depeches-melba', 'la-chaine-meteore', 'la-fourche', 'superflu', 'tu-sais-quoi'):
                continue

            data.append(dict(
                slug=slug,
                name=a_element.img.get('alt').encode('iso-8859-1').decode(),
                cover=a_element.img.get('src'),
            ))

        return data

    def search(self, term=None):
        # This server does not have a search
        # but a search method is needed for `Global Search` in `Explorer`
        # In order not to be offered in `Explorer`, class attribute `true_search` must be set to False

        results = []
        for item in self.get_most_populars():
            if term and term.lower() in item['name'].lower():
                results.append(item)

        return results
