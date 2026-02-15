# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import datetime
from gettext import gettext as _
import gc
import importlib
import json
import logging
import os
from pathlib import Path
import shutil
import time

from colorthief import ColorThief
from PIL import Image
from PIL import ImageFilter
from PIL import ImageStat

from komikku.consts import COVER_HEIGHT
from komikku.consts import COVER_WIDTH
from komikku.models.database import create_db_connection
from komikku.models.database import insert_row
from komikku.models.database import update_row
from komikku.models.database import update_rows
from komikku.servers.utils import get_server_class_name_by_id
from komikku.servers.utils import get_server_dir_name_by_id
from komikku.servers.utils import get_server_module_name_by_id
from komikku.utils import get_cached_data_dir
from komikku.utils import get_data_dir
from komikku.utils import is_number
from komikku.utils import markdown_to_markup
from komikku.utils import remove_number_leading_zero
from komikku.utils import trunc_filename

logger = logging.getLogger(__name__)


class Manga:
    _chapters = None
    _chapters_scanlators = None
    _server = None

    STATUSES = dict(
        complete=_('Complete'),
        ongoing=_('Ongoing'),
        suspended=_('Suspended'),
        hiatus=_('Hiatus'),
    )

    def __init__(self, server=None):
        if server:
            self._server = server

    @classmethod
    def get(cls, id_, server=None, db_conn=None):
        if db_conn is None:
            db_conn = create_db_connection()
            close_db_conn = True
        else:
            close_db_conn = False

        row = db_conn.execute('SELECT * FROM mangas WHERE id = ?', (id_,)).fetchone()

        if close_db_conn:
            db_conn.close()

        if row is None:
            return None

        manga = cls(server=server)
        for key in row.keys():
            setattr(manga, key, row[key])

        return manga

    @classmethod
    def new(cls, data, server, long_strip_detection):
        data = data.copy()
        chapters = data.pop('chapters')
        cover_url = data.pop('cover')

        # Remove search-specific data not saved in database
        for key in ('nb_chapters', 'nb_volumes', 'last_chapter', 'last_volume'):
            data.pop(key, None)
            continue

        if data.get('synopsis'):
            data['synopsis'] = markdown_to_markup(data['synopsis'])

        # Fill data with internal data
        data.update(dict(
            in_library=0,
            # Add fake last_read date: allows to display recently added manga at the top of the library
            last_read=datetime.datetime.now(datetime.UTC),
        ))

        # Long strip detection (Webtoon)
        if long_strip_detection and server.is_long_strip(data):
            data.update(dict(
                reading_mode='webtoon',
                scaling='width',
            ))

        db_conn = create_db_connection()
        with db_conn:
            id_ = insert_row(db_conn, 'mangas', data)

            rank = 0
            for chapter_data in chapters:
                if not chapter_data.get('date'):
                    # Used today if not date is provided
                    chapter_data['date'] = datetime.date.today()

                chapter = Chapter.new(chapter_data, rank, id_, db_conn)
                if chapter is not None:
                    rank += 1

        db_conn.close()

        manga = cls.get(id_, server)

        if not os.path.exists(manga.path):
            os.makedirs(manga.path)

        manga._save_cover(cover_url)

        return manga

    @property
    def backdrop_colors_css(self):
        cover_path = self.cover_fs_path
        if cover_path is None:
            return None

        path = os.path.join(self.path, 'backdrop_colors.css')
        if os.path.exists(path):
            with open(path) as fp:
                data = fp.read()
                # CSS must be regenerated if old format is detected
                # Named colors are deprecated and will be removed in GTK5
                if '@define-color' not in data:
                    return data

        palette = ColorThief(cover_path).get_palette(color_count=2, quality=1)[:2]
        if len(palette) != 2:
            # Single color image?
            return None

        colors = [':root {\n']
        for index, color in enumerate(reversed(palette)):
            colors.append(f'\t--backdrop-background-color-{index}: rgb({color[0]} {color[1]} {color[2]} / 100%);\n')  # noqa: E702, E231
        colors.append('\t--backdrop-background-color-2: var(--window-bg-color);\n')
        colors.append('}\n')

        with open(path, 'w') as fp:
            fp.writelines(colors)

        return ''.join(colors)

    @property
    def backdrop_image_fs_path(self):
        if self.cover_fs_path is None:
            return None

        path = os.path.join(self.path, 'backdrop_image.jpg')
        if os.path.exists(path):
            return path

        with Image.open(self.cover_fs_path) as image:
            image = image.convert('RGB').filter(ImageFilter.GaussianBlur(35))
            image.save(path, 'JPEG')

        return path

    @property
    def backdrop_info(self):
        if self.backdrop_image_fs_path is None:
            return None

        path = os.path.join(self.path, 'backdrop_info.json')
        if os.path.exists(path):
            with open(path) as fp:
                return json.load(fp)

        with Image.open(self.backdrop_image_fs_path) as image:
            stat = ImageStat.Stat(image.convert('L'))
            info = {
                # Luninance values used to apply an opacity on Picture depending of color scheme (dark/light)
                'luminance': [
                    min((stat.mean[0] + stat.extrema[0][0]) / 510, 0.7),
                    max((stat.mean[0] + stat.extrema[0][1]) / 510, 0.3),
                ]
            }
            with open(path, 'w') as fp:
                json.dump(info, fp)

        return info

    @property
    def categories(self):
        db_conn = create_db_connection()
        rows = db_conn.execute(
            'SELECT c.id FROM categories c JOIN categories_mangas_association cma ON cma.category_id = c.id WHERE cma.manga_id = ?',
            (self.id,)
        )

        categories = []
        for row in rows:
            categories.append(row['id'])

        db_conn.close()

        return categories

    @property
    def chapters(self):
        if self._chapters is None:
            db_conn = create_db_connection()
            if self.sort_order and self.sort_order.endswith('asc'):
                rows = db_conn.execute('SELECT * FROM chapters WHERE manga_id = ? ORDER BY rank ASC', (self.id,))
            else:
                rows = db_conn.execute('SELECT * FROM chapters WHERE manga_id = ? ORDER BY rank DESC', (self.id,))

            self._chapters = []
            for row in rows:
                self._chapters.append(Chapter(row=row, manga=self))

            db_conn.close()

        return self._chapters

    @property
    def chapters_scanlators(self):
        if self._chapters_scanlators is None:
            db_conn = create_db_connection()

            rows = db_conn.execute('SELECT DISTINCT scanlators, count(*) FROM chapters WHERE manga_id = ? GROUP BY scanlators', (self.id,))

            scanlators = {}
            for row in rows:
                if not row[0]:  # None or []
                    # Use 'Unknown' as virtual scanlator for chapters without scanlators defined
                    row = (['Unknown'], row[1])

                for scanlator in row[0]:
                    if scanlator not in scanlators:
                        scanlators[scanlator] = {
                            'name': scanlator,
                            'count': 0,
                        }

                    scanlators[scanlator]['count'] += row[1]

            self._chapters_scanlators = list(scanlators.values()) or None

            db_conn.close()

        return self._chapters_scanlators

    @property
    def class_name(self):
        return get_server_class_name_by_id(self.server_id)

    @property
    def cover_fs_path(self):
        path = os.path.join(self.path, 'cover.jpg')
        if os.path.exists(path):
            return path

        return None

    @property
    def dir_name(self):
        return get_server_dir_name_by_id(self.server_id)

    @property
    def is_local(self):
        return self.server_id == 'local'

    @property
    def module_name(self):
        return get_server_module_name_by_id(self.server_id)

    @property
    def nb_downloaded_chapters(self):
        db_conn = create_db_connection()
        row = db_conn.execute(
            'SELECT count() AS downloaded FROM chapters WHERE manga_id = ? AND downloaded = 1 and read = 0', (self.id,)).fetchone()
        db_conn.close()

        return row['downloaded']

    @property
    def nb_recent_chapters(self):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT count() AS recents FROM chapters WHERE manga_id = ? AND recent = 1', (self.id,)).fetchone()
        db_conn.close()

        return row['recents']

    @property
    def nb_unread_chapters(self):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT count() AS unread FROM chapters WHERE manga_id = ? AND read = 0', (self.id,)).fetchone()
        db_conn.close()

        return row['unread']

    @property
    def last_read_chapter(self):
        db_conn = create_db_connection()
        row = db_conn.execute(
            'SELECT * FROM chapters WHERE manga_id = ? AND last_read IS NOT NULL ORDER BY last_read DESC LIMIT 1', (self.id,)
        ).fetchone()
        db_conn.close()

        return Chapter(row=row, manga=self) if row else None

    @property
    def path(self):
        if self.in_library:
            return os.path.join(get_data_dir(), self.dir_name, trunc_filename(self.name))

        return os.path.join(get_cached_data_dir(), self.dir_name, trunc_filename(self.name))

    @property
    def server(self):
        if self._server is None:
            try:
                module = importlib.import_module('.' + self.module_name, package='komikku.servers')
                self._server = getattr(module, self.class_name)()
            except Exception:
                from komikku.servers import ServerDummy

                self._server = ServerDummy(self.server_id)
                logger.info('Failed to import server: %s', self.class_name)

        return self._server

    def _save_cover(self, url):
        # Covers in landscape format are converted to portrait format
        if self.server.save_image(url, self.path, 'cover', COVER_WIDTH, COVER_HEIGHT):
            # Remove backdrop files (image, css, info)
            for file in Path(self.path).glob('backdrop_*'):
                os.unlink(file)

    def add_in_library(self):
        tmp_path = self.path

        self.update(dict(in_library=True))

        if self.is_local:
            # Move files
            for filename in os.listdir(tmp_path):
                dst_path = os.path.join(self.path, filename)
                if os.path.exists(dst_path):
                    os.remove(dst_path)
                shutil.move(os.path.join(tmp_path, filename), self.path)

            # Remove folder
            shutil.rmtree(tmp_path)
        else:
            # Move folder
            shutil.move(tmp_path, self.path)

    def clear(self):
        # Remove chapters folders
        for path in Path(self.path).glob('*'):
            if path.is_dir():
                shutil.rmtree(path)

        # Set all chapters downloaded flag to 0
        db_conn = create_db_connection()
        with db_conn:
            db_conn.execute('UPDATE chapters SET downloaded = 0 WHERE manga_id = ?', (self.id, ))

        db_conn.close()

        self._chapters = None

    def delete(self, db_conn=None):
        if db_conn is None:
            db_conn = create_db_connection()
            close_db_conn = True
        else:
            close_db_conn = False

        with db_conn:
            db_conn.execute('DELETE FROM mangas WHERE id = ?', (self.id, ))

        if close_db_conn:
            db_conn.close()

        # Delete folder except when server is 'local'
        if os.path.exists(self.path) and not self.is_local:
            shutil.rmtree(self.path)

    def get_next_chapter(self, chapter, direction=1):
        """
        :param chapter: reference chapter
        :param direction: -1 for preceding chapter, 1 for following chapter
        """
        assert direction in (-1, 1), 'Invalid direction value'

        db_conn = create_db_connection()

        op = '>' if direction == 1 else '<'
        order = 'ASC' if direction == 1 else 'DESC'
        if self.filters and self.filters.get('scanlators'):
            # Chapters must be filtered by scanlators (some scanlators are excluded)
            excluded_scanlators = self.filters['scanlators']

            # Subquery to get IDs of not filtered chapters
            scanlators_subquery = f"""
                SELECT DISTINCT c.id
                FROM chapters c, json_each(scanlators)
                WHERE json_each.value NOT IN ("{'", "'.join(excluded_scanlators)}") AND c.manga_id = {self.id}
            """
            if 'Unknown' not in excluded_scanlators:
                # Add chapters without scanlators defined
                scanlators_subquery += f"""
                    UNION
                    SELECT id FROM chapters WHERE (scanlators IS NULL OR scanlators->0 IS NULL) AND manga_id = {self.id}
                """
        else:
            scanlators_subquery = None

        if self.sort_order in ('asc', 'desc', None):
            if scanlators_subquery:
                row = db_conn.execute(
                    f'SELECT * FROM chapters WHERE manga_id = ? AND id IN ({scanlators_subquery}) AND rank {op} ? ORDER BY rank {order}',
                    (self.id, chapter.rank)
                ).fetchone()
            else:
                row = db_conn.execute(
                    f'SELECT * FROM chapters WHERE manga_id = ? AND rank {op} ? ORDER BY rank {order}',
                    (self.id, chapter.rank)
                ).fetchone()

        elif self.sort_order in ('date-asc', 'date-desc'):
            if scanlators_subquery:
                row = db_conn.execute(
                    f'SELECT * FROM chapters WHERE manga_id = ? AND id IN ({scanlators_subquery}) AND date {op} ? ORDER BY date {order}, id {order}',
                    (self.id, chapter.date)
                ).fetchone()
            else:
                row = db_conn.execute(
                    f'SELECT * FROM chapters WHERE manga_id = ? AND date {op} ? ORDER BY date {order}, id {order}',
                    (self.id, chapter.date)
                ).fetchone()

        elif self.sort_order in ('natural-asc', 'natural-desc'):
            if scanlators_subquery:
                row = db_conn.execute(
                    f'SELECT * FROM chapters WHERE manga_id = ? AND id IN ({scanlators_subquery}) AND title {op} ? COLLATE natsort ORDER BY title {order}, id {order}',
                    (self.id, chapter.title)
                ).fetchone()
            else:
                row = db_conn.execute(
                    f'SELECT * FROM chapters WHERE manga_id = ? AND title {op} ? COLLATE natsort ORDER BY title {order}, id {order}',
                    (self.id, chapter.title)
                ).fetchone()

        db_conn.close()

        if not row:
            return None

        return Chapter(row=row, manga=self)

    def toggle_category(self, category_id, active):
        db_conn = create_db_connection()
        with db_conn:
            if active:
                insert_row(db_conn, 'categories_mangas_association', dict(category_id=category_id, manga_id=self.id))
            else:
                db_conn.execute(
                    'DELETE FROM categories_mangas_association WHERE category_id = ? AND manga_id = ?',
                    (category_id, self.id,)
                )

        db_conn.close()

    def update(self, data, db_conn=None):
        """
        Updates specific fields

        :param dict data: fields to update
        :return: True on success False otherwise
        """
        ret = False

        # Update
        for key in data:
            setattr(self, key, data[key])

        if db_conn is None:
            db_conn = create_db_connection()
            close_db_conn = True
        else:
            close_db_conn = False

        with db_conn:
            ret = update_row(db_conn, 'mangas', self.id, data)

        if close_db_conn:
            db_conn.close()

        return ret

    def update_full(self, db_conn=None):
        """
        Updates manga

        :return: True on success False otherwise, chapters_changes, synced
        :rtype: tuple
        """
        chapters_changes = {
            'recent_ids': [],
            'nb_updated': 0,
            'nb_deleted': 0,
        }
        gone_chapters_ranks = []

        def get_free_rank(rank):
            if rank not in gone_chapters_ranks:
                return rank

            return get_free_rank(rank + 1)

        data = self.server.get_manga_data(dict(
            slug=self.slug,
            name=self.name,
            url=self.url,
            last_read=self.last_read
        ))
        gc.collect()

        if data is None:
            return False, chapters_changes, False

        synced = self.server.sync and data['last_read'] != self.last_read

        if db_conn is None:
            db_conn = create_db_connection()
            close_db_conn = True
        else:
            close_db_conn = False

        with db_conn:
            # Update chapters
            chapters_data = data.pop('chapters')

            # First, delete chapters that no longer exist on server EXCEPT those marked as downloaded
            # If server is 'local', chapters are always deleted
            chapters_slugs = [str(chapter_data['slug']) for chapter_data in chapters_data]
            rows = db_conn.execute('SELECT * FROM chapters WHERE manga_id = ?', (self.id,))
            for row in rows:
                if row['slug'] not in chapters_slugs:
                    gone_chapter = Chapter.get(row['id'], manga=self, db_conn=db_conn)
                    if not gone_chapter.downloaded or self.is_local:
                        # Chapter is not downloaded or server is 'local'
                        # Delete chapter
                        gone_chapter.delete(db_conn)
                        chapters_changes['nb_deleted'] += 1

                        logger.warning(
                            '[UPDATE] {0} ({1}): Delete chapter {2} (no longer available)'.format(
                                self.name, self.server_id, gone_chapter.title
                            )
                        )
                    else:
                        # Chapter is downloaded
                        # Keep track of rank because it must not be reused
                        gone_chapters_ranks.append(gone_chapter.rank)

            # Then, add or update chapters
            rank = 0
            for chapter_data in chapters_data:
                row = db_conn.execute(
                    'SELECT * FROM chapters WHERE manga_id = ? AND slug = ?', (self.id, chapter_data['slug'])
                ).fetchone()

                rank = get_free_rank(rank)
                if row:
                    # Update chapter
                    changes = {}

                    # Common fields
                    for key in ('title', 'num', 'num_volume', 'url', 'date', 'scanlators'):
                        if row[key] != chapter_data.get(key):
                            if key in ('num', 'num_volume'):
                                num = str(chapter_data.get(key))
                                changes[key] = remove_number_leading_zero(num) if is_number(num) else None
                            else:
                                changes[key] = chapter_data.get(key)

                    if row['rank'] != rank:
                        changes['rank'] = rank

                    if changes:
                        chapters_changes['nb_updated'] += 1

                    # Sync fields
                    for key in ('last_page_read_index', 'last_read', 'read'):
                        if chapter_data.get(key) and row[key] != chapter_data[key]:
                            changes[key] = chapter_data[key]

                    if changes:
                        update_row(db_conn, 'chapters', row['id'], changes)

                    rank += 1
                else:
                    # Add new chapter

                    # Ensure chapter num and volume num are numbers
                    for key in ('num', 'num_volume'):
                        if chapter_data.get(key) is not None:
                            num = str(chapter_data[key])
                            chapter_data[key] = remove_number_leading_zero(num) if is_number(num) else None

                    # Used today if not date is provided
                    if not chapter_data.get('date'):
                        chapter_data['date'] = datetime.date.today()

                    chapter_data.update(dict(
                        manga_id=self.id,
                        rank=rank,
                        downloaded=chapter_data.get('downloaded', 0),
                        recent=1,
                        read=0,
                    ))
                    id_ = insert_row(db_conn, 'chapters', chapter_data)
                    if id_ is not None:
                        chapters_changes['recent_ids'].append(id_)
                        rank += 1

                        logger.info('[UPDATE] {0} ({1}): Add new chapter {2}'.format(self.name, self.server_id, chapter_data['title']))

            if chapters_changes['recent_ids'] or chapters_changes['nb_updated'] or chapters_changes['nb_deleted']:
                data['last_update'] = datetime.datetime.now(datetime.UTC)

            # Update cover
            cover = data.pop('cover', None)
            if cover:
                self._save_cover(cover)

            # Convert synopsis Markdown links (if any) into HTML <a> tags
            if data.get('synopsis'):
                data['synopsis'] = markdown_to_markup(data['synopsis'])

            # Clear cache
            self._chapters = None
            self._chapters_scanlators = None

            # Store old path
            old_path = self.path

            # Update
            for key in data:
                setattr(self, key, data[key])

            update_row(db_conn, 'mangas', self.id, data)

            if old_path != self.path:
                # Manga name changes, manga folder must be renamed too
                os.rename(old_path, self.path)

        if close_db_conn:
            db_conn.close()

        return True, chapters_changes, synced


