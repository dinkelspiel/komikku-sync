# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from urllib.parse import parse_qs
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number
from komikku.utils import ServerContent

# Conversion ISO_639-1 codes => server codes
LANGUAGES_CODES = {
    'de': 'de',
    'en': 'en',
    'es': 'es',
    'fr': 'fr',
    'it': 'it',
    'pt': 'pt',
    'ru': 'ru_RU',
}


class Dbmultiverse(Server):
    id = 'dbmultiverse'
    name = 'Dragon Ball Multiverse'
    lang = 'en'
    content = ServerContent(
        type='Doujins of Dragon Ball manga',
    )
    true_search = False

    base_url = 'https://www.dragonball-multiverse.com'
    logo_url = base_url + '/favicon.ico'
    manga_url = None
    chapter_url = None
    page_url = None
    cover_url = base_url + '/image.php?comic=page&num=0&lg=en&ext=jpg&small=1&pw=8f3722a594856af867d55c57f31ee103'

    synopsis = "Dragon Ball Multiverse (DBM) is a free online comic, made by a whole team of fans. It's our personal sequel to DBZ."

    def __init__(self):
        self.manga_url = self.base_url + f'/{LANGUAGES_CODES[self.lang]}/chapters.html?comic=page'
        self.chapter_url = self.base_url + f'/{LANGUAGES_CODES[self.lang]}/chapters.html?comic=page&chapter={{0}}'
        self.page_url = self.base_url + f'/{LANGUAGES_CODES[self.lang]}/page-{{0}}.html'

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
            authors=['Gogeta Jr', 'Asura', 'Salagir'],
            scanlators=[],
            genres=['Shōnen', 'Dōjinshi'],
            status='ongoing',
            synopsis=self.synopsis,
            chapters=[],
            server_id=self.id,
            cover=self.cover_url,
        ))

        # Chapters
        for element in soup.select('.chapter'):
            url = element.a.get('href')
            qs = parse_qs(urlparse(url).query)
            slug = qs['chapter'][0]

            chapter_data = dict(
                slug=slug,
                title=element.h4.text.strip(),
                num=slug if is_number(slug) else None,
                date=None,
                pages=[],
            )

            data['chapters'].append(chapter_data)

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

        data = dict(
            pages=[],
        )
        for element in soup.select('.pageslist > a > img'):
            data['pages'].append(dict(
                slug=element.get('title'),
                image=None,
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(self.page_url.format(page['slug']))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        if img_element := soup.select_one('#balloonsimg > img'):
            url = img_element.get('src')
            if not url:
                url = img_element.get('style').split(';')[0].split(':')[1][4:-1]
        elif div_element := soup.select_one('div#balloonsimg'):
            url = div_element.get('style').split('(')[1].split(')')[0]
        elif celebrate_element := soup.select_one('.cadrelect'):
            # Special page to celebrate 1000/2000/... pages
            # return first contribution image
            url = celebrate_element.select_one('img').get('src')
        else:
            return None

        r = self.session_get(self.base_url + url)
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name='{0}.png'.format(page['slug']),
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url

    def get_most_populars(self):
        return [dict(
            slug='dbm_{0}'.format(self.lang),
            name='Dragon Ball Multiverse (DBM)',
            cover=self.cover_url,
        )]

    def search(self, term=None):
        # This server does not have a true search
        # but a search method is needed for `Global Search` in `Explorer`
        # In order not to be offered in `Explorer`, class attribute `true_search` must be set to False

        results = []
        for item in self.get_most_populars():
            if term and term.lower() in item['name'].lower():
                results.append(item)

        return results


class Dbmultiverse_de(Dbmultiverse):
    id = 'dbmultiverse_de'
    lang = 'de'

    synopsis = 'Dragon Ball Multiverse ist ein kostenloser Online-Comic, gezeichnet von Fans, u. a. Gogeta Jr, Asura und Salagir. Es knüpft direkt an DBZ an als eine Art Fortsetzung. Veröffentlichung dreimal pro Woche: Mittwoch, Freitag und Sonntag um 20.00 MEZ.'


class Dbmultiverse_es(Dbmultiverse):
    id = 'dbmultiverse_es'
    lang = 'es'

    synopsis = 'Dragon Ball Multiverse (DBM) es un cómic online gratuito, realizado por un gran equipo de fans. Es nuestra propia continuación de DBZ.'


class Dbmultiverse_fr(Dbmultiverse):
    id = 'dbmultiverse_fr'
    lang = 'fr'

    synopsis = "Dragon Ball Multiverse (DBM) est une BD en ligne gratuite, faite par toute une équipe de fans. C'est notre suite personnelle à DBZ."


class Dbmultiverse_it(Dbmultiverse):
    id = 'dbmultiverse_it'
    lang = 'it'

    synopsis = 'Dragon Ball Multiverse (abbreviato in DBM) è un Fumetto gratuito pubblicato online e rappresenta un possibile seguito di DBZ. I creatori sono due fan: Gogeta Jr e Salagir.'


class Dbmultiverse_pt(Dbmultiverse):
    id = 'dbmultiverse_pt'
    lang = 'pt'

    synopsis = 'Dragon Ball Multiverse (DBM) é uma BD online grátis, feita por dois fãs Gogeta Jr e Salagir. É a sequela do DBZ.'


class Dbmultiverse_ru(Dbmultiverse):
    id = 'dbmultiverse_ru'
    lang = 'ru'

    synopsis = 'Dragon Ball Multiverse (DBM) это бесплатный онлайн комикс (манга), сделана двумя фанатами, Gogeta Jr и Salagir. Это продолжение DBZ.'
