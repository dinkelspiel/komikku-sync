# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

# Manga Strean/Manga Reader/Mamga Themesia - WordPress Themes for read manga

# Supported servers:
# Asura Scans For Free [EN] (Disabled)
# Cartel De Manhwas [ES]
# Hijala [AR]
# Iris Scanlator [pt_BR] (Disabled)
# KomikLovers [ID]
# Lelmanga [FR]
# Manga Koleji [TR]
# Neko Scans [ES]
# Noromax [ID]
# Ragna Scan [ES] (Disabled)
# Raiki Scan [ES]
# Raw Manga [JA] (Disabled)
# Rimu Scans [FR] (Disabled)
# Rukav Inari [ES] (Disabled)
# Ryujinmanga [ES]
# Senpai Ediciones [ES] (Disabled)
# ShadowMangas [ES]
# SkyMangas [ES]
# SushiScan [FR]
# Sushiscan (.net) [FR]
# Terco Scans [EN]
# Tres Daos [ES] (Disabled)
# VF Scan [FR] (Disabled)
# Vortex Scans For Free [EN] (Disabled)

from gettext import gettext as _
import json
import re

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.servers.utils import get_soup_element_inner_text
from komikku.utils import get_buffer_mime_type
from komikku.webview import CompleteChallenge


class MangaStream(Server):
    base_url: str
    api_url: str = None
    manga_list_url: str = None
    manga_url: str = None
    chapter_url: str = None

    chapters_order: str = 'desc'
    date_format: str = '%B %d, %Y'
    name_re_sub = str = None  # regexp to clean manga name
    series_name: str = 'manga'
    slug_position: int = -2
    chapter_images_re = r'\"images\":(.*?)}'

    name_selector: str = '.entry-title'
    thumbnail_selector: str = '.thumb img'
    authors_selector: str
    genres_selector: str
    scanlators_selector: str
    status_selector: str
    synopsis_selector: str
    chapter_pages_selector: str = '#readerarea img'

    filters = [
        {
            'key': 'type',
            'type': 'select',
            'name': _('Type'),
            'description': _('Filter by Type'),
            'value_type': 'single',
            'default': '',
            'options': [
                {'key': '', 'name': _('All')},
                {'key': 'manga', 'name': _('Manga')},
                {'key': 'manhwa', 'name': _('Manhwa')},
                {'key': 'manhua', 'name': _('Manhua')},
                {'key': 'comic', 'name': _('Comic')},
            ],
        },
    ]

    ignored_chapters_keywords: list = []
    ignored_pages: list = []

    def __init__(self):
        if self.api_url is None:
            self.api_url = self.base_url + '/wp-admin/admin-ajax.php'

        if self.manga_list_url is None:
            self.manga_list_url = self.base_url + '/' + self.series_name + '/'

        if self.manga_url is None:
            self.manga_url = self.base_url + '/' + self.series_name + '/{0}/'

        if self.chapter_url is None:
            self.chapter_url = self.base_url + '/{chapter_slug}/'

        if self.session is None and not self.has_cf:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    @CompleteChallenge()
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

        def compute_status(label):
            if not label:
                return None

            label = label.strip()

            # Ongoing
            labels = (
                'ongoing',
                'coming soon',
                'mass released',
                'daily release',
                'en curso',  # es
                'en cours',  # fr
                'ativo',  # pt
                'devam ediyor',  # tr
            )
            if any(re.findall('|'.join(labels), label, re.IGNORECASE)):
                return 'ongoing'

            # Complete
            labels = (
                'completed',
                'finalizado',  # es
                'fini',  # fr
                'terminé',  # fr
                'completo',  # pt
                'tamamlandı',  # tr
            )
            if any(re.findall('|'.join(labels), label, re.IGNORECASE)):
                return 'complete'

            # Hiatus
            labels = (
                'hiatus',
                'en pause',  # fr
                'hiato',  # pt
                'bırakıldı',  # tr
            )
            if any(re.findall('|'.join(labels), label, re.IGNORECASE)):
                return 'hiatus'

            # Suspended
            labels = (
                'cancelled',
                'dropped',
                'durduruldu',  # tr
                'ara verildi'  # tr
            )
            if any(re.findall('|'.join(labels), label, re.IGNORECASE)):
                return 'suspended'

            return None

        # Name & cover
        data['name'] = soup.select_one(self.name_selector).text.strip()
        if self.name_re_sub:
            data['name'] = re.sub(self.name_re_sub, '', data['name']).strip()

        if element := soup.select_one(self.thumbnail_selector):
            data['cover'] = element.get('data-src')
            if not data['cover']:
                data['cover'] = element.get('data-lazy-src')
                if not data['cover']:
                    data['cover'] = element.get('src')
            if data['cover'] and not data['cover'].startswith('http'):
                data['cover'] = f'https:{data["cover"]}'  # noqa: E231

        # Details
        if self.authors_selector:
            for element in soup.select(self.authors_selector):
                author = get_soup_element_inner_text(element).strip('-')
                if author and author not in data['authors']:
                    data['authors'].append(author)

        if self.genres_selector:
            for element in soup.select(self.genres_selector):
                genre = element.text.strip()
                if genre and genre not in data['genres']:
                    data['genres'].append(genre)

        if self.scanlators_selector:
            for element in soup.select(self.scanlators_selector):
                if scanlator := get_soup_element_inner_text(element).strip('-'):
                    data['scanlators'].append(scanlator)

        if self.status_selector:
            if element := soup.select_one(self.status_selector):
                data['status'] = compute_status(get_soup_element_inner_text(element))

        if self.synopsis_selector:
            if element := soup.select_one(self.synopsis_selector):
                data['synopsis'] = element.text.strip()

        # Chapters
        data['chapters'] = self.get_manga_chapters_data(soup)

        return data

    def get_manga_chapters_data(self, soup):
        chapters = []

        li_elements = soup.select('#chapterlist ul li')
        if self.chapters_order == 'desc':
            li_elements = reversed(li_elements)

        for li_element in li_elements:
            a_element = li_element.select_one('a')

            slug = a_element.get('href').split('/')[-2]
            ignore = False
            for keyword in self.ignored_chapters_keywords:
                if keyword in slug:
                    ignore = True
                    break
            if ignore:
                continue

            title = ' '.join(li_element.select_one('.chapternum').text.split())
            if date_element := li_element.select_one('.chapterdate'):
                date = convert_date_string(date_element.text.strip(), format=self.date_format)
            else:
                date = None

            chapters.append(dict(
                slug=slug,
                title=title,
                num=li_element.get('data-num').strip(),
                date=date,
            ))

        return chapters

    @CompleteChallenge()
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(
            self.chapter_url.format(manga_slug=manga_slug, chapter_slug=chapter_slug),
            headers={
                'Referer': self.manga_url.format(manga_slug),
            })
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )

        img_elements = soup.select(self.chapter_pages_selector)
        if not img_elements:
            # Pages images are loaded via javascript
            for script_element in soup.find_all('script'):
                script = script_element.string
                if script is None:
                    continue

                for line in script.split('\n'):
                    line = line.strip()
                    if line.startswith('ts_reader'):
                        if matches := re.compile(self.chapter_images_re).search(line):
                            for image in json.loads(matches.group(1)):
                                if image.split('/')[-1] in self.ignored_pages:
                                    continue

                                data['pages'].append(dict(
                                    slug=None,
                                    image=image,
                                ))
                            break
        else:
            for img_element in img_elements:
                image = img_element.get('data-src')
                if not image:
                    image = img_element.get('src')
                    if not image.startswith('http'):
                        image = f'https:{image}'  # noqa: E231
                if image.split('/')[-1] in self.ignored_pages:
                    continue

                data['pages'].append(dict(
                    slug=None,
                    image=image,
                ))

        return data

    @CompleteChallenge()
    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        headers = {
            'Referer': self.chapter_url.format(manga_slug=manga_slug, chapter_slug=chapter_slug),
        }
        r = self.session_get(page['image'], headers=headers)
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

    def get_manga_list(self, title=None, type=None, orderby=None):
        r = self.session_get(
            self.manga_list_url,
            params=dict(
                status='',
                type=type,
                order=orderby or '',
                title=title,
            )
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for a_element in soup.select('.listupd .bs a'):
            name = a_element.get('title')
            if self.name_re_sub:
                name = re.sub(self.name_re_sub, '', name).strip()

            if cover_element := a_element.select_one('img.ts-post-image'):
                if cover_element.get('data-lazy-src'):
                    cover = cover_element.get('data-lazy-src')
                elif cover_element.get('data-src'):
                    cover = cover_element.get('data-src')
                else:
                    cover = cover_element.get('src')
            else:
                continue

            results.append(dict(
                slug=a_element.get('href').split('/')[self.slug_position],
                name=name,
                cover=cover,
            ))

        return results

    @CompleteChallenge()
    def get_latest_updates(self, type):
        return self.get_manga_list(type=type, orderby='update')

    @CompleteChallenge()
    def get_most_populars(self, type):
        return self.get_manga_list(type=type, orderby='popular')

    @CompleteChallenge()
    def search(self, term, type):
        return self.get_manga_list(title=term, type=type)
