# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import json

from bs4 import BeautifulSoup

from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number
from komikku.webview import CompleteChallenge

LANGUAGES_CODES = dict(
    ar='ar',
    cs='cs',
    de='de',
    en='en',
    es='es',
    es_419='es-419',
    fa='fa',
    fr='fr',
    id='id',
    it='it',
    ja='jp',
    ko='kr',
    nl='nl',
    pl='pl',
    pt='pt-pt',
    pt_BR='pt-br',
    ru='ru',
    th='th',
    tr='tr',
    uk='uk',
    vi='vi',
    zh_Hant='zh',
    zh_Hans='zh-cn',
)


class Mangaball(Server):
    id = 'mangaball'
    name = 'MangaBall'
    lang = 'en'

    has_cf = True
    is_nsfw = True

    base_url = 'https://mangaball.net'
    logo_url = base_url + '/public/frontend/images/favicon/favicon-32x32.png'

    search_url = base_url + '/search-advanced/'
    manga_url = base_url + '/title-detail/{0}/'
    chapter_url = base_url + '/chapter-detail/{0}/'

    api_url = base_url + '/api/v1'
    api_search_url = api_url + '/title/search-advanced/'
    api_chapters_url = api_url + '/chapter/chapter-listing-by-title-id/'

    filters = [
        {
            'key': 'demographic',
            'type': 'select',
            'name': _('Demographic'),
            'description': _('Filter by Publication Demographic'),
            'value_type': 'single',
            'default': 'any',
            'options': [
                {'key': 'any', 'name': _('Any')},
                {'key': 'shounen', 'name': _('Shounen')},
                {'key': 'shoujo', 'name': _('Shoujo')},
                {'key': 'seinen', 'name': _('Seinen')},
                {'key': 'josei', 'name': _('Josei')},
                {'key': 'yuri', 'name': _('Yuri')},
                {'key': 'yaoi', 'name': _('Yaoi')},
            ],
        },
        {
            'key': 'status',
            'type': 'select',
            'name': _('Status'),
            'description': _('Filter by Status'),
            'value_type': 'single',
            'default': 'any',
            'options': [
                {'key': 'any', 'name': _('Any')},
                {'key': 'ongoing', 'name': _('Ongoing')},
                {'key': 'completed', 'name': _('Completed')},
                {'key': 'hiatus', 'name': _('Hiatus')},
                {'key': 'cancelled', 'name': _('Canceled')},
            ]
        },
    ]

    def __init__(self):
        self.session = None

    @CompleteChallenge()
    def get_manga_data(self, initial_data):
        """
        Returns manga data from manga HTML page

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()

        data.update(dict(
            authors=[],
            scanlators=[],
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        csrf_token = soup.select_one('meta[name="csrf-token"]')['content']

        data['name'] = soup.select_one('#comicDetail h6').text.strip()
        data['cover'] = soup.select_one('.featured-cover').get('src')

        if element := soup.select_one('.badge-status'):
            status = element.text.strip()
            if status == 'Completed':
                data['status'] = 'complete'
            elif status == 'Ongoing':
                data['status'] = 'ongoing'
            elif status == 'Hiatus':
                data['status'] = 'Hiatus'
            elif status == 'Cancelled':
                data['status'] = 'suspended'

        for element in soup.select('[data-tag-id]'):
            data['genres'].append(element.text.strip())

        for element in soup.select('[data-person-id]'):
            data['authors'].append(element.text.strip())

        if element := soup.select_one('.description-text > p'):
            data['synopsis'] = element.text.strip()

        # Chapters
        title_id = data['slug'].split('-')[-1]
        r = self.session_post(
            self.api_chapters_url,
            data={
                'title_id': title_id,
                'lang': LANGUAGES_CODES[self.lang],
            },
            headers={
                'Referer': self.manga_url.format(data['slug']),
                'X-Csrf-TOKEN': csrf_token,
                'X-Requested-With': 'XMLHttpRequest',
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()

        for chapter in reversed(resp_data['ALL_CHAPTERS']):
            num = chapter['number_float']
            for translation in chapter['translations']:
                num_volume = translation.get('volume')
                group = translation.get('group')

                data['chapters'].append(dict(
                    slug=translation['id'],
                    title=translation['name'].strip(),
                    scanlators=[group['name']] if group else None,
                    num=num if is_number(num) else None,
                    num_volume=num_volume if is_number(num_volume) else None,
                    date=convert_date_string(translation['date'].split(' ')[0], format='%Y-%m-%d'),
                ))

        return data

    @CompleteChallenge()
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data from chapter HTML page

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
        for script_element in soup.select('script'):
            script = script_element.string
            if not script or 'const chapterImages' not in script:
                continue

            for line in script.split('\n'):
                line = line.strip()
                if not line.startswith('const chapterImages'):
                    continue

                try:
                    # const chapterImages = JSON.parse(`[...]`);
                    urls = json.loads(line[34:-3])
                    for url in urls:
                        data['pages'].append(dict(
                            slug=None,
                            image=url,
                        ))
                except Exception:
                    return None

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(page['image'])
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=page['image'].split('/')[-1],
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_manga_list(self, term=None, demographic=None, status=None, orderby=None):
        # CRSF token
        r = self.session_get(self.search_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        csrf_token = soup.select_one('meta[name="csrf-token"]')['content']

        payload = {}
        if term:
            payload['search_input'] = term

        payload.update({
            'filters[sort]': orderby or 'name_asc',
            'filters[page]': '1',
            'filters[tag_included_mode]': 'and',
            'filters[tag_excluded_mode]': 'and',
            'filters[contentRating]': 'any',
            'filters[demographic]': demographic,
            'filters[person]': 'any',
            'filters[publicationYear]': '',
            'filters[publicationStatus]': status,
            'filters[translatedLanguage][]': LANGUAGES_CODES[self.lang],
        })

        r = self.session_post(
            self.api_search_url,
            data=payload,
            headers={
                'Referer': self.base_url,
                'X-Csrf-TOKEN': csrf_token,
                'X-Requested-With': 'XMLHttpRequest',
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()

        results = []
        for item in resp_data['data']:
            results.append(dict(
                slug=item['url'].split('/')[-2],
                name=item['name'],
                cover=item['cover'],
            ))

        return results

    @CompleteChallenge()
    def get_latest_updates(self, demographic='any', status='any'):
        return self.get_manga_list(demographic=demographic, status=status, orderby='updated_chapters_desc')

    @CompleteChallenge()
    def get_most_populars(self, demographic='any', status='any'):
        return self.get_manga_list(demographic=demographic, status=status, orderby='views_desc')

    @CompleteChallenge()
    def search(self, term, demographic='any', status='any'):
        return self.get_manga_list(term=term, demographic=demographic, status=status)


class Mangaball_ar(Mangaball):
    id = 'mangaball_ar'
    lang = 'ar'


class Mangaball_cs(Mangaball):
    id = 'mangaball_cs'
    lang = 'cs'


class Mangaball_de(Mangaball):
    id = 'mangaball_de'
    lang = 'de'


class Mangaball_es(Mangaball):
    id = 'mangaball_es'
    lang = 'es'


class Mangaball_es_419(Mangaball):
    id = 'mangaball_es_419'
    lang = 'es_419'


class Mangaball_fa(Mangaball):
    id = 'mangaball_fa'
    lang = 'fa'


class Mangaball_fr(Mangaball):
    id = 'mangaball_fr'
    lang = 'fr'


class Mangaball_id(Mangaball):
    id = 'mangaball_id'
    lang = 'id'


class Mangaball_it(Mangaball):
    id = 'mangaball_it'
    lang = 'it'


class Mangaball_ja(Mangaball):
    id = 'mangaball_ja'
    lang = 'ja'


class Mangaball_ko(Mangaball):
    id = 'mangaball_ko'
    lang = 'ko'


class Mangaball_nl(Mangaball):
    id = 'mangaball_nl'
    lang = 'nl'


class Mangaball_pl(Mangaball):
    id = 'mangaball_pl'
    lang = 'pl'


class Mangaball_pt(Mangaball):
    id = 'mangaball_pt'
    lang = 'pt'


class Mangaball_pt_br(Mangaball):
    id = 'mangaball_pt_br'
    lang = 'pt_BR'


class Mangaball_ru(Mangaball):
    id = 'mangaball_ru'
    lang = 'ru'


class Mangaball_th(Mangaball):
    id = 'mangaball_th'
    lang = 'th'


class Mangaball_tr(Mangaball):
    id = 'mangaball_tr'
    lang = 'tr'


class Mangaball_uk(Mangaball):
    id = 'mangaball_uk'
    lang = 'uk'


class Mangaball_vi(Mangaball):
    id = 'mangaball_vi'
    lang = 'vi'


class Mangaball_zh_hant(Mangaball):
    id = 'mangaball_zh_hant'
    lang = 'zh_Hant'


class Mangaball_zh_hans(Mangaball):
    id = 'mangaball_zh_hans'
    lang = 'zh_Hans'
