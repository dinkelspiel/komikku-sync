# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import base64
import json
import re

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type

re_chapter_date = re.compile(r'\d{4}.\d{2}.\d{2}')

# FoOlSlide Open Source online comic management software (NO LONGER MAINTAINED)
# https://github.com/FoolCode/FoOlSlide or https://github.com/chocolatkey/FoOlSlide2 (fork)

# Supported servers:
# Jaimini's Box [EN] (disabled)
# Kirei Cake [EN] (disabled)
# Le Cercle du Scan [FR] (disabled)
# NIFTeam [it]


class FoOlSlide(Server):
    base_url: str
    search_url: str
    manga_list_url: str
    manga_url: str
    chapter_url: str
    latest_updates_url = None

    name_selector = '.title'
    cover_selector = '.thumbnail img'
    details_selector = '.info b'
    synopsis_selector = None
    chapters_list_selector = '.list .element'
    chapters_list_link_selector = '.title > a'
    latest_updates_list_selector = '.group > .title > a'
    search_list_selector = '.group'
    search_last_chapter_selector = '.element .title a'
    search_list_cover_selector = 'img.preview'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'user-agent': USER_AGENT})

        if self.latest_updates_url is None:
            self.latest_updates_url = self.base_url

    @staticmethod
    def decrypt(value):
        """
        Decrypt a string with a circular shift of 13 of [a-zA-Z] characters

        nopqrstuvwxyzabcdefghijklm => abcdefghijklmnopqrstuvwxyz
        """
        dvalue = ''

        for char in value:
            code = ord(char)
            if 65 <= code <= 77 or 97 <= code <= 109:
                dvalue += chr(code + 13)
            elif 78 <= code <= 90 or 110 <= code <= 122:
                dvalue += chr(code - 13)
            else:
                dvalue += char

        return dvalue

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        adult_alert = False
        if soup.find('div', class_='alert'):
            adult_alert = True

            r = self.session_post(self.manga_url.format(initial_data['slug']), data=dict(adult='true'))
            if r is None:
                return None

            soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[self.name, ],
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        data['name'] = soup.select_one(self.name_selector).text.strip()
        if element := soup.select_one(self.cover_selector):
            data['cover'] = element.get('src')

        # Details
        if self.details_selector:
            for element in soup.select(self.details_selector):
                label = element.text
                value = list(element.next_siblings)[0][2:]
                if label in ('Author', 'Artist'):
                    data['authors'].append(value)
                elif label in ('Description', 'Synopsis', 'Trama'):
                    if adult_alert:
                        data['synopsis'] = '{0}\n\n{1}'.format(
                            'ALERT: This series contains mature contents and is meant to be viewed by an adult audience.',
                            value
                        )
                    else:
                        data['synopsis'] = value

        if self.synopsis_selector:
            data['synopsis'] = soup.select_one(self.synopsis_selector).text.strip()

        # Chapters
        for element in reversed(soup.select(self.chapters_list_selector)):
            a_element = element.select_one(self.chapters_list_link_selector)

            title = a_element.text.strip()
            slug = a_element.get('href').split(f'{self.lang}/')[-1][:-1]

            date_match = re.search(re_chapter_date, element.find('div', class_='meta_r').text)
            if date_match:
                date = convert_date_string(date_match.group(), '%Y.%m.%d')
            else:
                date = None

            data['chapters'].append(dict(
                slug=slug,
                date=date,
                title=title,
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_post(
            self.chapter_url.format(manga_slug, chapter_slug),
            data=dict(adult='true'),
            headers={
                'Accept-Encoding': 'gzip, deflate',
                'Accept-Language': '{0}-{1},{0};q=0.9,en-US;q=0.8,en;q=0.7'.format(self.lang, self.lang.upper()),
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        # List of pages is available in JavaScript variable '_0x3320' or 'pages'
        # Walk in all scripts to find it
        pages = None
        for script_element in soup.find_all('script'):
            script = script_element.string
            if script is None:
                continue

            for line in script.split('\n'):
                line = line.strip()
                if line.startswith('var _0x3320'):
                    #
                    # Jaimini's Box
                    #
                    pages = line.split(';')[0].split(',')[1][1:-2]
                    # String is encrypted with a circular shift of 13 for [a-zA-Z] characters
                    pages = self.decrypt(pages)
                    # String is BASE64 encoded
                    pages = base64.b64decode(pages)
                    break

                if line.startswith('var pages'):
                    pages = line.replace('var pages = ', '')[:-1]
                    break

            if pages is not None:
                pages = json.loads(pages)
                break

        if pages is None:
            return None

        data = dict(
            pages=[],
        )
        for page in pages:
            data['pages'].append(dict(
                slug=None,
                image=page['url'],
            ))

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
            name=page['image'].split('?')[0].split('/')[-1],
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_manga_list(self, page=1):
        r = self.session_get('{0}/{1}'.format(self.manga_list_url, page))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select(self.search_list_selector):
            a_element = element.find('div', class_='title').a
            if self.search_list_cover_selector:
                cover_element = element.select_one(self.search_list_cover_selector)
            else:
                cover_element = None
            last_chapter_element = element.select_one(self.search_last_chapter_selector)

            results.append(dict(
                slug=a_element.get('href').split('/')[-2],
                name=a_element.get('title'),
                cover=cover_element.get('src') if cover_element else None,
                last_chapter=last_chapter_element.text.strip() if last_chapter_element else None,
            ))

        return results

    def get_latest_updates(self):
        """
        Returns latest updates
        """
        r = self.session_get(self.latest_updates_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        slugs = []
        for a_element in soup.select(self.latest_updates_list_selector):
            slug = a_element.get('href').split('/')[-2]
            if slug in slugs:
                continue
            results.append(dict(
                slug=slug,
                name=a_element.text.strip(),
            ))
            slugs.append(slug)

        return results

    def get_most_populars(self):
        """
        Returns list of all mangas
        """
        r = self.session_get(self.manga_list_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        nav_buttons = soup.find_all('a', class_='gbutton')
        if nav_buttons:
            nb_pages = int(nav_buttons[0].get('href').split('/')[-2])
        else:
            nb_pages = 1

        results = []
        for index in range(nb_pages):
            results += self.get_manga_list(page=index + 1)

        return results

    def search(self, term):
        r = self.session_post(
            self.search_url,
            data=dict(search=term),
            headers={
                'Accept-Encoding': 'gzip, deflate',
                'Accept-Language': '{0}-{1},{0};q=0.9,en-US;q=0.8,en;q=0.7'.format(self.lang, self.lang.upper()),
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')
        results = []
        for element in soup.select(self.search_list_selector):
            a_element = element.find_all('div')[0].a
            if self.search_list_cover_selector:
                cover_element = element.select_one(self.search_list_cover_selector)
            else:
                cover_element = None
            last_chapter_element = element.select_one(self.search_last_chapter_selector)

            results.append(dict(
                slug=a_element.get('href').split('/')[-2],
                name=element.select_one('.title a').text.strip(),
                cover=cover_element.get('src') if cover_element else None,
                last_chapter=last_chapter_element.text.strip() if last_chapter_element else None,
            ))

        return results
