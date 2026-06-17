# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from urllib.parse import unquote_plus

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type


class Ninemanga(Server):
    id = 'ninemanga'
    name = 'Nine Manga'
    lang = 'en'
    is_nsfw = True
    status = 'disabled'  # Move to https://niadd.com

    base_url = 'https://www.ninemanga.com'
    logo_url = base_url + '/favicon.png'
    search_url = base_url + '/search/'
    latest_updates_url = base_url + '/list/New-Update/'
    most_populars_url = base_url + '/list/Hot-Book/'
    manga_url = base_url + '/manga/{0}.html?waring=1'
    chapter_url = base_url + '/chapter/{0}/{1}-1.html'
    page_url = base_url + '/chapter/{0}/{1}'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers = {
                'User-Agent': USER_AGENT,
                'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8,gl;q=0.7',
            }

    @classmethod
    def get_manga_initial_data_from_url(cls, url):
        return dict(slug=url.split('?')[0].split('/')[-1].replace('.html', ''))

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        if r.url == self.base_url:
            # Manga page doesn't exist, we have been redirected to homepage
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
            cover=None,
        ))

        name = soup.find('div', class_='ttline').h1.text.strip()
        name = name.replace(' Manga', '').replace(' Манга', '')  # cleaning
        data['name'] = name
        data['cover'] = soup.find('a', class_='bookface').img.get('src')

        # Details
        elements = soup.find('ul', class_='message').find_all('li')
        for element in elements:
            label = element.b.text

            if label.startswith(('Author', 'Auteur', 'Autor', 'Автор')):
                data['authors'] = [element.a.text.strip(), ]
            elif label.startswith(('Genre', 'Género', 'Genere', 'Gênero', 'Жанры')):
                for a_element in element.find_all('a'):
                    data['genres'].append(a_element.text)
            elif label.startswith(('Status', 'Statut', 'Estado', 'Stato', 'статус')):
                value = element.find_all('a')[0].text.strip().lower()

                if value in ('ongoing', 'en cours', 'laufende', 'en curso', 'in corso', 'em tradução', 'постоянный'):
                    data['status'] = 'ongoing'
                elif value in ('complete', 'completed', 'complété', 'abgeschlossen', 'completado', 'completato', 'completo', 'завершенный'):
                    data['status'] = 'complete'

        # Synopsis
        synopsis_element = soup.find('p', itemprop='description')
        if synopsis_element:
            synopsis_element.b.extract()
            data['synopsis'] = synopsis_element.text.strip()

        # Chapters
        if div_element := soup.find('div', class_='chapterbox'):
            li_elements = div_element.find_all('li')
            for li_element in reversed(li_elements):
                slug = li_element.a.get('href').split('/')[-1].replace('.html', '')
                data['chapters'].append(dict(
                    slug=slug,
                    title=li_element.a.text.strip(),
                    date=convert_date_string(li_element.span.text.strip(), format='%b %d, %Y'),
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
        options_elements = soup.find('select', id='page').find_all('option')

        data = dict(
            pages=[],
        )
        for option_element in options_elements:
            data['pages'].append(dict(
                slug=option_element.get('value').split('/')[-1],
                image=None,
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        # Scrap HTML page to get image url

        # Don't use `Referer` in headers, otherwise we are redirected to a page to select a mirror
        r = self.session_get(
            self.page_url.format(manga_slug, page['slug']),
            headers={
                'Accept':
                'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'en-US,en;q=0.9,fr;q=0.8,fr-FR;q=0.7',
            }
        )
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')
        url = soup.select_one('#manga_pic_1').get('src')

        # Get scan image
        r = self.session_get(
            url,
            headers={
                'Referer': 'f{self.base_url}/',
            },
            timeout=30
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=url.split('/')[-1],
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def get_latest_updates(self):
        """
        Returns Latest Updates list
        """
        r = self.session_get(self.latest_updates_url)
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.direlist .bookinfo'):
            a_element = element.select_one('.bookname')
            img_element = element.select_one('img')
            last_chapter_a_element = element.select_one('.chaptername')

            name = a_element.text.strip()
            results.append(dict(
                name=name,
                slug=unquote_plus(a_element.get('href')).split('/')[-1][:-5],
                cover=img_element.get('src'),
                last_chapter=last_chapter_a_element.text.replace(name, '').strip(),
            ))

        return results

    def get_most_populars(self):
        """
        Returns Hot manga list
        """
        r = self.session_get(self.most_populars_url)
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.direlist .bookinfo'):
            a_element = element.select_one('.bookname')
            img_element = element.select_one('img')
            last_chapter_a_element = element.select_one('.chaptername')

            name = a_element.text.strip()
            results.append(dict(
                name=name,
                slug=unquote_plus(a_element.get('href')).split('/')[-1][:-5],
                cover=img_element.get('src'),
                last_chapter=last_chapter_a_element.text.replace(name, '').strip(),
            ))

        return results

    def search(self, term):
        r = self.session_get(
            self.search_url,
            params={
                'wd': term,
                # 'type': 'high',  # Advanced search
            },
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
        for element in soup.select('.direlist .bookinfo'):
            a_element = element.select_one('.bookname')
            img_element = element.select_one('img')
            last_chapter_a_element = element.select_one('.chaptername')

            name = a_element.text.strip()
            results.append(dict(
                name=name,
                slug=unquote_plus(a_element.get('href')).split('/')[-1][:-5],
                cover=img_element.get('src'),
                last_chapter=last_chapter_a_element.text.replace(name, '').strip(),
            ))

        return results


class Ninemanga_br(Ninemanga):
    # BEWARE: For historical reasons, Id is ninemanga_br instead of ninemanga_pt_br (idem for class name)
    id = 'ninemanga_br'
    lang = 'pt_BR'

    base_url = 'https://br.ninemanga.com'
    search_url = base_url + '/search/'
    latest_updates_url = base_url + '/list/New-Update/'
    most_populars_url = base_url + '/list/Hot-Book/'
    manga_url = base_url + '/manga/{0}.html?waring=1'
    chapter_url = base_url + '/chapter/{0}/{1}-1.html'
    page_url = base_url + '/chapter/{0}/{1}'


class Ninemanga_de(Ninemanga):
    id = 'ninemanga_de'
    lang = 'de'

    base_url = 'https://de.ninemanga.com'
    search_url = base_url + '/search/'
    latest_updates_url = base_url + '/list/New-Update/'
    most_populars_url = base_url + '/list/Hot-Book/'
    manga_url = base_url + '/manga/{0}.html?waring=1'
    chapter_url = base_url + '/chapter/{0}/{1}-1.html'
    page_url = base_url + '/chapter/{0}/{1}'


class Ninemanga_es(Ninemanga):
    id = 'ninemanga_es'
    lang = 'es'

    base_url = 'https://es.ninemanga.com'
    search_url = base_url + '/search/'
    latest_updates_url = base_url + '/list/New-Update/'
    most_populars_url = base_url + '/list/Hot-Book/'
    manga_url = base_url + '/manga/{0}.html?waring=1'
    chapter_url = base_url + '/chapter/{0}/{1}-1.html'
    page_url = base_url + '/chapter/{0}/{1}'


class Ninemanga_fr(Ninemanga):
    id = 'ninemanga_fr'
    lang = 'fr'

    base_url = 'https://fr.ninemanga.com'
    search_url = base_url + '/search/'
    latest_updates_url = base_url + '/list/New-Update/'
    most_populars_url = base_url + '/list/Hot-Book/'
    manga_url = base_url + '/manga/{0}.html?waring=1'
    chapter_url = base_url + '/chapter/{0}/{1}-1.html'
    page_url = base_url + '/chapter/{0}/{1}'


class Ninemanga_it(Ninemanga):
    id = 'ninemanga_it'
    lang = 'it'

    base_url = 'https://it.ninemanga.com'
    search_url = base_url + '/search/'
    latest_updates_url = base_url + '/list/New-Update/'
    most_populars_url = base_url + '/list/Hot-Book/'
    manga_url = base_url + '/manga/{0}.html?waring=1'
    chapter_url = base_url + '/chapter/{0}/{1}-1.html'
    page_url = base_url + '/chapter/{0}/{1}'


class Ninemanga_ru(Ninemanga):
    id = 'ninemanga_ru'
    lang = 'ru'

    base_url = 'https://ru.ninemanga.com'
    search_url = base_url + '/search/'
    latest_updates_url = base_url + '/list/New-Update/'
    most_populars_url = base_url + '/list/Hot-Book/'
    manga_url = base_url + '/manga/{0}.html?waring=1'
    chapter_url = base_url + '/chapter/{0}/{1}-1.html'
    page_url = base_url + '/chapter/{0}/{1}'
