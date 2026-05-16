# SPDX-FileCopyrightText: 2024-2024 Zhao Se
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Zhao Se <zhaose233@outlook.com>

import json

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type


class Rawdevart(Server):
    id = 'rawdevart'
    name = 'Rawdevart'
    lang = 'ja'

    is_nsfw = True

    base_url = 'https://rawdevart.art'
    logo_url = base_url + '/logo.png'
    media_url = 'https://s3.rawuwu.com'
    manga_url = base_url + '/{0}'
    api_search_url = base_url + '/ajax/search-manga'
    latest_updates_url = base_url + '/latest'
    api_latest_updates_url = base_url + '/spa/latest-manga'
    api_manga_url = base_url + '/spa/manga/{0}'
    api_chapter_url = api_manga_url + '/{1}'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Get full manga data by parsing the response of the API.
        """
        r = self.session_get(self.api_manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        r_decoded = json.loads(r.text)

        authors = [
            author_info['author_name'] for author_info in r_decoded['authors']
        ]
        genres = [tag_info['tag_name'] for tag_info in r_decoded['tags']]
        synopsis = r_decoded['detail']['manga_description']

        chapters = []
        for chapter_info in reversed(r_decoded['chapters']):
            slug = str(chapter_info['chapter_number'])
            title = f'Chapter {slug}'
            date = convert_date_string(chapter_info['chapter_date_published'].split('T')[0])

            chapters.append(dict(slug=slug, title=title, num=slug, date=date))

        # Slug can't be used to compute manga URL
        # Manga URL must be computed and recorded
        # It's computed using part of cover URL
        manga_url_slug_split = r_decoded['detail']['manga_cover_img_full'].split('/')[-1].split('-')[:-1]
        manga_url_slug_split[-1] = 'c' + manga_url_slug_split[-1]
        manga_url_slug = '-'.join(manga_url_slug_split)

        return dict(
            name=r_decoded['detail']['manga_name'].strip(),
            slug=initial_data['slug'],
            url=self.manga_url.format(manga_url_slug),
            authors=authors,
            genres=genres,
            status=None,  # not available
            synopsis=synopsis,
            chapters=chapters,
            server_id=self.id,
            cover=r_decoded['detail']['manga_cover_img_full'],
        )

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by parsing the response of the API.
        """
        r = self.session_get(self.api_chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        r_decoded = json.loads(r.text)

        soup = BeautifulSoup(r_decoded['chapter_detail']['chapter_content'], 'lxml')

        pages = []
        for index, canvas in enumerate(soup.find_all('canvas')):
            image = canvas.get('data-srcset')
            pages.append(dict(
                image=image,
                server=r_decoded['chapter_detail']['server'],
                index=index + 1,
            ))

        return dict(pages=pages)

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            f'{page.get("server") or self.media_url}/{page["image"]}',
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name='{0:03d}.{1}'.format(page['index'], mime_type.split('/')[-1]),
        )

    def get_manga_url(self, slug, url):
        return url  # It's hard to get the absolute webpage url

    def get_latest_updates(self):
        """
        Returns latest updates
        """
        r = self.session_get(
            self.api_latest_updates_url,
            headers={
                'Referer': self.latest_updates_url,
            }
        )
        if r.status_code != 200:
            return None

        r_decoded = json.loads(r.text)

        results = []
        for manga_info in r_decoded['manga_list']:
            slug = manga_info['manga_id']
            name = manga_info['manga_name']
            cover = manga_info['manga_cover_img']
            if chapters := manga_info.get('manga_chapters'):
                last_chapter = 'Chapter ' + str(chapters[0]['chapter_number'])
            else:
                last_chapter = None

            results.append(dict(
                slug=str(slug),
                name=name,
                cover=cover,
                last_chapter=last_chapter,
            ))

        return results

    def search(self, term=None):
        """
        Search for mangas
        """
        r = self.session_get(self.api_search_url, params=dict(query=term))
        if r.status_code != 200:
            return None

        r_decoded = json.loads(r.text)

        results = []
        for manga_info in r_decoded:
            slug = manga_info['manga_id']
            name = manga_info['manga_name']
            cover = manga_info['manga_cover_img']
            nb_chapters = manga_info['chapter_number']

            results.append(dict(
                slug=str(slug),
                name=name,
                cover=cover,
                nb_chapters=nb_chapters,
            ))

        return results
