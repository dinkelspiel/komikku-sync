# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

# Supported servers:
# Aurora Scan [pt_BR] (disabled)
# Cerise Scan [pt_BR] (disabled)
# Dango Scan [pt_BR] (disabled)
# Luratoon Scan [pt_BR] (disabled)
# Nazarick Scan [pt_BR]
# RF Dragon Scan [pt_BR]
# Wicked Witch Scan [pt_BR] (disabled)

import base64
from io import BytesIO
import re
from zipfile import ZipFile

from bs4 import BeautifulSoup
from PIL import Image
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.servers.utils import get_soup_element_inner_text
from komikku.utils import get_buffer_mime_type
from komikku.webview import CompleteChallenge

RE_ZIP_IMAGES = re.compile(r'base64,([a-zA-Z0-9+=\/\n]*)')


class Peachscan(Server):
    base_url: str
    search_url: str = None
    latest_updates_url: str = None
    most_populars_url: str = None
    manga_url: str = None
    chapter_url: str = None
    image_url: str = None

    date_format: str = '%d %B %Y'

    def __init__(self):
        if self.session is None and not self.has_cf:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

        if self.search_url is None:
            self.search_url = self.base_url + '/auto-complete/'
        if self.latest_updates_url is None:
            self.latest_updates_url = self.base_url
        if self.most_populars_url is None:
            self.most_populars_url = self.base_url + '/todas-as-obras/'
        if self.manga_url is None:
            self.manga_url = self.base_url + '/{0}/'
        if self.chapter_url is None:
            self.chapter_url = self.base_url + '/{0}/{1}/'
        if self.image_url is None:
            self.image_url = self.base_url + '{0}#page'

    @CompleteChallenge()
    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
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
        ))

        soup = BeautifulSoup(r.text, 'lxml')

        data['name'] = soup.select_one('.desc__titulo__comic').text.strip()
        data['cover'] = self.base_url + soup.select_one('.sumario__img').get('src')

        # Use category as genre
        if element := soup.select_one('.categoria__comic'):
            data['genres'].append(element.text.strip())

        label = None
        for element in soup.select('.sumario__specs .sumario__specs__box'):
            label = element.text.strip()
            value = element.find_next_siblings()[0].text.strip()

            if label.startswith(('Autor',)):
                for author in value.split(','):
                    data['authors'].append(author.strip())

            elif label.startswith(('Gênero',)):
                for genre in value.split():
                    data['genres'].append(genre.strip())

            elif label.startswith(('Status',)):
                if value in ('Em Lançamento',):
                    data['status'] = 'ongoing'
                elif value in ('Finalizado',):
                    data['status'] = 'complete'

        synopsis = []
        for element in soup.select('.sumario__sinopse .sumario__sinopse__texto'):
            synopsis.append(element.text.strip())
        if synopsis:
            data['synopsis'] = '\n\n'.join(synopsis)

        # Chapters
        for element in reversed(soup.select('.link__capitulos')):
            date = None
            if element.parent.name == 'abbr':
                # New chapters are encapsulated in a <abbr> element and date is in `title` attribute
                date = element.parent.get('title')
            elif date_element := element.select_one('.data__lançamento'):
                date = date_element.text

            if date:
                date = date.split()  # Ex. 15 de Maio de 2024 às 16:35
                date = f'{date[0]} {date[2]} {date[4]}'

            slug = element.get('href').split('/')[-2]

            data['chapters'].append(dict(
                slug=slug,
                title=element.select_one('.numero__capitulo').text.strip(),
                num=f'{int(slug)}',
                date=convert_date_string(date, format=self.date_format, languages=[self.lang]),
            ))

        return data

    @CompleteChallenge()
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )

        for script_element in soup.find_all('script'):
            script = script_element.string
            if not script or 'urls' not in script:
                continue

            for line in script.split('\n'):
                for sline in line.split(';'):
                    if 'urls' not in sline:
                        continue

                    urls = sline.split('=')[1].strip()[1:-1].split(',')
                    for index, url in enumerate(urls):
                        data['pages'].append(dict(
                            slug=None,
                            image=url.strip().strip("'"),
                            index=index + 1,
                        ))

                    break

                if data['pages']:
                    break

        return data

    @CompleteChallenge()
    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            self.image_url.format(page['image']),
            headers={
                'Referer': self.chapter_url.format(manga_slug, chapter_slug),
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type == 'application/zip' or page['image'].endswith('.zip'):
            # Image is cut into several chunks stored in a ZIP archive
            chunks = []
            with ZipFile(BytesIO(r.content), 'r') as zip:
                # Read files
                for name in zip.namelist():
                    _index, type = name.split('.')
                    with zip.open(name=name, mode='r') as fp:
                        data = fp.read()

                    if type == 's':
                        # image data in a SVG
                        data = data.decode('utf-8')
                        if matches := RE_ZIP_IMAGES.search(data):
                            chunks.append(base64.b64decode(matches.group(1)))
                    else:
                        chunks.append(data)

            # Load image chunks and compute its size
            width, height = 0, 0
            img_chunks = []
            for chunk in chunks:
                img_chunk = Image.open(BytesIO(chunk))
                img_chunks.append(img_chunk)
                width = max(width, img_chunk.width)
                height += img_chunk.height

            # Put chunks back together
            image = Image.new('RGB', (width, height))
            y = 0
            for img_chunk in img_chunks:
                x = (img_chunk.width - width) / 2
                image.paste(img_chunk, (int(x), y))
                y += img_chunk.height

            io_buffer = BytesIO()
            image.save(io_buffer, 'png')

            buffer = io_buffer.getvalue()
            ext = 'png'

        elif mime_type.startswith('image'):
            buffer = r.content
            ext = mime_type.split('/')[-1]

        else:
            return None

        return dict(
            buffer=buffer,
            mime_type=mime_type,
            name=f'{page["index"]:03d}.{ext}',  # noqa: E231
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    @CompleteChallenge()
    def get_latest_updates(self):
        r = self.session_get(self.latest_updates_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.all__comics .comic'):
            last_chapter_element = element.select_one('.capitulo__comic')

            results.append({
                'slug': element.a.get('href').split('/')[-2],
                'name': element.h2.text.strip(),
                'cover': self.base_url + element.a.img.get('src'),
                'last_chapter': get_soup_element_inner_text(last_chapter_element, recursive=False).replace('Cap ', '') if last_chapter_element else None,
            })

        return results

    @CompleteChallenge()
    def get_most_populars(self):
        r = self.session_get(self.most_populars_url)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for element in soup.select('.comics__all__box'):
            img_element = element.select_one('.box-image img')
            a_element = element.select_one('.titulo__comic__allcomics')

            results.append({
                'slug': a_element.get('href').split('/')[-2],
                'name': a_element.text.strip(),
                'cover': self.base_url + img_element.get('src'),
            })

        return results

    @CompleteChallenge()
    def search(self, term):
        r = self.session_get(
            self.search_url,
            params={
                'term': term,
            },
            headers={
                'Referer': f'{self.base_url}/',
            }
        )
        if r.status_code != 200:
            return None

        results = []
        for item in r.json():
            soup = BeautifulSoup(item['html'], 'lxml')
            results.append({
                'slug': soup.a.get('href').split('/')[-2],
                'name': soup.a.span.text.strip(),
                'cover': self.base_url + soup.a.img.get('src'),
            })

        return results
