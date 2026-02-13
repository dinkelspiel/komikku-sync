# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.mangareader import Mangareader


class Mangareaderto(Mangareader):
    id = 'mangareaderto'
    name = 'MangaReader (to)'
    lang = 'en'
    is_nsfw = True
    status = 'disabled'

    languages_codes = dict(
        en='en',
        es='es',
        es_419='es-mx',
        fr='fr',
        ja='ja',
        ko='ko',
        pt='pt',
        pt_BR='pt-br',
        zh_Hans='zh',
    )

    base_url = 'https://mangareader.to'
    logo_url = base_url + '/favicon.ico?v=0.1'
    list_url = base_url + '/filter'
    search_url = base_url + '/search'
    manga_url = base_url + '/{0}'
    chapter_url = base_url + '/read/{0}/{1}/{2}'
    api_chapter_images_url = base_url + '/ajax/image/list/chap/{0}?mode=vertical&quality=medium&hozPageSize=1'


class Mangareaderto_es(Mangareaderto):
    id = 'mangareaderto_es'
    lang = 'es'


class Mangareaderto_es_419(Mangareaderto):
    id = 'mangareaderto_es_419'
    lang = 'es_419'


class Mangareaderto_fr(Mangareaderto):
    id = 'mangareaderto_fr'
    lang = 'fr'


class Mangareaderto_ja(Mangareaderto):
    id = 'mangareaderto_ja'
    lang = 'ja'


class Mangareaderto_ko(Mangareaderto):
    id = 'mangareaderto_ko'
    lang = 'ko'


class Mangareaderto_pt(Mangareaderto):
    id = 'mangareaderto_pt'
    lang = 'pt'


class Mangareaderto_pt_br(Mangareaderto):
    id = 'mangareaderto_pt_br'
    lang = 'pt_BR'


class Mangareaderto_zh_hans(Mangareaderto):
    id = 'mangareaderto_zh_hans'
    lang = 'zh_Hans'