class Chapter:
    _manga = None

    def __init__(self, row=None, manga=None):
        if row is not None:
            if manga:
                self._manga = manga
            for key in row.keys():
                setattr(self, key, row[key])

    @classmethod
    def get(cls, id_, manga=None, db_conn=None):
        if db_conn is None:
            db_conn = create_db_connection()
            close_db_conn = True
        else:
            close_db_conn = False

        row = db_conn.execute('SELECT * FROM chapters WHERE id = ?', (id_,)).fetchone()

        if close_db_conn:
            db_conn.close()

        if row is None:
            return None

        return cls(row, manga)

    @classmethod
    def new(cls, data, rank, manga_id, db_conn=None):
        # Fill data with internal data
        data = data.copy()
        data.update(dict(
            manga_id=manga_id,
            rank=rank,
            downloaded=data.get('downloaded', 0),
            recent=0,
            read=0,
        ))

        if db_conn is None:
            db_conn = create_db_connection()
            close_db_conn = True
        else:
            close_db_conn = False

        with db_conn:
            id_ = insert_row(db_conn, 'chapters', data)

        chapter = cls.get(id_, db_conn=db_conn) if id_ is not None else None

        if close_db_conn:
            close_db_conn.close()

        return chapter

    @property
    def clearable(self):
        # Not clearable if server is 'local'
        return os.path.exists(self.path) and not self.is_local

    @property
    def is_local(self):
        return self.manga.is_local

    @property
    def manga(self):
        if self._manga is None:
            self._manga = Manga.get(self.manga_id)

        return self._manga

    @property
    def number(self):
        """ Returns chapter number"""
        if self.num and is_number(self.num):
            return remove_number_leading_zero(self.num)

        logger.warning(f'{self.manga.name} serie ({self.manga.server_id}) do not support tracking (no chapter num)?')

        return None

    @property
    def path(self):
        # BEWARE: self.slug may contain '/' characters
        # os.makedirs() must be used to create chapter's folder
        name = '/'.join([trunc_filename(part) for part in self.slug.split('/')])

        return os.path.join(self.manga.path, name)

    def clear(self, reset=False):
        """
        Clear (erase files on disk) and optionally reset

        :param bool reset: reset
        :return: True on success False otherwise
        """
        if self.clearable:
            shutil.rmtree(self.path)

        data = dict(
            downloaded=0,
        )
        if reset:
            data.update(dict(
                pages=None,
                read_progress=None,
                read=0,
                last_read=None,
                last_page_read_index=None,
            ))

        return self.update(data)

    @staticmethod
    def clear_many(chapters, reset=False):
        # Assume all chapters belong to the same manga
        manga = chapters[0].manga
        ids = []
        data = []

        for chapter in chapters:
            # Delete folder except when server is 'local'
            if os.path.exists(chapter.path) and not manga.is_local:
                shutil.rmtree(chapter.path)

            ids.append(chapter.id)

            updated_data = dict(
                downloaded=0,
            )
            if reset:
                updated_data.update(dict(
                    pages=None,
                    read_progress=None,
                    read=0,
                    last_read=None,
                    last_page_read_index=None,
                ))
            data.append(updated_data)

        db_conn = create_db_connection()
        with db_conn:
            update_rows(db_conn, 'chapters', ids, data)

        db_conn.close()

    def delete(self, db_conn=None):
        if db_conn is None:
            db_conn = create_db_connection()
            close_db_conn = True
        else:
            close_db_conn = False

        with db_conn:
            db_conn.execute('DELETE FROM chapters WHERE id = ?', (self.id, ))

        if close_db_conn:
            db_conn.close()

        if os.path.exists(self.path):
            shutil.rmtree(self.path)

    def get_page(self, index, db_conn=None):
        page_path = self.get_page_path(index)
        if page_path:
            return page_path, None

        page = self.pages[index]

        start = time.perf_counter()
        data = self.manga.server.get_manga_chapter_page_image(self.manga.slug, self.manga.name, self.slug, page)
        rtime = time.perf_counter() - start
        gc.collect()

        if data is None:
            return None, None

        if not os.path.exists(self.path):
            os.makedirs(self.path, exist_ok=True)

        image = data['buffer']
        page_path = os.path.join(self.path, data['name'])
        with open(page_path, 'wb') as fp:
            fp.write(image)

        updated_data = {}

        # If page name can't be retrieved from `image` or `slug`, we store its name
        retrievable = False
        if page.get('image') and data['name'] == page['image'].split('?')[0].split('/')[-1]:
            retrievable = True
        elif page.get('slug') and data['name'] == page['slug'].split('/')[-1]:
            retrievable = True
        if not retrievable:
            self.pages[index]['name'] = data['name']
            updated_data['pages'] = self.pages

        downloaded = len(next(os.walk(self.path))[2]) == len(self.pages)
        if downloaded != self.downloaded:
            updated_data['downloaded'] = downloaded

        if updated_data:
            self.update(updated_data, db_conn=db_conn)

        return page_path, rtime

    def get_page_data(self, index):
        """
        Return page image data: buffer, MIME type, name

        Useful for locally stored manga. Image data (bytes) are retrieved directly from archive.
        """
        return self.manga.server.get_manga_chapter_page_image(self.manga.slug, self.manga.name, self.slug, self.pages[index])

    def get_page_path(self, index):
        if not self.pages:
            return None

        page = self.pages[index]

        # Get image name
        if page.get('name'):
            name = page['name']

        elif page.get('image') and page['image'].split('/')[-1]:
            # Extract from URL (relative or absolute)
            name = page['image'].split('/')[-1]
            # Remove query string
            name = name.split('?')[0]

        elif page.get('slug') and page['slug'].split('/')[-1]:
            name = page['slug'].split('/')[-1]

        else:
            return None

        path = os.path.join(self.path, name)

        return path if os.path.exists(path) else None

    def update(self, data, db_conn=None):
        """
        Updates specific fields

        :param dict data: fields to update
        :return: True on success False otherwise
        """
        ret = False

        for key in data:
            setattr(self, key, data[key])

        if db_conn is None:
            db_conn = create_db_connection()
            close_db_conn = True
        else:
            close_db_conn = False

        with db_conn:
            ret = update_row(db_conn, 'chapters', self.id, data)

        if close_db_conn:
            db_conn.close()

        return ret

    def update_full(self, db_conn=None):
        """
        Updates chapter

        Fetches server and saves chapter data

        :return: True on success False otherwise
        """
        if self.pages:
            return True

        data = self.manga.server.get_manga_chapter_data(self.manga.slug, self.manga.name, self.slug, self.url)
        gc.collect()

        if data is None or not data['pages']:
            return False

        return self.update(data, db_conn=db_conn)
