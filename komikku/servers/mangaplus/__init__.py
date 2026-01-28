# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from datetime import datetime
from functools import wraps
import re
import uuid

import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number

LANGUAGES_CODES = dict(
    de='deu',
    en='eng',
    es='esp',
    fr='fra',
    id='ind',
    pt_BR='ptb',
    ru='rus',
    th='tha',
    vi='vie',
)

LANGUAGES_CODES2 = dict(
    de='GERMAN',
    en='ENGLISH',
    es='SPANISH',
    fr='FRENCH',
    id='INDONESIAN',
    pt_BR='PORTUGUESE_BR',
    ru='RUSSIAN',
    th='THAI',
    vi='VIETNAMESE',
)

RE_ENCRYPTION_KEY = re.compile('.{1,2}')


def set_lang(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        server = args[0]
        if not server.is_lang_set:
            server.session_get(server.api_params_url, params=dict(lang=LANGUAGES_CODES[server.lang]))
            server.is_lang_set = True

        return func(*args, **kwargs)

    return wrapper


class Mangaplus(Server):
    id = 'mangaplus'
    name = 'MANGA Plus by SHUEISHA'
    lang = 'en'
    status = 'disabled'  # commercial platforms are no supported

    is_lang_set = False

    base_url = 'https://mangaplus.shueisha.co.jp'
    api_url = 'https://jumpg-webapi.tokyo-cdn.com/api'
    api_params_url = api_url + '/featured'
    api_search_url = api_url + '/title_list/allV2?format=json'
    # api_latest_updates_url = api_url + '/web/web_homeV4?lang={0}&format=json'
    api_latest_updates_url = api_url + '/home_v4?lang={0}&clang={0}&format=json'
    api_most_populars_url = api_url + '/title_list/rankingV2?lang={0}&type=hottest&clang={0}&format=json'
    api_manga_url = api_url + '/title_detailV3?title_id={0}&format=json'
    api_chapter_url = api_url + '/manga_viewer?chapter_id={0}&split=yes&img_quality=high&format=json'
    manga_url = base_url + '/titles/{0}'

    headers = {
        'User-Agent': USER_AGENT,
        'Origin': base_url,
        'Referer': f'{base_url}/',
        'SESSION-TOKEN': repr(uuid.uuid1()),
    }

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers = self.headers

    @set_lang
    def get_manga_data(self, initial_data):
        """
        Returns manga data from API

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(self.api_manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type not in ('application/json', 'text/plain'):
            return None

        resp_data = r.json()
        if resp_data.get('error'):
            return None

        resp_data = resp_data['success']['titleDetailView']

        data = initial_data.copy()
        data.update(dict(
            name=resp_data['title']['name'],
            authors=[resp_data['title']['author']],
            scanlators=['Shueisha'],
            genres=[],
            status='ongoing',
            synopsis=resp_data['overview'],
            chapters=[],
            server_id=self.id,
            cover=resp_data['title']['portraitImageUrl'],
        ))

        # Chapters
        for group in resp_data['chapterListGroup']:
            for key in ('firstChapterList', 'lastChapterList'):
                chapters = group.get(key)
                if chapters is None:
                    continue

                for chapter in chapters:
                    num = chapter['name'].lstrip('#')

                    data['chapters'].append(dict(
                        slug=str(chapter['chapterId']),
                        title='{0} - {1}'.format(chapter['name'], chapter['subTitle']),
                        num=num if is_number(num) else None,
                        date=datetime.fromtimestamp(chapter['startTimeStamp']).date(),
                    ))

        return data

    @set_lang
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data from API

        Currently, only pages are expected.
        """
        r = self.session_get(self.api_chapter_url.format(chapter_slug))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type not in ('application/json', 'text/plain'):
            return None

        resp_data = r.json()
        if resp_data.get('error'):
            return None

        data = dict(
            pages=[],
        )
        for page in resp_data['success']['mangaViewer']['pages']:
            if not page.get('mangaPage'):
                continue

            data['pages'].append(dict(
                slug=None,
                image=page['mangaPage']['imageUrl'],
                encryption_key=page['mangaPage'].get('encryptionKey'),
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(page['image'])
        if r.status_code != 200:
            return None

        if page['encryption_key'] is not None:
            # Decrypt
            key_stream = [int(v, 16) for v in RE_ENCRYPTION_KEY.findall(page['encryption_key'])]
            block_size_in_bytes = len(key_stream)

            content = bytes([int(v) ^ key_stream[index % block_size_in_bytes] for index, v in enumerate(r.content)])
        else:
            content = r.content

        mime_type = get_buffer_mime_type(content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=content,
            mime_type=mime_type,
            name=page['image'].split('?')[0].split('/')[-1],
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    @set_lang
    def get_latest_updates(self):
        """
        Returns latest updates
        """
        r = self.session_get(
            self.api_latest_updates_url.format(LANGUAGES_CODES[self.lang]),
            headers={
                'Referer': self.base_url + '/',
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type not in ('application/json', 'text/plain'):
            return None

        resp_data = r.json()
        if resp_data.get('error'):
            return None

        results = []
        for group in resp_data['success']['homeViewV3']['groups']:
            for title_group in group['titleGroups']:
                for title in title_group['titles']:
                    info = title['title']

                    if info.get('language', 'ENGLISH') != LANGUAGES_CODES2[self.lang]:
                        continue

                    results.append(dict(
                        slug=info['titleId'],
                        name=info['name'],
                        cover=info['portraitImageUrl'],
                        last_chapter=title['chapterName'],
                    ))

        return results

    @set_lang
    def get_most_populars(self):
        """
        Returns hottest manga list
        """
        r = self.session_get(self.api_most_populars_url.format(LANGUAGES_CODES[self.lang]))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type not in ('application/json', 'text/plain'):
            return None

        resp_data = r.json()
        if resp_data.get('error'):
            return None

        results = []
        for group in resp_data['success']['titleRankingViewV2']['rankedTitles']:
            for title in group['titles']:
                if title.get('language', 'ENGLISH') != LANGUAGES_CODES2[self.lang]:
                    continue

                results.append(dict(
                    slug=title['titleId'],
                    name=title['name'],
                    cover=title['portraitImageUrl'],
                ))

        return results

    @set_lang
    def search(self, term):
        r = self.session_get(self.api_search_url)
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type not in ('application/json', 'text/plain'):
            return None

        resp_data = r.json()
        if resp_data.get('error'):
            return None

        results = []
        for group in resp_data['success']['allTitlesViewV2']['AllTitlesGroup']:
            for title in group['titles']:
                if title.get('language', 'ENGLISH') != LANGUAGES_CODES2[self.lang]:
                    continue

                if term.lower() not in title['name'].lower():
                    continue

                results.append(dict(
                    slug=title['titleId'],
                    name=title['name'],
                    cover=title['portraitImageUrl'],
                ))

        return results


class Mangaplus_de(Mangaplus):
    id = 'mangaplus_de'
    lang = 'de'


class Mangaplus_es(Mangaplus):
    id = 'mangaplus_es'
    lang = 'es'


class Mangaplus_fr(Mangaplus):
    id = 'mangaplus_fr'
    lang = 'fr'


class Mangaplus_id(Mangaplus):
    id = 'mangaplus_id'
    lang = 'id'


class Mangaplus_pt_br(Mangaplus):
    id = 'mangaplus_pt_br'
    lang = 'pt_BR'


class Mangaplus_ru(Mangaplus):
    id = 'mangaplus_ru'
    lang = 'ru'


class Mangaplus_th(Mangaplus):
    id = 'mangaplus_th'
    lang = 'th'


class Mangaplus_vi(Mangaplus):
    id = 'mangaplus_vi'
    lang = 'vi'
