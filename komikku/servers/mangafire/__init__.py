# SPDX-FileCopyrightText: 2023-2024 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number
from komikku.webview import get_page_html
from komikku.webview import get_page_resources

LANGUAGES_CODES = dict(
    en='en',
    es='es',
    es_419='es-la',
    fr='fr',
    ja='ja',
    pt='pt',
    pt_BR='pt-br',
)


class Mangafire(Server):
    id = 'mangafire'
    name = 'MangaFire'
    lang = 'en'

    base_url = 'https://mangafire.to'
    logo_url = base_url + '/assets/sites/mangafire/favicon.png?v3'
    search_url = base_url + '/filter'
    manga_url = base_url + '/manga/{0}'                          # slug
    chapter_url = base_url + '/read/{0}/{1}/chapter-{2}'         # manga_slug, lang, slug
    api_chapters_url = base_url + '/ajax/manga/{0}/chapter/{1}'  # code in manga slug, lang: used to get chapters list (slug, title, date)

    filters = [
        {
            'key': 'types',
            'type': 'select',
            'name': _('Type'),
            'description': _('Filter by Types'),
            'value_type': 'multiple',
            'options': [
                {'key': 'manga', 'name': _('Manga'), 'default': False},
                {'key': 'one_shot', 'name': _('Oneshot'), 'default': False},
                {'key': 'doujinshi', 'name': _('Doujinshi'), 'default': False},
                {'key': 'novel', 'name': _('Novel'), 'default': False},
                {'key': 'manhwa', 'name': _('Manhwa'), 'default': False},
                {'key': 'manhua', 'name': _('Manhua'), 'default': False},
            ],
        },
        {
            'key': 'statuses',
            'type': 'select',
            'name': _('Status'),
            'description': _('Filter by Statuses'),
            'value_type': 'multiple',
            'options': [
                {'key': 'releasing', 'name': _('Releasing'), 'default': False},
                {'key': 'completed', 'name': _('Completed'), 'default': False},
                {'key': 'discontinued', 'name': _('Discontinued'), 'default': False},
                {'key': 'on_hiatus', 'name': _('Hiatus'), 'default': False},
            ],
        },
    ]

    vrf = {}

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Returns manga data from API

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],  # not available
            genres=[],
            status=None,
            cover=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
        ))

        data['name'] = soup.select_one('.info h1').text.strip()
        data['cover'] = soup.select_one('.poster img').get('src')

        # Details
        if element := soup.select_one('.info > p'):
            value = element.text.strip()
            if value == 'Releasing':
                data['status'] = 'ongoing'
            elif value == 'Completed':
                data['status'] = 'complete'
            elif value == 'Discontinued':
                data['status'] = 'suspended'
            elif value == 'On_hiatus':
                data['status'] = 'hiatus'

        if element := soup.select_one('span:-soup-contains("Author") + span a'):
            data['authors'].append(element.text.strip())

        for element in soup.select('span:-soup-contains("Genres") + span a'):
            data['genres'].append(element.text.strip())

        if element := soup.select_one('#synopsis'):
            data['synopsis'] = element.text.strip()

        # Chapters
        r = self.session_get(
            self.api_chapters_url.format(initial_data['slug'].split('.')[1], LANGUAGES_CODES[self.lang]),
            headers={
                'Referer': self.manga_url.format(initial_data['slug']),
                'X-Requested-With': 'XMLHttpRequest',
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.json()['result'], 'lxml')

        for element in reversed(soup.select('li')):
            a_element = element.a
            title_element = a_element.select_one('span:first-child')
            date_element = a_element.select_one('span:last-child')

            slug = element.get('data-number')
            title = title_element.text.strip()
            if hover_title := a_element.get('title'):
                if 'Vol' in hover_title:
                    title = f'{hover_title.split("-")[0].strip()} - {title}'

            data['chapters'].append(dict(
                slug=slug,
                title=title,
                num=slug if is_number(slug) else None,
                date=convert_date_string(date_element.text.strip(), languages=[self.lang]),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        # Get API chapter endpoint URL with webview
        resources = get_page_resources(
            self.chapter_url.format(manga_slug, LANGUAGES_CODES[self.lang], chapter_slug),
            paths=['/ajax/read/chapter', '/ajax/read/volume']
        )
        if not resources:
            return None

        api_chapter_url = resources[0]['uri']

        r = self.session_get(
            api_chapter_url,
            headers={
                'Referer': self.chapter_url.format(manga_slug, LANGUAGES_CODES[self.lang], chapter_slug),
                'X-Requested-With': 'XMLHttpRequest',
            }
        )
        if r.status_code != 200:
            return None

        data = dict(
            pages=[],
        )
        for index, item in enumerate(r.json()['result']['images']):
            data['pages'].append(dict(
                slug=None,
                image=item[0],
                index=index + 1,
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        # SSL cert verification fails for *.mfcdn1.xzy CDNs
        domains = [
            'mfcdn1.xyz',
        ]
        verify = True

        for domain in domains:
            if domain in page['image']:
                verify = False
                break

        r = self.session_get(
            page['image'],
            headers={
                'Referer': f'{self.base_url}/',
            },
            verify=verify
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=f'{page["index"]:03d}.{mime_type.split("/")[-1]}',  # noqa: E231
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_manga_list(self, keyword=None, types=None, statuses=None, sort='most_relevance'):
        params = {
            'keyword': keyword,
            'type[]': types,
            'status[]': statuses,
            'language[]': LANGUAGES_CODES[self.lang],
            'sort': sort,
        }

        if keyword:
            if keyword not in self.vrf:
                # Get `vrf` param with webview
                wait_js_code = """
                    let intervalID = setInterval(() => {
                        if (document.readyState === 'loading') {
                            return;
                        }

                        const searchInput = document.querySelector('#filters .search input');
                        if (!searchInput.value) {
                            searchInput.value = '%s';
                            searchInput.focus();

                            let spaceEvent = new KeyboardEvent('keydown', {
                                key: ' ',
                                keyCode: 32,
                                code: 'Space',
                                which: 32,
                                bubbles: true,
                                cancelable: true
                            });

                            // Dispatch event on input
                            searchInput.dispatchEvent(spaceEvent);

                            spaceEvent = new KeyboardEvent('keyup', {
                                key: ' ',
                                keyCode: 32,
                                code: 'Space',
                                which: 32,
                                bubbles: true,
                                cancelable: true
                            });

                            // Dispatch event on input
                            searchInput.dispatchEvent(spaceEvent);

                            return;
                        }

                        const vrfInput = document.querySelector('#filters input[name="vrf"]');
                        if (vrfInput.value) {
                            document.title = 'ready';
                            clearInterval(intervalID);
                        }
                    }, 100);
                """ % keyword

                html = get_page_html(self.search_url, wait_js_code=wait_js_code)

                soup = BeautifulSoup(html, 'lxml')

                self.vrf[keyword] = soup.select_one('#filters input[name="vrf"]').get('value')

            params['vrf'] = self.vrf[keyword]

        r = self.session_get(
            self.search_url,
            params=params,
            headers={
                'Referer': self.search_url,
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.unit'):
            a_element = element.select_one('.info > a')
            img_element = element.select_one('.poster img')

            last_chapter = None
            for chap_element in element.select('.info ul li a'):
                chap_lang, chap_slug = chap_element.get('href').split('/')[-2:]
                if chap_lang == LANGUAGES_CODES[self.lang]:
                    last_chapter = chap_slug.replace('chapter-', '')
                    break

            results.append(dict(
                slug=a_element.get('href').split('/')[-1],
                name=a_element.text.strip(),
                cover=img_element.get('src'),
                last_chapter=last_chapter,
            ))

        return results

    def get_latest_updates(self, types=None, statuses=None):
        return self.get_manga_list(types=types, statuses=statuses, sort='recently_updated')

    def get_most_populars(self, types=None, statuses=None):
        return self.get_manga_list(types=types, statuses=statuses, sort='most_viewed')

    def search(self, term, types=None, statuses=None):
        return self.get_manga_list(keyword=term, types=types, statuses=statuses)


class Mangafire_es(Mangafire):
    id = 'mangafire_es'
    name = 'MangaFire'
    lang = 'es'


class Mangafire_es_419(Mangafire):
    id = 'mangafire_es_419'
    name = 'MangaFire'
    lang = 'es_419'


class Mangafire_fr(Mangafire):
    id = 'mangafire_fr'
    name = 'MangaFire'
    lang = 'fr'


class Mangafire_ja(Mangafire):
    id = 'mangafire_ja'
    name = 'MangaFire'
    lang = 'ja'


class Mangafire_pt(Mangafire):
    id = 'mangafire_pt'
    name = 'MangaFire'
    lang = 'pt'


class Mangafire_pt_br(Mangafire):
    id = 'mangafire_pt_br'
    name = 'MangaFire'
    lang = 'pt_BR'
