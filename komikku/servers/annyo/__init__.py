# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _

from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import ServerContent


class Annyo(Server):
    id = 'annyo'
    name = 'Annyo - le mouton a 5 pattes'
    lang = 'fr'
    content = ServerContent(
        type=[_('Webcomic'), _('Self-publishing')],
        license='CC BY-SA'
    )
    true_search = False

    base_url = 'https://annyo.logaton.fr'
    logo_url = base_url + '/themes/margot/images/favicon.png'
    chapters_url = base_url + '/?PagePrincipale'
    image_url = base_url + '/{0}'
    cover_url = base_url + '/cache/PageTitre_Annyo_vignette_140_97_20241006122801_20241006142905.jpg'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """
        Returns comic data by scraping comic HTML page content
        """
        data = initial_data.copy()
        data.update(dict(
            authors=['Kalam'],
            scanlators=[],
            genres=['Écologie', 'Vulgarisation', 'Humour'],
            status='ongoing',
            synopsis="""« Si le berger l’a dit, c’est que c’est comme ça ». Le chien de berger est d’accord. Et aussi l’oiseau que nourrit le berger. Mais il y a ce mouton vert à 5 pattes qui doit toujours ramener sa fraise, ça complique tout. C’était plus simple de penser qu’il fallait donner sa laine et en vouloir aux moutons noirs. Enfin, il est quand même bizarre : il est vert et il a 5 pattes.
N’y voyez aucune similitude avec des situations réelles. Vraiment aucune.""",
            chapters=[],
            server_id=self.id,
            cover=self.cover_url,
        ))

        # Chapters
        r = self.session_get(self.chapters_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        for a_element in reversed(soup.select('.pbgalery-link')):
            date = a_element.get('title')
            data['chapters'].append(dict(
                slug=date.replace('-', ''),
                date=convert_date_string(date, '%Y-%m-%d'),
                title=a_element.h5.text.strip(),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns comic chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.base_url)
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        if a_element := soup.select_one(f'[data-id_fiche="{chapter_slug}"] a.pbgalery-link'):
            return dict(
                pages=[
                    dict(
                        slug=None,
                        image=a_element.get('href'),
                    ),
                ]
            )

        return None

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(self.image_url.format(page['image']))
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
        Returns comic absolute URL
        """
        return self.base_url

    def get_most_populars(self):
        return [dict(
            slug='',
            name='Annyo - le mouton a 5 pattes',
            cover=self.cover_url,
        )]

    def search(self, term=None):
        # This server does not have a search
        # but a search method is needed for `Global Search` in `Explorer`
        # In order not to be offered in `Explorer`, class attribute `true_search` must be set to False

        results = []
        for item in self.get_most_populars():
            if term and term.lower() in item['name'].lower():
                results.append(item)

        return results
