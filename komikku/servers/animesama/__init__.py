# SPDX-FileCopyrightText: 2023-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.utils import get_buffer_mime_type


class Animesama(Server):
    id = 'animesama'
    name = 'Anime-Sama'
    lang = 'fr'

    base_url = 'https://anime-sama.to'
    logo_url = base_url + '/img/favicon.ico?v=4'
    search_url = base_url + '/catalogue/'
    manga_url = base_url + '/catalogue/{0}/'
    chapter_url = base_url + '/catalogue/{0}/scan/vf/'
    api_chapters_url = base_url + '/s2/scans/get_nb_chap_et_img.php'
    image_url = base_url + '/s2/scans/{0}/{1}/{2}.jpg'
    cover_url = 'https://raw.githubusercontent.com/Anime-Sama/IMG/img/contenu/{0}.jpg'

    long_strip_genres = ['Webcomic']

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Returns manga data from API

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],  # not available
            genres=[],
            status=None,
            cover=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
        ))

        data['name'] = soup.select_one('.oeuvre-right h1').text.strip()
        data['cover'] = self.cover_url.format(data['slug'])

        if element := soup.select_one('.info-grid > .info-lbl:-soup-contains("Créateur") ~ span'):
            data['authors'].append(element.text.strip())

        if element := soup.select_one('.info-grid > .info-lbl:-soup-contains("État") ~ span'):
            status = element.text.strip()
            if status == 'En cours':
                data['status'] = 'ongoing'
            elif status == 'Terminé':
                data['status'] = 'complete'

        for element in soup.select('.genre-pill'):
            data['genres'].append(element.text.strip())

        if element := soup.select_one('div h2:-soup-contains("Synopsis") ~ p'):
            data['synopsis'] = element.text.strip()

        # Chapters
        oeuvre = self.get_manga_oeuvre(data['slug'])
        if oeuvre is None:
            return None

        r = self.session_get(
            self.api_chapters_url,
            params={
                'oeuvre': oeuvre,
            },
            headers={
                'Referer': self.manga_url.format(data['slug']),
            }
        )
        if r.status_code != 200:
            return None

        rjson = r.json()
        if 'error' in rjson:
            return None

        for num in rjson:
            data['chapters'].append(dict(
                slug=num,
                title=f'Chapitre {num}',
                num=num,
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        oeuvre = self.get_manga_oeuvre(manga_slug)
        if oeuvre is None:
            return None

        # Get chapter images
        r = self.session_get(
            self.api_chapters_url,
            params={
                'oeuvre': oeuvre,
            },
            headers={
                'Referer': self.chapter_url.format(manga_slug),
            }
        )
        if r.status_code != 200:
            return None

        rjson = r.json()
        if 'error' in rjson:
            return None

        data = dict(
            pages=[],
        )
        for index in range(1, rjson[chapter_slug] + 1):
            data['pages'].append(dict(
                slug=None,
                image=self.image_url.format(oeuvre, chapter_slug, index),
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            page['image'],
            headers={
                'Referer': self.chapter_url.format(manga_slug),
            },
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

    def get_manga_oeuvre(self, slug):
        r = self.session_get(self.chapter_url.format(slug))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        if element := soup.select_one('#titreOeuvre'):
            return element.text  # beware, no strip here

        return None

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_latest_updates(self, types=None, statuses=None):
        r = self.session_get(self.base_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('#containerAjoutsScans > div'):
            a_element = element.a
            img_element = a_element.img

            if last_element := element.select_one('.card-info .info-text'):
                last_chapter = last_element.text.strip()
            else:
                last_chapter = None

            results.append(dict(
                slug=a_element.get('href').split('/')[-4],
                name=a_element.select_one('.card-title').text.strip(),
                cover=img_element.get('src'),
                last_chapter=last_chapter,
            ))

        return results

    def search(self, term):
        params = {
            'search': term,
            'type[]': 'Scans',
        }

        r = self.session_get(
            self.search_url,
            params=params,
            headers={
                'Referer': self.search_url,
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('#list_catalog > div'):
            a_element = element.a
            img_element = a_element.img

            url = a_element.get('href').strip()
            if url[-1] == '/':
                slug = url.split('/')[-2]
            else:
                slug = url.split('/')[-1]

            results.append(dict(
                slug=slug,
                name=a_element.select_one('.card-title').text.strip(),
                cover=img_element.get('src'),
            ))

        return results
