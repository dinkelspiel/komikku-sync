# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.utils import get_buffer_mime_type
from komikku.utils import ServerContent

# Conversion ISO_639-1 codes => server codes
LANGUAGES_CODES = dict(
    cs='cs',
    de='de',
    en='en',
    eo='eo',
    es='es',
    fa='fa',
    fr='fr',
    id='id',
    it='it',
    ja='ja',
    ko='kr',  # diff
    nb='no',  # diff
    nl='nl',
    pl='pl',
    pt='pt',
    ru='ru',
    vi='vi',
    zh_Hans='cn',  # diff
)

SERVER_NAME = 'Pepper & Carrot'


class Peppercarrot(Server):
    id = 'peppercarrot'
    name = SERVER_NAME
    lang = 'en'
    content = ServerContent(
        type=[_('Webcomic'), _('Self-publishing')],
        license='CC BY'
    )
    true_search = False

    base_url = 'https://www.peppercarrot.com'
    donate_url = base_url + '/en/support/index.html'
    logo_url = base_url + '/core/img/favicon.png'
    manga_url = base_url + '/{0}/webcomics/index.html'
    langs_url = base_url + '/0_sources/langs.json'
    chapters_url = base_url + '/0_sources/episodes-v1.json'
    image_url = base_url + '/0_sources/{0}/low-res/{1}_{2}'
    cover_url = base_url + '/0_sources/0ther/artworks/low-res/2016-02-24_vertical-cover_remake_by-David-Revoy.jpg'

    genres = ['Fantasy', 'Magical girl', 'Coming-of-age']
    synopsis = 'This is the story of the young witch Pepper and her cat Carrot in the magical world of Hereva. Pepper learns the magic of Chaosah, the magic of chaos, with his godmothers Cayenne, Thyme and Cumin. Other witches like Saffron, Coriander, Camomile and Schichimi learn magics that each have their specificities.'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

        self.donate_url = f'{self.base_url}/{LANGUAGES_CODES[self.lang]}/support/index.html'

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content
        """
        r = self.session_get(self.manga_url.format(LANGUAGES_CODES[self.lang]))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update(dict(
            authors=['David Revoy', ],
            scanlators=[],
            genres=self.genres,
            status='ongoing',
            synopsis=self.synopsis,
            chapters=[],
            server_id=self.id,
            cover=self.cover_url,
        ))

        # Scanlators (translators here)
        r = self.session_get(self.langs_url)
        if r.ok:
            if lang_data := r.json().get(LANGUAGES_CODES[self.lang]):
                data['scanlators'] = lang_data['translators']

        # Chapters
        r = self.session_get(self.chapters_url)
        if r.status_code != 200:
            return None

        chapters_data = r.json()

        for index, element in enumerate(reversed(soup.select('figure.thumbnail'))):
            if 'notranslation' in element.get('class'):
                # Skipped not translated episodes
                continue

            data['chapters'].append(dict(
                slug=chapters_data[index]['name'],
                date=None,
                title=element.a.img.get('title').split('(')[0].strip(),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data using episodes API service
        """
        r = self.session_get(self.chapters_url)
        if r.status_code != 200:
            return None

        chapters_data = r.json()
        for chapter_data in chapters_data:
            if chapter_data['name'] == chapter_slug:
                pages = chapter_data['pages']
                break

        data = dict(
            pages=[],
        )

        # Cover & Title pages are first
        data['pages'].append(dict(
            slug=pages.pop('cover'),
            image=None,
        ))
        data['pages'].append(dict(
            slug=pages.pop('title'),
            image=None,
        ))
        credits_slug = pages.pop('credits')

        # Sort pages
        pages = dict(sorted(pages.items(), key=lambda x: int(x[0])))

        for _key, page_name in pages.items():
            data['pages'].append(dict(
                slug=page_name,
                image=None,
            ))

        # Credits page at end
        data['pages'].append(dict(
            slug=credits_slug,
            image=None,
        ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(self.image_url.format(chapter_slug, LANGUAGES_CODES[self.lang], page['slug']))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=page['slug'],
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(LANGUAGES_CODES[self.lang])

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


class Peppercarrot_cs(Peppercarrot):
    id = 'peppercarrot_cs'
    name = SERVER_NAME
    lang = 'cs'


class Peppercarrot_de(Peppercarrot):
    id = 'peppercarrot_de'
    name = SERVER_NAME
    lang = 'de'


class Peppercarrot_eo(Peppercarrot):
    id = 'peppercarrot_eo'
    name = SERVER_NAME
    lang = 'eo'


class Peppercarrot_es(Peppercarrot):
    id = 'peppercarrot_es'
    name = SERVER_NAME
    lang = 'es'


class Peppercarrot_fa(Peppercarrot):
    id = 'peppercarrot_fa'
    name = 'فلفل و هویج'
    lang = 'fa'

    synopsis = 'این داستان جادوگر جوان فلفل و گربه‌اش هویج در دنیای جادویی هروا است. پپر جادوی چائوسا، جادوی آشوب، را به همراه مادربزرگ‌هایش کاین، آویشن و زیره می‌آموزد. جادوگران دیگری مانند زعفران، گشنیز، بابونه و شیچیمی جادوهایی را یاد می‌گیرند که هر کدام ویژگی‌های خاص خود را دارند.'


class Peppercarrot_fr(Peppercarrot):
    id = 'peppercarrot_fr'
    name = SERVER_NAME
    lang = 'fr'

    synopsis = "C'est l'histoire de la jeune sorcière Pepper et de son chat Carrot dans le monde magique d'Hereva. Pepper apprend la magie de Chaosah, la magie du chaos, avec ses marraines Cayenne, Thym et Cumin. D'autres sorcières comme Saffran, Coriandre, Camomille et Schichimi apprennent des magies qui ont chacune leurs spécificités."


class Peppercarrot_id(Peppercarrot):
    id = 'peppercarrot_id'
    name = SERVER_NAME
    lang = 'id'


class Peppercarrot_it(Peppercarrot):
    id = 'peppercarrot_it'
    name = SERVER_NAME
    lang = 'it'


class Peppercarrot_ja(Peppercarrot):
    id = 'peppercarrot_ja'
    name = SERVER_NAME
    lang = 'ja'


class Peppercarrot_ko(Peppercarrot):
    id = 'peppercarrot_ko'
    name = SERVER_NAME
    lang = 'ko'


class Peppercarrot_nb(Peppercarrot):
    id = 'peppercarrot_nb'
    name = SERVER_NAME
    lang = 'nb'


class Peppercarrot_nl(Peppercarrot):
    id = 'peppercarrot_nl'
    name = SERVER_NAME
    lang = 'nl'


class Peppercarrot_pl(Peppercarrot):
    id = 'peppercarrot_pl'
    name = SERVER_NAME
    lang = 'pl'


class Peppercarrot_pt(Peppercarrot):
    id = 'peppercarrot_pt'
    name = SERVER_NAME
    lang = 'pt'


class Peppercarrot_ru(Peppercarrot):
    id = 'peppercarrot_ru'
    name = SERVER_NAME
    lang = 'ru'


class Peppercarrot_vi(Peppercarrot):
    id = 'peppercarrot_vi'
    name = SERVER_NAME
    lang = 'vi'


class Peppercarrot_zh_hans(Peppercarrot):
    id = 'peppercarrot_zh_hans'
    name = SERVER_NAME
    lang = 'zh_Hans'
