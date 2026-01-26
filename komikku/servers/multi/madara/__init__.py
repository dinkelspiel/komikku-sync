# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

# Madara – WordPress Theme for Manga

# Supported servers:
# 24hRomance [EN] (disabled)
# 3asq [AR] (disabled)
# AkuManga [AR] (disabled)
# Aloalivn [EN] (disabled)
# Apoll Comics [ES]
# ArazNovel [TR] (disabled)
# Argos Scan / Argos Comics [PT] (disabled)
# Asura Scans [TR]
# Atikrost [TR] (disabled)
# Best Manga [RU] (disabled)
# Fr-Scan (Id frdashscan) [FR] (disabled)
# Hunlight Scans [EN] (disabled)
# Leomanga [ES]
# Leviatanscans [EN] (disabled)
# Lovers Toon [pt_BR]
# Manga-Scantrad [FR]
# Mangas Origines [FR]
# MangaWeebs [EN] (disabled)
# Manhuaus [EN]
# Manhwa Hentai [EN] (disabled)
# Phoenix Fansub [ES] (disabled)
# Poseidon Scans [FR] (disabled)
# Reaperscans [AR/FR/ID/TR] (disabled)
# Starbound Scans [FR] (disabled)
# Submanga [ES] (disabled)
# ToonGod [EN]
# Toonily [EN]
# Wakascan [FR] (disabled)
# Webtoon Hatti [TR]

import datetime
from gettext import gettext as _
import logging
import re

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.models import Settings
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.servers.utils import get_soup_element_inner_text
from komikku.servers.utils import remove_emoji_from_string
from komikku.utils import get_buffer_mime_type
from komikku.webview import CompleteChallenge

logger = logging.getLogger('komikku.servers.madara')


