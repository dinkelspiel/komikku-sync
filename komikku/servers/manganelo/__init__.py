# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.servers.utils import get_soup_element_inner_text
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number
from komikku.webview import CompleteChallenge

# NOTE: https://mangakakalot.gg seems to be a clone (same IP)
# https://www.mangabats.com
# https://www.natomanga.com


class Manganelo(Server):
    id = 'manganelo'
    name = 'MangaNato (MangaNelo)'
    lang = 'en'

    has_cf = True
    long_strip_genres = ['Webtoons', ]

    base_url = 'https://www.manganato.gg'
    logo_url = base_url + '/images/favicon.ico'
    latest_updates_url = base_url + '/manga-list/latest-manga'
    most_populars_url = base_url + '/manga-list/hot-manga'
    search_url = base_url + '/home/search/json'
    manga_url = base_url + '/manga/{0}'
    chapter_url = base_url + '/manga/{0}/chapter-{1}'
    api_chapters_url = base_url + '/api/manga/{0}/chapters?limit=-1'

    bypass_cf_url = search_url + '?searchword=blossom'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

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
        ))

        # Name & cover
        data['name'] = soup.select_one('.manga-info-text h1').text.strip()
        data['cover'] = soup.select_one('.manga-info-pic img').get('src')

        # Details
        for li_element in soup.select('ul.manga-info-text li'):
            try:
                label, value = li_element.text.split(':', 1)
            except Exception:
                continue

            label = label.strip()

            if label.startswith('Author'):
                data['authors'] = [t.strip() for t in value.split(',') if t.strip() != 'Unknown']
            elif label.startswith('Genres'):
                data['genres'] = [t.strip() for t in value.split(',')]
            elif label.startswith('Status'):
                status = value.strip().lower()
                if status == 'completed':
                    data['status'] = 'complete'
                elif status == 'ongoing':
                    data['status'] = 'ongoing'

        # Synopsis
        data['synopsis'] = get_soup_element_inner_text(soup.select_one('#contentBox'), recursive=False)

        # Chapters
        r = self.session_get(self.api_chapters_url.format(initial_data['slug']))
        if r.status_code != 200:
            return data

        resp_data = r.json()
        if not resp_data.get('success'):
            return data

        for chapter in reversed(resp_data['data']['chapters']):
            data['chapters'].append(dict(
                slug=chapter['chapter_slug'].split('-')[-1],
                title=chapter['chapter_name'].strip(),
                num=chapter['chapter_num'] if is_number(chapter.get('chapter_num')) else None,
                date=convert_date_string(chapter['updated_at'].split('T')[0], format='%Y-%m-%d'),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )
        for img in soup.select('.container-chapter-reader img'):
            data['pages'].append(dict(
                slug=None,  # slug can't be used to forge image URL
                image=img.get('src'),
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            page['image'],
            headers={
                'Accept': 'image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5',
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
            name=page['image'].split('/')[-1],
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_latest_updates(self):
        """
        Returns latest manga list
        """
        return self.get_manga_list(orderby='latest')

    def get_most_populars(self):
        """
        Returns hot manga list
        """
        return self.get_manga_list(orderby='popular')

    def get_manga_list(self, orderby=None):
        """
        Returns hot manga list
        """
        if orderby == 'popular':
            url = self.most_populars_url
        elif orderby == 'latest':
            url = self.latest_updates_url

        r = self.session_get(url)
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.list-comic-item-wrap'):
            link_element = element.h3.a
            link_cover_element = element.a
            last_chapter_link_element = element.select_one('.list-story-item-wrap-chapter')
            results.append(dict(
                name=link_element.get('title').strip(),
                slug=link_element.get('href').split('/')[-1],
                cover=link_cover_element.img.get('src'),
                last_chapter=last_chapter_link_element.text.strip().split()[-1],
            ))

        return results

    @CompleteChallenge()
    def search(self, term):
        r = self.session_get(
            self.search_url,
            params=dict(searchword=term.lower().replace(' ', '_')),
            headers={
                'Referer': f'{self.base_url}/',
                'X-Requested-With': 'XMLHttpRequest',
            }
        )
        if r.status_code != 200:
            return None

        data = r.json()

        results = []
        for item in data:
            results.append(dict(
                slug=item['slug'],
                name=item['name'],
                cover=item['thumb'],
                last_chapter=item['chapterLatest'].split()[-1],
            ))

        return results
