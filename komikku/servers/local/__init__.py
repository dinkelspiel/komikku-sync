# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import datetime
from gettext import gettext as _
from io import BytesIO
import logging
import os
import rarfile
import tarfile
import xml.etree.ElementTree as ET
import zipfile

import ebooklib
from ebooklib import epub
from pypdf import PdfReader

from komikku.servers import Server
from komikku.servers.exceptions import ArchiveError
from komikku.servers.exceptions import ArchiveUnrarMissingError
from komikku.servers.exceptions import ServerException
from komikku.servers.utils import convert_date_string
from komikku.utils import concat_images_vertically
from komikku.utils import get_buffer_mime_type
from komikku.utils import get_file_mime_type
from komikku.utils import get_data_dir

IMG_EXTENSIONS = ['bmp', 'gif', 'jpg', 'jpeg', 'png', 'tif', 'tiff', 'webp']

logger = logging.getLogger('komikku.servers.local')


def is_archive(path):
    if zipfile.is_zipfile(path):  # CBZ, EPUB
        return True
    if rarfile.is_rarfile(path):
        return True
    if tarfile.is_tarfile(path):
        return True
    if get_file_mime_type(path) == 'application/pdf':
        return True
    return False


class Archive:
    def __init__(self, path):
        try:
            if get_file_mime_type(path) == 'application/epub+zip':
                self.obj = EPUB(path)

            elif zipfile.is_zipfile(path):
                self.obj = CBZ(path)

            elif rarfile.is_rarfile(path):
                self.obj = CBR(path)

            elif tarfile.is_tarfile(path):
                self.obj = CBT(path)

            elif get_file_mime_type(path) == 'application/pdf':
                self.obj = PDF(path)

        except Exception as e:
            logger.exception(f'Bad/corrupt archive: {path}')
            raise ArchiveError from e

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.obj.close()

    def get_info(self):
        if hasattr(self.obj, 'get_info'):
            return self.obj.get_info()

        # Parse ComicInfo.xml if exists
        data = dict(
            title=None,
            volume=None,
            number=None,
            authors=set(),
            translators=set(),
            genres=set(),
            synopsis=None,
            day=None,
            month=None,
            year=None,
        )
        info_xml = self.get_name_buffer('ComicInfo.xml')
        if not info_xml:
            return data

        tree = ET.ElementTree(ET.fromstring(info_xml))
        root = tree.getroot()

        for info in root.findall('./'):
            if not info.text:
                continue

            if info.tag == 'Title':
                data['title'] = info.text
            elif info.tag == 'Volume':
                data['volume'] = info.text.strip()
            elif info.tag == 'Number':
                data['number'] = info.text.strip()
            elif info.tag in ('Colorist', 'CoverArtist', 'Inker', 'Letterer', 'Penciller', 'Writer'):
                for author in info.text.split(','):
                    data['authors'].add(author.strip())
            elif info.tag == 'Translator':
                for translator in info.text.split(','):
                    data['translators'].add(translator.strip())
            elif info.tag == 'Genre':
                for genre in info.text.split(','):
                    data['genres'].add(genre.strip())
            elif info.tag == 'Manga' and info.text.strip() == 'Yes':
                data['genres'].add('Manga')
            elif info.tag == 'Summary':
                data['synopsis'] = info.text.strip()
            elif info.tag in ('Day', 'Month', 'Year'):
                data[info.tag.lower()] = int(info.text.strip())

        return data

    def get_namelist(self):
        names = []
        for name in self.obj.get_namelist():
            _root, ext = os.path.splitext(name)
            if ext[1:].lower() in IMG_EXTENSIONS:
                names.append(name)

        return sorted(names)

    def get_name_buffer(self, name):
        return self.obj.get_name_buffer(name)


class CBR:
    """Comic Book Rar (CBR) format"""

    def __init__(self, path):
        self.path = path
        self.archive = rarfile.RarFile(self.path)

    def close(self):
        self.archive.close()

    def get_namelist(self):
        return self.archive.namelist()

    def get_name_buffer(self, name):
        try:
            return self.archive.read(name)
        except rarfile.NoRarEntry as e:
            logger.info(f'{self.path}: {e}')
            return None
        except rarfile.RarCannotExec as e:
            logger.exception('Failed to execute unrar command')
            raise ArchiveUnrarMissingError from e
        except Exception as e:
            logger.info(f'{self.path}: {e}')
            raise ServerException(e) from e