class Madara(Server):
    base_url: str = None
    chapter_url: str = None
    chapters_url: str = None

    date_format: str = '%B %d, %Y'
    medium: str = 'manga'
    series_name: str = 'manga'

    results_selector = '.row'
    result_name_slug_selector = '.post-title a'
    result_cover_selector = '.tab-thumb img'

    details_name_selector = 'h1'
    details_cover_selector = '.summary_image > a > img'
    details_authors_selector = '.author-content a, .artist-content a'
    details_scanlators_selector = None
    details_genres_selector = '.genres-content a'
    details_status_selector = '.post-status .summary-content'
    details_synopsis_selector = '.summary__content'

    chapters_list_selector = '#manga-chapters-holder'
    chapters_date_selector = '.chapter-release-date'
    chapters_selector = '.wp-manga-chapter'
    chapters_slug_range = (-2, -1)
    chapters_order = 'desc'

    images_src_attr = 'src'

    def __init__(self):
        self.api_url = self.base_url + '/wp-admin/admin-ajax.php'
        self.manga_url = self.base_url + '/' + self.series_name + '/{0}/'
        if self.chapter_url is None:
            self.chapter_url = self.base_url + '/' + self.series_name + '/{0}/{1}/?style=list'

        if self.session is None and not self.has_cf:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    @staticmethod
    def extract_chapter_nums_from_slug(slug):
        re_nums = r'((\w+)\-(\d+)-)?(\w+)-(\d+)([-_](\d+))?.*'

        if matches := re.search(re_nums, slug):
            if num := matches.group(5):
                num = f'{int(num)}'

                if num_dec := matches.group(7):
                    num = f'{num}.{int(num_dec)}'

                if num_volume := matches.group(3):
                    num_volume = f'{int(num_volume)}'

                return num, num_volume

        return None, None

    @CompleteChallenge()
    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        r = self.session_get(
            self.manga_url.format(initial_data['slug']),
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type not in ('text/html', 'text/plain'):
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
        if r.history and r.history[-1].status_code == 301:
            # Slug has changed
            data['slug'] = r.url.split('/')[-2]

        data['name'] = get_soup_element_inner_text(soup.select_one(self.details_name_selector))
        if cover_element := soup.select_one(self.details_cover_selector):
            data['cover'] = cover_element.get('data-src')
            if data['cover'] is None:
                data['cover'] = cover_element.get('data-lazy-src')
                if data['cover'] is None:
                    data['cover'] = cover_element.get('data-lazy-srcset')
                    if data['cover']:
                        # data-lazy-srcset can contain several covers with sizes: url1 size1 url2 size2...
                        data['cover'] = data['cover'].split()[0]
                    else:
                        data['cover'] = cover_element.get('src')

        # Details
        for element in soup.select(self.details_authors_selector):
            author = element.text.strip()
            if author not in data['authors']:
                data['authors'].append(author)

        if self.details_scanlators_selector:
            for element in soup.select(self.details_scanlators_selector):
                data['scanlators'].append(element.text.strip())

        for element in soup.select(self.details_genres_selector):
            genre = element.text.strip()
            if genre not in data['genres']:
                data['genres'].append(genre)

        if self.details_status_selector:
            if elements := soup.select(self.details_status_selector):
                element = elements[-1]  # get last element (release date is sometimes shown just before)
                status = element.text.strip()
                # Remove emoji
                status = remove_emoji_from_string(status)

                if status in ('Completed', 'Terminé', 'Completé', 'Completo', 'Finalizado', 'Terminado', 'Concluído', 'Tamamlandı', 'مكتملة', 'Закончена'):
                    data['status'] = 'complete'
                elif status in ('OnGoing', 'En Cours', 'En cours', 'Updating', 'Devam Ediyor', 'Em Lançamento', 'Em andamento', 'En curso', 'En Emision', 'En emisión', 'En Emisión', 'مستمرة', 'Продолжается', 'Выпускается'):
                    data['status'] = 'ongoing'
                elif status in ('Canceled', 'Cancelada', 'Cancelado'):
                    data['status'] = 'suspended'
                elif status in ('On Hold', 'En pause', 'En Hiatus', 'En espera'):
                    data['status'] = 'hiatus'

        if self.details_synopsis_selector:
            if summary_container := soup.select_one(self.details_synopsis_selector):
                if p_elements := summary_container.select('p'):
                    synopsis = []
                    for p_element in p_elements:
                        if paragraph := p_element.text.strip():
                            synopsis.append(paragraph)
                    data['synopsis'] = '\n\n'.join(synopsis) if synopsis else None
                else:
                    data['synopsis'] = summary_container.text.strip()

        # Chapters
        chapters_container = soup.select_one(self.chapters_list_selector)
        if chapters_container:
            # Chapters list is empty and is loaded via an Ajax call
            if self.chapters_url:
                r = self.session_post(
                    self.chapters_url.format(data['slug']),
                    headers={
                        'Origin': self.base_url,
                        'Referer': self.manga_url.format(data['slug']),
                        'X-Requested-With': 'XMLHttpRequest',
                    }
                )
            else:
                r = self.session_post(
                    self.api_url,
                    data=dict(
                        action='manga_get_chapters',
                        manga=chapters_container.get('data-id'),
                    ),
                    headers={
                        'Origin': self.base_url,
                        'Referer': self.manga_url.format(data['slug']),
                        'X-rRquested-With': 'XMLHttpRequest',
                    }
                )

            soup = BeautifulSoup(r.text, 'lxml')

        elements = soup.select(self.chapters_selector)
        if self.chapters_order == 'desc':
            elements = reversed(elements)

        for element in elements:
            if element.select_one('i.fa-lock'):
                # Skip premium chapter (LeviatanScans ES for ex.)
                continue

            a_element = element.a
            if view_element := element.find(class_='view'):
                view_element.extract()

            url = a_element.get('href')
            if 'javascript' in url:
                # VIP
                continue

            date_element = element.select_one(self.chapters_date_selector).extract()
            if date := date_element.text.strip():
                date = convert_date_string(date, format=self.date_format, languages=[self.lang])
            else:
                date = datetime.date.today().strftime('%Y-%m-%d')

            slug = url.split('/')[-2]
            num, num_volume = self.extract_chapter_nums_from_slug(slug)

            data['chapters'].append(dict(
                slug=slug,
                title=a_element.text.strip(),
                num=num,
                num_volume=num_volume,
                date=date,
            ))

        return data

    @CompleteChallenge()
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(
            self.chapter_url.format(manga_slug, chapter_slug),
            headers={
                'Referer': self.manga_url.format(manga_slug),
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )
        for index, img_element in enumerate(soup.select_one('.read-container, .reading-content, .image-list').select('img.wp-manga-chapter-img')):
            if img_element.parent.name == 'noscript':
                # In case server uses a second <img> encapsulated in a <noscript> element
                continue

            img_url = img_element.get(self.images_src_attr)
            if img_url is None:
                continue

            data['pages'].append(dict(
                slug=None,
                image=img_url.strip(),
                index=index + 1,
            ))

        return data

    @CompleteChallenge()
    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            page['image'],
            headers={
                'Referer': self.chapter_url.format(manga_slug, chapter_slug),
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
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_latest_updates(self):
        """
        Returns list of latest updates manga
        """
        return self.search('', orderby='latest')

    def get_most_populars(self):
        """
        Returns list of most viewed manga
        """
        return self.search('', orderby='populars')

    @CompleteChallenge()
    def search(self, term, orderby=None):
        data = {
            'action': 'madara_load_more',
            'page': 0,
            'template': 'madara-core/content/content-search',
            'vars[orderby]': 'meta_value_num' if orderby else '',
            'vars[paged]': 0,
            'vars[template]': 'search',
            'vars[post_type]': 'wp-manga',
            'vars[post_status]': 'publish',
            'vars[manga_archives_item_layout]': 'default',
        }

        if self.medium:
            data['vars[meta_query][0][0][value]'] = self.medium  # allows to ignore novels
            data['vars[meta_query][0][orderby]'] = ''
            data['vars[meta_query][0][paged]'] = '0'
            data['vars[meta_query][0][template]'] = 'search'
            data['vars[meta_query][0][meta_query][relation]'] = 'AND'
            data['vars[meta_query][0][post_type]'] = 'wp-manga'
            data['vars[meta_query][0][post_status]'] = 'publish'
            data['vars[meta_query][relation]'] = 'AND'

        if orderby:
            data['vars[order]'] = 'desc'
            data['vars[posts_per_page]'] = 100
            if orderby == 'populars':
                data['vars[meta_key]'] = '_wp_manga_views'
            elif orderby == 'latest':
                data['vars[meta_key]'] = '_latest_update'
        else:
            data['vars[meta_query][0][s]'] = term
            data['vars[s]'] = term

        r = self.session_post(
            self.api_url,
            data=data,
            headers={
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': self.base_url
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select(self.results_selector):
            a_element = element.select_one(self.result_name_slug_selector)
            slug = a_element.get('href').split('/')[-2]
            name = a_element.text.strip()
            if not name or not slug:
                continue

            if cover_img := element.select_one(self.result_cover_selector):
                cover = cover_img.get('data-src')
                if cover is None:
                    cover = cover_img.get('src')

            results.append(dict(
                slug=slug,
                name=name,
                cover=cover,
            ))

        return results


class Madara2(Madara):
    filters = [
        {
            'key': 'nsfw',
            'type': 'checkbox',
            'name': _('NSFW Content'),
            'description': _('Whether to show manga containing NSFW content'),
            'default': False,
        },
    ]

    def __init__(self):
        super().__init__()

        # Update NSFW filter default value according to current settings
        if Settings.instance:
            self.filters[0]['default'] = Settings.get_default().nsfw_content

    @CompleteChallenge()
    def get_latest_updates(self, nsfw):
        """
        Returns list of latest updates manga
        """
        return self.search(None, nsfw=nsfw, orderby='latest')

    @CompleteChallenge()
    def get_most_populars(self, nsfw):
        """
        Returns list of most viewed manga
        """
        return self.search(None, nsfw=nsfw, orderby='populars')

    @CompleteChallenge()
    def search(self, term, nsfw, orderby=None):
        params = {
            's': term or '',
            'post_type': 'wp-manga',
            'op': '',
            'author': '',
            'artist': '',
            'release': '',
            'adult': '' if nsfw else 0,
        }

        if orderby == 'populars':
            params['m_orderby'] = 'views'
        elif orderby == 'latest':
            params['m_orderby'] = 'latest'

        r = self.session_get(f'{self.base_url}/', params=params)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.c-tabs-item__content'):
            thumb_element = element.select_one('.tab-thumb')
            if not thumb_element.a:
                continue

            last_chapter_element = element.select_one('.latest-chap .chapter')
            if cover_element := element.a.img or element.img:
                cover = cover_element.get('data-src')
                if not cover:
                    cover = cover_element.get('src')
            else:
                cover = None

            results.append(dict(
                slug=thumb_element.a.get('href').split('/')[-2],
                name=thumb_element.a.get('title').strip(),
                cover=cover,
                last_chapter=last_chapter_element.text.strip() if last_chapter_element else None,
            ))

        return results
