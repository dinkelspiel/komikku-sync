# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
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
    'ar': 'ar_JO',
    'de': 'de',
    'en': 'en',
    'es': 'es',
    'es_419': 'es_CO',
    'fr': 'fr',
    'it': 'it',
    'ja': 'jp',
    'ko': 'kr_KR',
    'nl': 'nl',
    'pl': 'pl',
    'pt': 'pt',
    'pt_BR': 'pt_BR',
    'ru': 'ru_RU',
    'tr': 'tr_TR',
    'zh_Hans': 'cn',
}


def get_comic_from_slug(slug):
    # A previous slug format included the language (for ex. dbm_en)
    comic = slug.split('_')[0]
    if comic == 'dbm':
        comic = 'page'

    return comic


class Dbmultiverse(Server):
    id = 'dbmultiverse'
    name = 'Dragon Ball Multiverse'
    lang = 'en'
    content = ServerContent(
        type=[_('Doujinshi'), _('Fan Webcomic')]
    )
    true_search = False

    base_url = 'https://www.dragonball-multiverse.com'
    logo_url = base_url + '/favicon.ico'
    most_populars_url = None
    manga_url = None
    chapter_url = None
    page_url = None
    cover_url = base_url + '/imgs/read/{0}.jpg'

    status_complete = 'finished'

    def __init__(self):
        self.most_populars_url = self.base_url + f'/{LANGUAGES_CODES[self.lang]}/read.html'
        self.manga_url = self.base_url + f'/{LANGUAGES_CODES[self.lang]}/chapters.html?comic={{0}}'
        self.chapter_url = self.base_url + f'/{LANGUAGES_CODES[self.lang]}/chapters.html?comic={{0}}&chapter={{1}}'
        self.page_url = self.base_url + f'/{LANGUAGES_CODES[self.lang]}/{{0}}-{{1}}.html'
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content
        """
        comic = get_comic_from_slug(initial_data['slug'])

        r = self.session_get(self.manga_url.format(comic))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update({
            'authors': ['Gogeta Jr', 'Asura', 'Salagir', 'Et al.'],
            'scanlators': [],
            'genres': ['Shōnen', 'Dōjinshi'],
            'status': 'ongoing',
            'synopsis': None,
            'chapters': [],
            'server_id': self.id,
            'cover': self.cover_url.format(comic),
        })

        for element in soup.select('.dbm-tags span'):
            data['genres'].append(element.text.strip())

        if self.status_complete in soup.select_one('.cadrelect').text.strip():
            data['status'] = 'complete'

        data['synopsis'] = soup.select_one('.cadrelect > p').text.strip()

        # Chapters
        for element in soup.select('.chapter'):
            url = element.a.get('href')
            qs = parse_qs(urlparse(url).query)
            slug = qs['chapter'][0]

            chapter_data = {
                'slug': slug,
                'title': element.h4.text.strip(),
                'num': slug if is_number(slug) else None,
                'date': None,
                'pages': [],
            }

            data['chapters'].append(chapter_data)

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        comic = get_comic_from_slug(manga_slug)

        r = self.session_get(self.chapter_url.format(comic, chapter_slug))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = {
            'pages': [],
        }
        for element in soup.select('.pageslist > a > img'):
            data['pages'].append({
                'slug': element.get('title'),
                'image': None,
            })

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        comic = get_comic_from_slug(manga_slug)

        r = self.session_get(self.page_url.format(comic, page['slug']))
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

        return {
            'buffer': r.content,
            'mime_type': mime_type,
            'name': '{0}.png'.format(page['slug']),
        }

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(get_comic_from_slug(slug))

    def get_most_populars(self):
        r = self.session_get(self.most_populars_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('#dbm-reads .dbm-read'):
            url = element.a.get('href')
            if param := parse_qs(urlparse(url).query).get('comic'):
                slug = param[0]
                if slug == 'page':
                    slug = 'dbm'

                results.append({
                    'slug': slug,
                    'name': element.h3.text.strip(),
                    'cover': self.cover_url.format(get_comic_from_slug(slug)),
                })

        return results

    def search(self, term=None):
        # This server does not have a true search
        # but a search method is needed for `Global Search` in `Explorer`
        # In order not to be offered in `Explorer`, class attribute `true_search` must be set to False

        results = []
        for item in self.get_most_populars():
            if term and term.lower() in item['name'].lower():
                results.append(item)

        return results


class Dbmultiverse_ar(Dbmultiverse):
    id = 'dbmultiverse_ar'
    lang = 'ar'

    status_complete = 'انتهت'


class Dbmultiverse_de(Dbmultiverse):
    id = 'dbmultiverse_de'
    lang = 'de'

    status_complete = 'beendet'


class Dbmultiverse_es(Dbmultiverse):
    id = 'dbmultiverse_es'
    lang = 'es'

    status_complete = 'terminado'


class Dbmultiverse_es_419(Dbmultiverse):
    id = 'dbmultiverse_es_419'
    lang = 'es_419'

    status_complete = 'terminado'


class Dbmultiverse_fr(Dbmultiverse):
    id = 'dbmultiverse_fr'
    lang = 'fr'

    status_complete = 'terminé'


class Dbmultiverse_it(Dbmultiverse):
    id = 'dbmultiverse_it'
    lang = 'it'

    status_complete = 'concluso'


class Dbmultiverse_ja(Dbmultiverse):
    id = 'dbmultiverse_ja'
    lang = 'ja'

    status_complete = 'finished'


class Dbmultiverse_ko(Dbmultiverse):
    id = 'dbmultiverse_ko'
    lang = 'ko'

    status_complete = 'finished'


class Dbmultiverse_nl(Dbmultiverse):
    id = 'dbmultiverse_nl'
    lang = 'nl'

    status_complete = 'finished'


class Dbmultiverse_pl(Dbmultiverse):
    id = 'dbmultiverse_pl'
    lang = 'pl'

    status_complete = 'finished'


class Dbmultiverse_pt(Dbmultiverse):
    id = 'dbmultiverse_pt'
    lang = 'pt'

    status_complete = 'finished'


class Dbmultiverse_pt_BR(Dbmultiverse):
    id = 'dbmultiverse_pt_BR'
    lang = 'pt_BR'

    status_complete = 'finalizada'


class Dbmultiverse_ru(Dbmultiverse):
    id = 'dbmultiverse_ru'
    lang = 'ru'

    status_complete = 'finished'


class Dbmultiverse_tr(Dbmultiverse):
    id = 'dbmultiverse_tr'
    lang = 'tr'

    status_complete = 'finished'


class Dbmultiverse_zh_Hans(Dbmultiverse):
    id = 'dbmultiverse_zh_Hans'
    lang = 'zh_Hans'

    status_complete = 'finished'