class CBT:
    """Comic Book Tar (CBT) format"""

    def __init__(self, path):
        self.path = path
        self.archive = tarfile.open(self.path)

    def close(self):
        self.archive.close()

    def get_namelist(self):
        return self.archive.getnames()

    def get_name_buffer(self, name):
        try:
            with self.archive.extractfile(name) as fp:
                buf = fp.read()
            return buf
        except KeyError as e:
            logger.info(f'{self.path}: {e}')
            return None
        except Exception as e:
            logger.info(f'{self.path}: {e}')
            raise ServerException(e) from e


class CBZ:
    """Comic Book Zip (CBZ) format

    Can also handle EPUB archives if images are well named (use of zero as a prefix to numbers to keep correct order)
    """

    def __init__(self, path):
        self.path = path
        self.archive = zipfile.ZipFile(self.path, allowZip64=True)

    def close(self):
        self.archive.close()

    def get_namelist(self):
        return self.archive.namelist()

    def get_name_buffer(self, name):
        try:
            return self.archive.read(name)
        except KeyError as e:
            logger.info(f'{self.path}: {e}')
            return None
        except Exception as e:
            logger.info(f'{self.path}: {e}')
            raise ServerException(e) from e


class EPUB:
    """EPUB format"""

    def __init__(self, path):
        self.path = path

        reader = epub.EpubReader(path, None)
        self.archive = reader.load()

    def close(self):
        return

    def get_info(self):
        data = dict(
            title=self.archive.get_metadata('DC', 'title')[0][0],
            volume=None,
            number=None,
            authors=set(),
            translators=set(),
            genres=set(),
            synopsis=None,
            day=None,
            month=None,
            year=None,
        )

        if creators := self.archive.get_metadata('DC', 'creator'):
            for creator in creators:
                data['authors'].add(creator[0])

        if descriptions := self.archive.get_metadata('DC', 'description'):
            data['synopsis'] = []
            for description in descriptions:
                for line in description[0].split('\n'):
                    data['synopsis'].append(line.strip())

            data['synopsis'] = '\n'.join(data['synopsis'])

        if date := self.archive.get_metadata('DC', 'date'):
            if len(date[0][0]) == 8:
                data['year'] = int(date[0][0][:4])
                data['month'] = int(date[0][0][4:6])
                data['day'] = int(date[0][0][6:8])
            elif date := convert_date_string(date[0][0]):
                data['year'] = date.year
                data['month'] = date.month
                data['day'] = date.day

        if position := self.archive.get_metadata('OPF', 'group-position'):
            if '.' in position[0][1]['content']:
                data['volume'], data['number'] = position[0][1]['content'].split('.')
            else:
                data['volume'] = position[0][1]['content']

        return data

    def get_namelist(self):
        namelist = []

        for image in self.archive.get_items_of_type(ebooklib.ITEM_COVER):
            namelist.append(image.get_name())

        for image in self.archive.get_items_of_type(ebooklib.ITEM_IMAGE):
            namelist.append(image.get_name())

        return namelist

    def get_name_buffer(self, name):
        try:
            return self.archive.get_item_with_href(name).get_content()
        except Exception as e:
            logger.info(f'{self.path}: {e}')
            raise ServerException(e) from e


class PDF:
    """PDF format"""

    def __init__(self, path):
        self.path = path
        self.archive = PdfReader(self.path)

    def get_namelist(self):
        names = []
        for page_index, page in enumerate(self.archive.pages):
            if page.images:
                # Page image can be split vertically into several images
                images_keys = sorted(page.images.keys())
                name = page.images[images_keys[0]].name
                names.append(f'{page_index}:{",".join(images_keys)}:{name}')  # noqa: E231

        return names

    def get_name_buffer(self, name):
        try:
            page_index, images_keys, _name = name.split(':')
            page_index = int(page_index)
            images_keys = images_keys.split(',')

        except ValueError as e:
            logger.info(f'{self.path}: {e}')
            return None

        except Exception as e:
            logger.info(f'{self.path}: {e}')
            raise ServerException(e) from e

        page = self.archive.get_page(page_index)

        if len(images_keys) == 1:
            buffer = page.images[images_keys[0]].data
        else:
            image = concat_images_vertically(*[page.images[key].image for key in images_keys])

            io_buffer = BytesIO()
            image.save(io_buffer, 'JPEG')
            image.close()

            buffer = io_buffer.getvalue()
            io_buffer.close()

        return buffer


