# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

# Supported servers:
# DocTruyen3Q [VI]
# JManga [JA] (disabled)
# Read Comics Free [EN] (disabled)
# Xoxocomics [EN]

import time
from urllib.parse import parse_qs
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests

from komikku.consts import DOWNLOAD_MAX_DELAY
from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.servers.utils import get_soup_element_inner_text
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number
from komikku.utils import get_response_elapsed
from komikku.webview import CompleteChallenge

# WPComics Wordpress theme


class WPComics(Server):
    base_url: str = None
    search_url: str = None
    latest_updates_url: str = None
    most_populars_url: str = None
    manga_url: str = None
    chapter_url: str = None

    chapters_name: str = 'issue'
    date_format: str = '%m/%d/%Y'
    ignore_images_status_code: bool = False
    image_src_attrs: list = ['data-original']
    slug_segments: int = 1

    details_name_selector: str = None
    details_cover_selector: str = None
    details_status_selector: str = None
    details_authors_selector: str = None
    details_genres_selector: str = None
    details_synopsis_selector: str = None

    results_selector: str = '.items .item'
    results_latest_selector: str = '.list-chapter .row'
    results_link_selector: str = None
    results_cover_img_selector: str = None
    results_last_chapter_link_selector: str = None
    results_last_chapter_lastest_updates_link_selector: str = None

    chapters_selector: str = '#nt_listchapter ul li.row'

    def __init__(self):
        if self.session is None and not self.has_cf:
            self.session = requests.Session()
            self.session.headers = {
                'User-Agent': USER_AGENT,
            }

    @CompleteChallenge()
    def get_manga_data(self, initial_data):
        """
        Returns comic data by scraping manga HTML page content

        Initial data should contain at least comic's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug'], 1))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],  # not available
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        soup = BeautifulSoup(r.text, 'lxml')

        data['name'] = soup.select_one(self.details_name_selector).text.strip()
        data['cover'] = soup.select_one(self.details_cover_selector).get('src')

        if self.details_status_selector:
            if element := soup.select_one(self.details_status_selector):
                status = element.text.strip().lower()
                if status in ('completed', '完結済み'):
                    data['status'] = 'complete'
                elif status in ('ongoing', '連載中'):
                    data['status'] = 'ongoing'

        if self.details_authors_selector:
            if elements := soup.select(self.details_authors_selector):
                for element in elements:
                    # elements can be <a> or <p>
                    if element.name == 'p':
                        for author in element.text.strip().split(' - '):
                            data['authors'].append(author.strip())
                    else:
                        data['authors'].append(element.text.strip())

        if a_elements := soup.select(self.details_genres_selector):
            for a_element in a_elements:
                data['genres'].append(a_element.text.strip())

        if element := soup.select_one(self.details_synopsis_selector):
            data['synopsis'] = get_soup_element_inner_text(element, recursive=False)

        # Chapters
        data['chapters'] = self.get_manga_chapters_data(data['slug'], soup=soup)

        return data

    @CompleteChallenge()
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns comic chapter data

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
        for index, element in enumerate(soup.select('.page-chapter')):
            if not element.get('id') or not element.get('id').startswith('page'):
                continue

            image = None
            for attr in self.image_src_attrs:
                if image := element.img.get(attr):
                    break
            if image and image.startswith('//'):
                image = f'https:{image}'  # noqa: E231

            data['pages'].append(dict(
                slug=None,
                image=image,
                index=index + 1,
            ))

        return data

    def get_manga_chapters_data(self, slug, soup=None):
        """
        Returns manga chapters
        """
        def get_page(page, slug, soup=None):
            if soup is None and page is not None:
                r = self.session_get(
                    self.manga_url.format(slug),
                    params={
                        'page': page,
                    }
                )
                if r.status_code != 200:
                    return None

                mime_type = get_buffer_mime_type(r.content)
                if mime_type != 'text/html':
                    return None

                rtime = get_response_elapsed(r)
                soup = BeautifulSoup(r.text, 'lxml')
            else:
                rtime = 0

            items = []
            for li_element in soup.select(self.chapters_selector):
                if 'heading' in li_element.get('class'):
                    continue

                a_element = li_element.select_one('div a')
                url = a_element.get('href')
                slug = url.split('/')[-1]
                num = slug.split('-')[-1] if slug.startswith(f'{self.chapters_name}-') else None
                date = li_element.select_one('div:last-child').text.strip()

                items.append(dict(
                    slug=url.split('/', len(url.split('/')) - self.slug_segments)[-1],
                    title=a_element.text.strip(),
                    num=num if is_number(num) else None,
                    date=convert_date_string(date, self.date_format),
                ))

            if next_element := soup.select_one('.pagination a[rel="next"]'):
                next_url = next_element.get('href')
                next_page = int(parse_qs(urlparse(next_url).query)['page'][0])
                more = next_page > page
            else:
                more = False

            return items, more, rtime

        chapters = []
        delay = None
        more = True
        page = 1
        while more:
            if delay:
                time.sleep(delay)

            items, more, rtime = get_page(page, slug, soup=soup)
            chapters += items
            soup = None

            delay = min(rtime * 4, DOWNLOAD_MAX_DELAY) if rtime else None
            page += 1

        return list(reversed(chapters))

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
        if r.status_code != 200 and not self.ignore_images_status_code:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=f'{page["index"]:04d}.{mime_type.split("/")[-1]}' if page.get('index') else page['image'].split('/')[-1],  # noqa E231
        )

    def get_manga_url(self, slug, url):
        """
        Returns comic absolute URL
        """
        return self.manga_url.format(slug)

    def get_manga_list(self, term=None, orderby=None):
        if term:
            params = {
                'keyword': term,
            }
            url = self.search_url
            results_selector = self.results_selector
            last_chapter_selector = self.results_last_chapter_link_selector
        else:
            params = {}
            if orderby == 'populars':
                url = self.most_populars_url
                results_selector = self.results_selector
                last_chapter_selector = self.results_last_chapter_link_selector
            elif orderby == 'latest':
                url = self.latest_updates_url
                results_selector = self.results_latest_selector
                last_chapter_selector = self.results_last_chapter_lastest_updates_link_selector

        r = self.session.get(
            url,
            params=params,
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select(results_selector):
            a_element = element.select_one(self.results_link_selector)
            img_element = element.select_one(self.results_cover_img_selector)
            if last_chapter_selector:
                last_chapter_element = element.select_one(last_chapter_selector)
            else:
                last_chapter_element = None

            name = a_element.get('title')
            if not name:
                name = a_element.text
            url = a_element.get('href')
            if last_chapter_element:
                last_chapter = last_chapter_element.text.replace(self.chapters_name.capitalize(), '').strip()
            else:
                last_chapter = None

            cover = None
            for attr in self.image_src_attrs:
                if cover := img_element.get(attr):
                    break

            results.append(dict(
                name=name.strip(),
                slug=url.split('/', len(url.split('/')) - self.slug_segments)[-1],
                cover=cover,
                last_chapter=last_chapter,
            ))

        return results

    @CompleteChallenge()
    def get_latest_updates(self):
        return self.get_manga_list(orderby='latest')

    @CompleteChallenge()
    def get_most_populars(self):
        return self.get_manga_list(orderby='populars')

    @CompleteChallenge()
    def search(self, term):
        return self.get_manga_list(term=term)
