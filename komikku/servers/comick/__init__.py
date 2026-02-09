# SPDX-FileCopyrightText: 2025 gondolyr <gondolyr+code@posteo.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Author: gondolyr <gondolyr+code@posteo.org>

#
# API doc: https://api.comick.fun/docs/
#

from gettext import gettext as _
import logging

try:
    # For some reasons, under flatpak sandbox, API calls return 403 errors!
    # API works perfectly well in terminal with curl (Note that `--tlsv1.3` option is required with GNOME 48 runtime)
    # Only solution found, use curl_cffi (JA3/TLS and HTTP2 fingerprints impersonation) in place of requests
    # What's wrong with sandbox?
    from curl_cffi import requests
except Exception:
    # Server will be disabled
    requests = None

from komikku.consts import REQUESTS_TIMEOUT
from komikku.servers import Server
from komikku.servers.exceptions import NotFoundError
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type

logger = logging.getLogger('komikku.servers.comick')

CHAPTERS_PER_REQUEST = 100
SEARCH_RESULTS_LIMIT = 50

SERVER_NAME = 'ComicK'


class Comick(Server):
    id = 'comick'
    name = SERVER_NAME
    lang = 'en'
    lang_code = 'en'

    is_nsfw = True
    # status = 'enabled' if requests is not None else 'disabled'
    status = 'disabled'  # Shut down 09/2025

    base_url = 'https://comick.io'
    logo_url = base_url + '/favicon.ico'

    api_base_url = 'https://api.comick.fun'
    api_search_url = api_base_url + '/v1.0/search/'
    api_latest_chapters_url = api_base_url + '/chapter/'
    api_manga_url = api_base_url + '/comic/{slug}/'
    api_manga_chapters_url = api_base_url + '/comic/{hid}/chapters'
    api_chapter_url = api_base_url + '/chapter/{hid}/'

    manga_url = base_url + '/comic/{slug}'
    image_url = 'https://meo.comick.pictures/{b2key}'

    filters = [
        {
            'key': 'ratings',
            'type': 'select',
            'name': _('Rating'),
            'description': _('Filter by Content Ratings'),
            'value_type': 'multiple',
            'options': [
                {'key': 'safe', 'name': _('Safe'), 'default': True},
                {'key': 'suggestive', 'name': _('Suggestive'), 'default': True},
                {'key': 'erotica', 'name': _('Erotica'), 'default': False},
            ],
        },
        {
            'key': 'statuses',
            'type': 'select',
            'name': _('Status'),
            'description': _('Filter by Statuses'),
            'value_type': 'multiple',
            'options': [
                {'key': '1', 'name': _('Ongoing'), 'default': False},
                {'key': '2', 'name': _('Completed'), 'default': False},
                {'key': '3', 'name': _('Canceled'), 'default': False},
                {'key': '4', 'name': _('Paused'), 'default': False},
            ],
        },
        {
            'key': 'origination',
            'type': 'select',
            'name': _('Origination'),
            'description': _('[Latest Updates only] Filter by Origination'),
            'value_type': 'multiple',
            'options': [
                {'key': 'manga', 'name': _('Manga'), 'default': False},
                {'key': 'manhwa', 'name': _('Manhwa'), 'default': False},
                {'key': 'manhua', 'name': _('Manhua'), 'default': False},
            ],
        },
        {
            'key': 'countries',
            'type': 'select',
            'name': _('Countries'),
            'description': _(
                '[Search and Most Popular only] Filter by Country (origination)'
            ),
            'value_type': 'multiple',
            'options': [
                {'key': 'jp', 'name': _('Japan (Manga)'), 'default': False},
                {'key': 'kr', 'name': _('Korea (Manhwa)'), 'default': False},
                {'key': 'cn', 'name': _('China (Manhua)'), 'default': False},
            ],
        },
        {
            'key': 'publication_demographics',
            'type': 'select',
            'name': _('Publication Demographic'),
            'description': _('Filter by Publication Demographics'),
            'value_type': 'multiple',
            'options': [
                {'key': '1', 'name': _('Shounen'), 'default': False},
                {'key': '2', 'name': _('Shoujo'), 'default': False},
                {'key': '3', 'name': _('Seinen'), 'default': False},
                {'key': '4', 'name': _('Josei'), 'default': False},
                {'key': '5', 'name': _('None'), 'default': False},
            ],
        },
        {
            'key': 'tags',
            'type': 'select',
            'name': _('Tags'),
            'description': _('Filter by Formats'),
            'value_type': 'multiple',
            'options': [
                {'key': '4-koma', 'name': _('4-Koma'), 'default': False},
                {'key': 'adaptation', 'name': _('Adaptation'), 'default': False},
                {'key': 'anthology', 'name': _('Anthology'), 'default': False},
                {'key': 'award-winning', 'name': _('Award Winning'), 'default': False},
                {'key': 'doujinshi', 'name': _('Doujinshi'), 'default': False},
                {'key': 'fan-colored', 'name': _('Fan Colored'), 'default': False},
                {'key': 'full-color', 'name': _('Full Color'), 'default': False},
                {'key': 'long-strip', 'name': _('Long Strip'), 'default': False},
                {
                    'key': 'official-colored',
                    'name': _('Official Colored'),
                    'default': False,
                },
                {'key': 'oneshot', 'name': _('Oneshot'), 'default': False},
                {'key': 'user-created', 'name': _('User Created'), 'default': False},
                {'key': 'web-comic', 'name': _('Webcomic'), 'default': False},
            ],
        },
        {
            'key': 'genres',
            'type': 'select',
            'name': _('Genres'),
            'description': _('Filter by Genres'),
            'value_type': 'multiple',
            'options': [
                {'key': 'action', 'name': _('Action'), 'default': False},
                {'key': 'adult', 'name': _('Adult'), 'default': False},
                {'key': 'adventure', 'name': _('Adventure'), 'default': False},
                {'key': 'comedy', 'name': _('Comedy'), 'default': False},
                {'key': 'crime', 'name': _('Crime'), 'default': False},
                {'key': 'drama', 'name': _('Drama'), 'default': False},
                {'key': 'ecchi', 'name': _('Ecchi'), 'default': False},
                {'key': 'fantasy', 'name': _('Fantasy'), 'default': False},
                {'key': 'gender-bender', 'name': _('Gender Bender'), 'default': False},
                {'key': 'historical', 'name': _('Historical'), 'default': False},
                {'key': 'horror', 'name': _('Horror'), 'default': False},
                {'key': 'isekai', 'name': _('Isekai'), 'default': False},
                {'key': 'magical-girls', 'name': _('Magical Girls'), 'default': False},
                {'key': 'mature', 'name': _('Mature'), 'default': False},
                {'key': 'mecha', 'name': _('Mecha'), 'default': False},
                {'key': 'medical', 'name': _('Medical'), 'default': False},
                {'key': 'mystery', 'name': _('Mystery'), 'default': False},
                {'key': 'philosophical', 'name': _('Philosophical'), 'default': False},
                {'key': 'psychological', 'name': _('Psychological'), 'default': False},
                {'key': 'romance', 'name': _('Romance'), 'default': False},
                {'key': 'sci-fi', 'name': _('Sci-Fi'), 'default': False},
                {'key': 'shoujo-ai', 'name': _('Shoujo Ai'), 'default': False},
                {'key': 'slice-of-life', 'name': _('Slice of Life'), 'default': False},
                {'key': 'sports', 'name': _('Sports'), 'default': False},
                {'key': 'superhero', 'name': _('Superhero'), 'default': False},
                {'key': 'thriller', 'name': _('Thriller'), 'default': False},
                {'key': 'tragedy', 'name': _('Tragedy'), 'default': False},
                {'key': 'wuxia', 'name': _('Wuxia'), 'default': False},
                {'key': 'yaoi', 'name': _('Yaoi'), 'default': False},
                {'key': 'yuri', 'name': _('Yuri'), 'default': False},
            ],
        },
    ]

    def __init__(self) -> None:
        if self.session is None and requests is not None:
            self.session = requests.Session(
                allow_redirects=True,
                impersonate='chrome',
                timeout=(REQUESTS_TIMEOUT, REQUESTS_TIMEOUT * 2)
            )

    def _resolve_chapters(self, comic_hid: str) -> list[dict[str, str]]:
        chapters = []
        page = 1

        while True:
            r = self.session_get(
                self.api_manga_chapters_url.format(hid=comic_hid),
                params={
                    'limit': CHAPTERS_PER_REQUEST,
                    'page': page,
                    'chap-order': 1,
                    'lang': self.lang_code,
                },
            )
            if r.status_code != 200:
                return None

            data = r.json()

            for chapter in data['chapters']:
                title = ''
                if chapter['vol']:
                    title += f'[{chapter["vol"]}] '
                if chapter['chap']:
                    title += f'#{chapter["chap"]} '
                if chapter['title']:
                    title += f'- {chapter["title"]}'

                date = chapter['publish_at'] or chapter['updated_at']

                chapters.append({
                    'slug': chapter['hid'],
                    'title': title,
                    'num': chapter['chap'],
                    'num_volume': chapter['vol'],
                    'date': convert_date_string(date.split('T')[0], format='%Y-%m-%d'),
                    'scanlators': chapter['group_name'],
                })

            if len(chapters) == data['total']:
                break

            page += 1

        return chapters

    def get_manga_data(self, initial_data: dict) -> dict:
        """
        Return manga data from the API.

        :param initial_data: Contains the following fields:
            - slug
            - name
            - cover
            - last_chapter
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(
            self.api_manga_url.format(slug=initial_data['slug']),
            params={
                'tachiyomi': 'false',
            },
        )
        if r.status_code != 200:
            return None

        resp_json = r.json()

        data = initial_data.copy()
        data.update({
            'authors': [],
            'scanlators': [],
            'genres': [],
            'status': None,
            'cover': None,
            'synopsis': None,
            'chapters': [],
            'server_id': self.id,
        })

        comic_data = resp_json['comic']

        data['name'] = comic_data['title']

        # Always grab the last cover.
        data['cover'] = self.image_url.format(b2key=comic_data['md_covers'][-1]['b2key'])

        data['authors'] = [author['name'] for author in resp_json['authors']]
        data['authors'] += [author['name'] for author in resp_json['artists'] if author not in data['authors']]

        data['genres'] = [genre['md_genres']['name'] for genre in comic_data['md_comic_md_genres']]

        match comic_data['status']:
            case 1:
                # Ongoing.
                data['status'] = 'ongoing'
            case 2:
                # Completed.
                data['status'] = 'complete'
            case 3:
                # Cancelled.
                data['status'] = 'suspended'
            case 4:
                # Hiatus.
                data['status'] = 'hiatus'
            case _:
                data['status'] = None

        data['synopsis'] = comic_data.get('desc')

        data['chapters'] += self._resolve_chapters(comic_data['hid'])

        return data

    def get_manga_chapter_data(
        self,
        manga_slug: str,
        manga_name: str,
        chapter_slug: str,
        chapter_url: str,
    ) -> dict:
        """
        Return manga chapter data from the API.
        """
        r = self.session_get(
            self.api_chapter_url.format(hid=chapter_slug),
            params={
                'tachiyomi': 'false',
            },
        )
        if r.status_code == 404:
            raise NotFoundError
        if r.status_code != 200:
            return None

        chapter_data = r.json()['chapter']

        title = ''
        if chapter_data['vol']:
            title += f'[{chapter_data["vol"]}] '
        if chapter_data['chap']:
            title += f'#{chapter_data["chap"]} '
        if chapter_data['title']:
            title += f'- {chapter_data["title"]}'

        pages = [
            {
                'slug': page['b2key'],
                'image': None,
            }
            for page in chapter_data['md_images']
        ]

        date = chapter_data['publish_at'] or chapter_data['updated_at']
        scanlators = chapter_data['group_name']

        return {
            'num': chapter_data['chap'],
            'num_volume': chapter_data['vol'],
            'title': title,
            'pages': pages,
            'date': convert_date_string(date.split('T')[0], format='%Y-%m-%d'),
            'scanlators': scanlators,
        }

    def get_manga_chapter_page_image(
        self, manga_slug: str, manga_name: str, chapter_slug: str, page: dict
    ) -> dict:
        """
        Return chapter page scan (image) content.
        """
        r = self.session_get(self.image_url.format(b2key=page['slug']))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return {
            'buffer': r.content,
            'mime_type': mime_type,
            'name': page['slug'],
        }

    def get_manga_url(self, slug: str, url: str) -> str:
        """
        Return manga absolute URL.
        """
        return self.manga_url.format(slug=slug)

    def get_latest_updates(
        self,
        ratings: list[str] | None = None,
        statuses: list[str] | None = None,
        publication_demographics: str | None = None,
        tags: list[str] | None = None,
        genres: list[str] | None = None,
        origination: list[str] | None = None,
        countries: list[str] | None = None,
    ) -> list[dict]:
        params = {
            'lang': [self.lang_code],
            'order': 'new',
            'accept_erotic_content': 'true' if 'erotica' in ratings else 'false',
            'tachiyomi': 'false',
        }

        if origination:
            params['type'] = origination

        r = self.session_get(self.api_latest_chapters_url, params=params)
        if r.status_code != 200:
            return None

        # Use a dictionary to only have unique entries and to store the comic attributes.
        comics = {}
        for chapter in r.json():
            comic = chapter['md_comics']
            if comic['id'] in comics:
                continue

            if comic['title']:
                if comic['md_covers']:
                    cover_b2key = comic['md_covers'][-1]['b2key']
                else:
                    cover_b2key = None

                comics[comic['id']] = {
                    'slug': comic['slug'],
                    'name': comic['title'],
                    'cover': self.image_url.format(b2key=cover_b2key) if cover_b2key else None,
                    'last_chapter': comic['last_chapter'],
                }
            else:
                logger.warning('Ignoring result {}, missing name'.format(comic['id']))

        return list(comics.values())

    def get_most_populars(
        self,
        ratings: list[str] | None = None,
        statuses: list[str] | None = None,
        publication_demographics: str | None = None,
        tags: list[str] | None = None,
        genres: list[str] | None = None,
        origination: list[str] | None = None,
        countries: list[str] | None = None,
    ) -> list[dict]:
        return self.search(
            None,
            ratings=ratings,
            statuses=statuses,
            publication_demographics=publication_demographics,
            tags=tags,
            genres=genres,
            countries=countries,
            orderby='view',
        )

    def search(
        self,
        term,
        ratings: list[str] | None = None,
        statuses: list[str] | None = None,
        publication_demographics: str | None = None,
        tags: list[str] | None = None,
        genres: list[str] | None = None,
        origination: list[str] | None = None,
        countries: list[str] | None = None,
        orderby: str | None = None,
    ) -> list[dict]:
        params = {
            'genres': genres,
            'tags': tags,
            'demographic': publication_demographics,
            'limit': SEARCH_RESULTS_LIMIT,
            'tachiyomi': 'false',
        }

        if countries:
            params['country'] = countries

        if statuses:
            # The API only accepts one status.
            params['status'] = statuses[0]

        if ratings:
            # The API only accepts one content rating.
            params['content_ratings'] = ratings[0]

        if orderby:
            params['sort'] = orderby
        else:
            params['sort'] = 'view'

        if term:
            params['q'] = term

        r = self.session_get(self.api_search_url, params=params)
        if r.status_code != 200:
            return None

        results = []
        for comic in r.json():
            if comic['title']:
                if comic['md_covers']:
                    cover_b2key = comic['md_covers'][-1]['b2key']
                else:
                    cover_b2key = None

                results.append({
                    'slug': comic['slug'],
                    'name': comic['title'],
                    'cover': self.image_url.format(b2key=cover_b2key) if cover_b2key else None,
                    'last_chapter': comic['last_chapter'],
                })
            else:
                logger.warning('Ignoring result {}, missing name'.format(comic['id']))

        return results


class Comick_cs(Comick):
    id = 'comick_cs'
    name = SERVER_NAME
    lang = 'cs'
    lang_code = 'cs'


class Comick_de(Comick):
    id = 'comick_de'
    name = SERVER_NAME
    lang = 'de'
    lang_code = 'de'


class Comick_es(Comick):
    id = 'comick_es'
    name = SERVER_NAME
    lang = 'es'
    lang_code = 'es'


class Comick_es_419(Comick):
    id = 'comick_es_419'
    name = SERVER_NAME
    lang = 'es_419'
    lang_code = 'es-la'


class Comick_fr(Comick):
    id = 'comick_fr'
    name = SERVER_NAME
    lang = 'fr'
    lang_code = 'fr'


class Comick_id(Comick):
    id = 'comick_id'
    name = SERVER_NAME
    lang = 'id'
    lang_code = 'id'


class Comick_it(Comick):
    id = 'comick_it'
    name = SERVER_NAME
    lang = 'it'
    lang_code = 'it'


class Comick_ja(Comick):
    id = 'comick_ja'
    name = SERVER_NAME
    lang = 'ja'
    lang_code = 'ja'


class Comick_ko(Comick):
    id = 'comick_ko'
    name = SERVER_NAME
    lang = 'ko'
    lang_code = 'kr'


class Comick_nl(Comick):
    id = 'comick_nl'
    name = SERVER_NAME
    lang = 'nl'
    lang_code = 'nl'


class Comick_pl(Comick):
    id = 'comick_pl'
    name = SERVER_NAME
    lang = 'pl'
    lang_code = 'pl'


class Comick_pt(Comick):
    id = 'comick_pt'
    name = SERVER_NAME
    lang = 'pt'
    lang_code = 'pt'


class Comick_pt_br(Comick):
    id = 'comick_pt_br'
    name = SERVER_NAME
    lang = 'pt_BR'
    lang_code = 'pt-br'


class Comick_ru(Comick):
    id = 'comick_ru'
    name = SERVER_NAME
    lang = 'ru'
    lang_code = 'ru'


class Comick_th(Comick):
    id = 'comick_th'
    name = SERVER_NAME
    lang = 'th'
    lang_code = 'th'


class Comick_uk(Comick):
    id = 'comick_uk'
    name = SERVER_NAME
    lang = 'uk'
    lang_code = 'uk'


class Comick_vi(Comick):
    id = 'comick_vi'
    name = SERVER_NAME
    lang = 'vi'
    lang_code = 'vi'


class Comick_zh_hans(Comick):
    id = 'comick_zh_hans'
    name = SERVER_NAME
    lang = 'zh_Hans'
    lang_code = 'zh'


class Comick_zh_hant(Comick):
    id = 'comick_zh_hant'
    name = SERVER_NAME
    lang = 'zh_Hant'
    lang_code = 'zh-hk'