class Local(Server):
    id = 'local'
    name = 'Local'
    description = _('Comics stored locally as archives in CBZ/CBR/CBT or PDF formats')
    lang = ''

    def get_image(self, data, etag=None):
        """ Returns cover image """
        if data is None:
            return None, None, None

        with Archive(data['path']) as archive:
            buffer = archive.get_name_buffer(data['name'])
        if buffer is None:
            return None, None, None

        mime_type = get_buffer_mime_type(buffer)
        if not mime_type.startswith('image'):
            return None, None, None

        return buffer, None, None

    def get_manga_data(self, initial_data):
        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],
            genres=[],
            status=None,
            chapters=[],
            synopsis=None,
            cover=None,
            server_id=self.id,
            url=None,
        ))

        dir_path = os.path.join(get_data_dir(), self.id, data['slug'])
        if not os.path.exists(dir_path):
            return None

        # Chapters
        for _path, _dirs, files in os.walk(dir_path):
            for file in sorted(files):
                path = os.path.join(dir_path, file)
                if not is_archive(os.path.join(dir_path, file)):
                    continue

                try:
                    with Archive(path) as archive:
                        names = archive.get_namelist()

                        # Used some chapters/volumes info to populate comic data
                        info = archive.get_info()
                        for genre in info['genres']:
                            if genre not in data['genres']:
                                data['genres'].append(genre)
                        for author in info['authors']:
                            if author not in data['authors']:
                                data['authors'].append(author)
                        for translator in info['translators']:
                            if translator not in data['scanlators']:
                                data['scanlators'].append(translator)
                        if not data['synopsis'] and info['synopsis']:
                            data['synopsis'] = info['synopsis']

                        # Cover is by default 1st page of 1st chapter/volume (archive)
                        if data['cover'] is None:
                            data['cover'] = dict(
                                path=path,
                                name=names[0],
                            )

                        title = info['title'] or os.path.splitext(file)[0]
                        if info['number']:
                            title = f'{info["number"]} - {title}'
                        if info['volume']:
                            title = f'{title} ({info["volume"]})'

                        date = datetime.date(info['year'], info['month'] or 1, info['day'] or 1) if info['year'] else None

                        chapter = dict(
                            slug=file,
                            title=title,
                            date=date,
                            scanlators=list(info['translators']),
                        )

                        data['chapters'].append(chapter)
                except Exception:
                    logger.exception(f'Failed to retrieve chapters of {data["name"]}')

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        path = os.path.join(get_data_dir(), self.id, manga_slug, chapter_slug)
        if not os.path.exists(path):
            return None

        with Archive(path) as archive:
            names = archive.get_namelist()

        data = dict(
            pages=[],
        )
        for name in names:
            data['pages'].append(dict(
                slug=name,
                image=None,
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        path = os.path.join(get_data_dir(), self.id, manga_slug, chapter_slug)
        if not os.path.exists(path):
            return None

        with Archive(path) as archive:
            content = archive.get_name_buffer(page['slug'])

        mime_type = get_buffer_mime_type(content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=content,
            mime_type=mime_type,
            name=page['slug'],
        )

    def get_manga_url(self, slug, url):
        return None

    def get_latest_updates(self):
        """
        Returns list of latest updated manga
        """
        dir_path = os.path.join(get_data_dir(), self.id)

        result = {}
        for name in os.listdir(dir_path):
            manga_folder = os.path.join(dir_path, name)

            if not os.path.isdir(manga_folder):
                continue

            result[os.path.getmtime(manga_folder)] = dict(
                slug=name,
                name=name,
            )

        return [item for key, item in sorted(result.items(), reverse=True)][:100]

    def search(self, term):
        dir_path = os.path.join(get_data_dir(), self.id)

        result = []
        for name in sorted(os.listdir(dir_path)):
            if not os.path.isdir(os.path.join(dir_path, name)):
                continue

            if term and term.lower() not in name.lower():
                continue

            result.append(dict(
                slug=name,
                name=name,
            ))

        return result
