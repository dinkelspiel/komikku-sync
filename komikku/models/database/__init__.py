# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import datetime
from functools import cache
import json
import logging
import os
import shutil
import threading

from gi.repository import Gio
import natsort
import sqlite3

from komikku.utils import get_cached_data_dir
from komikku.utils import get_data_dir
from komikku.utils import is_flatpak

logger = logging.getLogger(__name__)

db_connections = threading.local()

VERSION = 15


def adapt_date_iso(val):
    """Adapt datetime.date to ISO 8601 date"""
    return val.isoformat()


def adapt_datetime_iso(val):
    """Adapt datetime.datetime to timezone-naive ISO 8601 date"""
    return val.replace(tzinfo=None).isoformat()


def adapt_json(data):
    return (json.dumps(data, sort_keys=True)).encode()


def convert_date(val):
    """Convert ISO 8601 date to datetime.date object"""
    return datetime.date.fromisoformat(val.decode())


def convert_datetime(val):
    """Convert ISO 8601 datetime to datetime.datetime object"""
    return datetime.datetime.fromisoformat(val.decode())


def convert_json(blob):
    return json.loads(blob.decode())


sqlite3.register_adapter(datetime.date, adapt_date_iso)
sqlite3.register_adapter(datetime.datetime, adapt_datetime_iso)
sqlite3.register_adapter(dict, adapt_json)
sqlite3.register_adapter(list, adapt_json)
sqlite3.register_adapter(tuple, adapt_json)
sqlite3.register_converter('date', convert_date)
sqlite3.register_converter('json', convert_json)
sqlite3.register_converter('timestamp', convert_datetime)


def backup_db():
    db_path = get_db_path()

    if os.path.exists(db_path):
        db_conn = create_db_connection()
        if not db_conn:
            logger.info('[SQLite] Failed to backup DB')
            return

        if check_db(db_conn):
            logger.info('Save a DB backup')
            shutil.copyfile(db_path, get_db_backup_path())
        else:
            logger.info('[SQLite] Failed to backup DB')


def check_db(db_conn):
    try:
        res = db_conn.execute('PRAGMA integrity_check').fetchone()  # PRAGMA quick_check

        fk_violations = len(db_conn.execute('PRAGMA foreign_key_check').fetchall())

        ret = res[0] == 'ok' and fk_violations == 0
    except sqlite3.DatabaseError:
        logger.exception('[SQLite] Failed to check DB')
        ret = False

    return ret


def clear_cached_data(manga_in_use=None):
    # Clear chapters cache
    cache_dir_path = get_cached_data_dir()
    for server_name in os.listdir(cache_dir_path):
        server_dir_path = os.path.join(cache_dir_path, server_name)
        if manga_in_use and manga_in_use.path.startswith(server_dir_path):
            for manga_name in os.listdir(server_dir_path):
                manga_dir_path = os.path.join(server_dir_path, manga_name)
                if manga_dir_path != manga_in_use.path:
                    shutil.rmtree(manga_dir_path)
        else:
            shutil.rmtree(server_dir_path)

    # Clear database
    db_conn = create_db_connection()
    with db_conn:
        if manga_in_use:
            db_conn.execute('DELETE FROM mangas WHERE in_library != 1 AND id != ?', (manga_in_use.id, ))
        else:
            db_conn.execute('DELETE FROM mangas WHERE in_library != 1')


def collate_natsort(value1, value2):
    lst = natsort.natsorted([value1, value2], alg=natsort.ns.INT | natsort.ns.IC)
    return -1 if lst[0] == value1 else 1


def create_db_connection(path=None):
    if path is None:
        path = get_db_path()
    elif not os.path.exists(path):
        logger.error('[SQLite] Failed to create DB connection: invalid path %s', path)
        return None

    con = getattr(db_connections, path, None)

    needs_connect = False
    if con is None:
        needs_connect = True
        logger.debug(f'[SQLite] no DB connection exists for path {path} on thread {threading.get_native_id()}, creating new one')
    else:
        try:
            # Use fast query to check if the connection was closed
            con.execute('PRAGMA user_version')
        except sqlite3.ProgrammingError:
            logger.warn('[SQLite] DB connection was closed, reconnecting')
            needs_connect = True

    if needs_connect:
        con = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
        if con is None:
            logger.error('[SQLite] Failed to create DB connection')
            return None

        con.row_factory = sqlite3.Row

        # Enable integrity constraint
        con.execute('PRAGMA foreign_keys = ON')

        # Ensure database can be accessed concurrently
        con.execute('PRAGMA journal_mode = WAL')

        # Perform less disk synchronization, safe under WAL
        con.execute('PRAGMA synchronous = NORMAL')
        con.execute('PRAGMA temp_store = MEMORY')

        # Add natural sort collation
        con.create_collation('natsort', collate_natsort)

        setattr(db_connections, path, con)

    return con


def execute_sql(conn, sql):
    res = True

    c = conn.cursor()

    try:
        c.execute(sql)
        conn.commit()
    except Exception as e:
        logger.error('[SQLite] %s', e)
        res = False

    c.close()

    return res


@cache
def get_db_path():
    app_profile = Gio.Application.get_default().profile

    if is_flatpak() and app_profile == 'beta':
        # In Flathub beta version share same data folder with stable version:
        # ~/.var/app/info.febvre.Komikku/data/
        # So, DB files must have distinct names
        name = 'komikku_beta.db'
    else:
        name = 'komikku.db'

    return os.path.join(get_data_dir(), name)


@cache
def get_db_backup_path():
    app_profile = Gio.Application.get_default().profile

    if is_flatpak() and app_profile == 'beta':
        name = 'komikku_beta_backup.db'
    else:
        name = 'komikku_backup.db'

    return os.path.join(get_data_dir(), name)


def init_db():
    db_conn = create_db_connection()
    if not db_conn:
        return

    db_path = get_db_path()
    db_backup_path = get_db_backup_path()

    if os.path.exists(db_path) and os.path.exists(db_backup_path) and not check_db(db_conn):
        # Restore backup
        logger.info('Restore DB from backup')
        shutil.copyfile(db_backup_path, db_path)

    sql_create_mangas_table = """CREATE TABLE IF NOT EXISTS mangas (
        id integer PRIMARY KEY,
        slug text NOT NULL,
        url text, -- only used in case slug can't be used to forge the url
        server_id text NOT NULL,
        in_library integer,
        name text NOT NULL,
        authors json,
        scanlators json,
        genres json,
        synopsis text,
        status text,
        background_color text,
        borders_crop integer,
        filters json,
        landscape_zoom integer,
        page_numbering integer,
        reading_mode text,
        scaling text,
        scaling_filter text,
        sort_order text,
        last_read timestamp,
        last_update timestamp,
        tracking json,
        UNIQUE (slug, server_id)
    );"""

    sql_create_chapters_table = """CREATE TABLE IF NOT EXISTS chapters (
        id integer PRIMARY KEY,
        manga_id integer REFERENCES mangas(id) ON DELETE CASCADE,
        slug text NOT NULL,
        url text, -- only used in case slug can't be used to forge the url
        title text NOT NULL,
        scanlators json,
        pages json,
        date date,
        num text,
        num_volume text,
        rank integer NOT NULL,
        downloaded integer NOT NULL,
        recent integer NOT NULL,
        read_progress text,
        read integer NOT NULL,
        last_page_read_index integer,
        last_read timestamp,
        UNIQUE (slug, manga_id)
    );"""

    sql_create_downloads_table = """CREATE TABLE IF NOT EXISTS downloads (
        id integer PRIMARY KEY,
        chapter_id integer REFERENCES chapters(id) ON DELETE CASCADE,
        status text NOT NULL,
        percent float NOT NULL,
        errors integer DEFAULT 0,
        date timestamp NOT NULL,
        UNIQUE (chapter_id)
    );"""

    sql_create_categories_table = """CREATE TABLE IF NOT EXISTS categories (
        id integer PRIMARY KEY,
        label text NOT NULL,
        UNIQUE (label)
    );"""

    sql_create_categories_mangas_association_table = """CREATE TABLE IF NOT EXISTS categories_mangas_association (
        category_id integer REFERENCES categories(id) ON DELETE CASCADE,
        manga_id integer REFERENCES mangas(id) ON DELETE CASCADE,
        UNIQUE (category_id, manga_id)
    );"""

    sql_create_indexes = [
        'CREATE INDEX IF NOT EXISTS idx_categories_mangas_association_manga ON categories_mangas_association(manga_id);',
        'CREATE INDEX IF NOT EXISTS idx_chapters_date ON chapters(manga_id, date);',
        'CREATE INDEX IF NOT EXISTS idx_chapters_downloaded ON chapters(manga_id, downloaded, read);',
        'CREATE INDEX IF NOT EXISTS idx_chapters_last_read ON chapters(last_read);',
        'CREATE INDEX IF NOT EXISTS idx_chapters_rank ON chapters(manga_id, rank);',
        'CREATE INDEX IF NOT EXISTS idx_chapters_read ON chapters(manga_id, read);',
        'CREATE INDEX IF NOT EXISTS idx_chapters_recent ON chapters(manga_id, recent);',
        'CREATE INDEX IF NOT EXISTS idx_downloads_date ON downloads(date);',
        'CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(date, status);',
        'CREATE INDEX IF NOT EXISTS idx_mangas_in_library ON mangas(in_library, last_read DESC);',
    ]

    db_version = db_conn.execute('PRAGMA user_version').fetchone()[0]

    execute_sql(db_conn, sql_create_mangas_table)
    execute_sql(db_conn, sql_create_chapters_table)
    execute_sql(db_conn, sql_create_downloads_table)
    execute_sql(db_conn, sql_create_categories_table)
    execute_sql(db_conn, sql_create_categories_mangas_association_table)
    for sql_create_index in sql_create_indexes:
        execute_sql(db_conn, sql_create_index)

    if db_version == 0:
        # First launch
        db_conn.execute('PRAGMA user_version = {0}'.format(VERSION))

    if 0 < db_version <= 1:
        # Version 0.10.0
        if execute_sql(db_conn, 'ALTER TABLE downloads ADD COLUMN errors integer DEFAULT 0;'):
            db_conn.execute('PRAGMA user_version = {0}'.format(2))

    if 0 < db_version <= 2:
        # Version 0.12.0
        if execute_sql(db_conn, 'ALTER TABLE mangas ADD COLUMN borders_crop integer;'):
            db_conn.execute('PRAGMA user_version = {0}'.format(3))

    if 0 < db_version <= 4:
        # Version 0.16.0
        if execute_sql(db_conn, 'ALTER TABLE chapters ADD COLUMN scanlators json;'):
            db_conn.execute('PRAGMA user_version = {0}'.format(5))

    if 0 < db_version <= 5:
        # Version 0.22.0
        if execute_sql(db_conn, 'ALTER TABLE mangas RENAME COLUMN reading_direction TO reading_mode;'):
            db_conn.execute('PRAGMA user_version = {0}'.format(6))

    if 0 < db_version <= 6:
        # Version 0.25.0
        if execute_sql(db_conn, sql_create_categories_table) and execute_sql(db_conn, sql_create_categories_mangas_association_table):
            db_conn.execute('PRAGMA user_version = {0}'.format(7))

    if 0 < db_version <= 7:
        # Version 0.31.0
        ids_mapping = dict(
            jaiminisbox__old='jaiminisbox',
            kireicake='kireicake:jaiminisbox',
            lupiteam='lupiteam:jaiminisbox',
            tuttoanimemanga='tuttoanimemanga:jaiminisbox',

            readcomicsonline='readcomicsonline:hatigarmscans',

            hatigarmscans__old='hatigarmscans',

            edelgardescans='edelgardescans:genkan',
            hatigarmscans='hatigarmscans:genkan',
            hunlightscans='hunlightscans:genkan',
            leviatanscans__old='leviatanscans:genkan',
            leviatanscans_es_old='leviatanscans_es:genkan',
            oneshotscans__old='oneshotscans:genkan',
            reaperscans='reaperscans:genkan',
            thenonamesscans='thenonamesscans:genkan',
            zeroscans='zeroscans:genkan',

            akumanga='akumanga:madara',
            aloalivn='aloalivn:madara',
            apollcomics='apollcomics:madara',
            araznovel='araznovel:madara',
            argosscan='argosscan:madara',
            atikrost='atikrost:madara',
            romance24h='romance24h:madara',
            wakascan='wakascan:madara',
        )
        res = True
        for new, old in ids_mapping.items():
            res &= execute_sql(db_conn, f"UPDATE mangas SET server_id = '{new}' WHERE server_id = '{old}';")  # noqa: E702, E231

        if res:
            db_conn.execute('PRAGMA user_version = {0}'.format(8))

    if 0 < db_version <= 8:
        # Version 0.32.0
        if execute_sql(db_conn, 'ALTER TABLE mangas ADD COLUMN page_numbering integer;'):
            db_conn.execute('PRAGMA user_version = {0}'.format(9))

    if 0 < db_version <= 9:
        # Version 0.35.0
        execute_sql(db_conn, "UPDATE mangas SET server_id = 'reaperscans__old' WHERE server_id = 'reaperscans';")

        if execute_sql(db_conn, 'ALTER TABLE chapters ADD COLUMN last_read timestamp;'):
            db_conn.execute('PRAGMA user_version = {0}'.format(10))

    if 0 < db_version <= 10:
        # Version 1.0.0
        execute_sql(db_conn, 'ALTER TABLE mangas ADD COLUMN landscape_zoom integer;')
        execute_sql(db_conn, 'ALTER TABLE chapters ADD COLUMN read_progress text;')

        # Chapters: move reading status of pages in a new 'read_progress' field
        ids = []
        data = []
        manga_rows = db_conn.execute('SELECT id FROM mangas').fetchall()
        with db_conn:
            for manga_row in manga_rows:
                chapter_rows = db_conn.execute('SELECT * FROM chapters WHERE manga_id = ?', (manga_row['id'],)).fetchall()
                for chapter_row in chapter_rows:
                    if not chapter_row['pages']:
                        continue

                    read_progress = ''
                    for page in chapter_row['pages']:
                        read = page.pop('read', False)
                        read_progress += str(int(read))
                    if '1' in read_progress and '0' in read_progress:
                        ids.append(chapter_row['id'])
                        data.append({'pages': chapter_row['pages'], 'read_progress': read_progress})

            if ids:
                update_rows(db_conn, 'chapters', ids, data)

            db_conn.execute('PRAGMA user_version = {0}'.format(11))

    if 0 < db_version <= 11:
        # Version 1.16.0
        execute_sql(db_conn, 'ALTER TABLE mangas ADD COLUMN in_library integer;')
        execute_sql(db_conn, 'UPDATE mangas SET in_library = 1;')
        db_conn.execute('PRAGMA user_version = {0}'.format(12))

    if 0 < db_version <= 12:
        # Version 1.54.0
        execute_sql(db_conn, 'ALTER TABLE mangas ADD COLUMN scaling_filter text;')
        db_conn.execute('PRAGMA user_version = {0}'.format(13))

    if 0 < db_version <= 13:
        # Version 1.60.0
        execute_sql(db_conn, 'ALTER TABLE mangas ADD COLUMN tracking json;')
        execute_sql(db_conn, 'ALTER TABLE chapters ADD COLUMN num text;')
        execute_sql(db_conn, 'ALTER TABLE chapters ADD COLUMN num_volume text;')
        db_conn.execute('PRAGMA user_version = {0}'.format(14))

    if 0 < db_version <= 14:
        # Version 1.70.0
        execute_sql(db_conn, 'ALTER TABLE mangas ADD COLUMN filters json;')
        db_conn.execute('PRAGMA user_version = {0}'.format(15))

    logger.info('DB version {0}'.format(db_conn.execute('PRAGMA user_version').fetchone()[0]))


def delete_rows(db_conn, table, ids):
    seq = []
    if isinstance(ids[0], dict):
        # Several keys (secondary) are used to delete a row
        sql = 'DELETE FROM {0} WHERE {1}'.format(table, ' AND '.join(f'{skey} = ?' for skey in ids[0].keys()))

        for item in ids:
            seq.append(tuple(item.values()))
    else:
        sql = 'DELETE FROM {0} WHERE id = ?'.format(table)

        for id_ in ids:
            seq.append((id_, ))

    try:
        db_conn.executemany(sql, seq)
    except Exception as e:
        logger.error('[SQLite] %s %s', e, ids)
        return False
    else:
        return True


def insert_row(db_conn, table, data):
    try:
        cursor = db_conn.execute(
            'INSERT INTO {0} ({1}) VALUES ({2})'.format(table, ', '.join(data.keys()), ', '.join(['?'] * len(data))),
            tuple(data.values())
        )
    except Exception as e:
        logger.error('[SQLite] %s %s', e, data)
        return None
    else:
        return cursor.lastrowid


def insert_rows(db_conn, table, data):
    sql = 'INSERT INTO {0} ({1}) VALUES ({2})'.format(table, ', '.join(data[0].keys()), ', '.join(['?'] * len(data[0])))

    seq = []
    for item in data:
        seq.append(tuple(item.values()))

    try:
        db_conn.executemany(sql, seq)
    except Exception as e:
        logger.error('[SQLite] %s %s', e, data)
        return False
    else:
        return True


def update_row(db_conn, table, id_, data):
    try:
        db_conn.execute(
            'UPDATE {0} SET {1} WHERE id = ?'.format(table, ', '.join(k + ' = ?' for k in data)),
            tuple(data.values()) + (id_,)
        )
    except Exception as e:
        logger.error('[SQLite] %s %s', e, data)
        return False
    else:
        return True


def update_rows(db_conn, table, ids, data):
    sql = 'UPDATE {0} SET {1} WHERE id = ?'.format(table, ', '.join(k + ' = ?' for k in data[0]))

    seq = []
    for index, id_ in enumerate(ids):
        seq.append(tuple(data[index].values()) + (id_, ))

    try:
        db_conn.executemany(sql, seq)
    except Exception as e:
        logger.error('[SQLite] %s %s', e, data)
        return False
    else:
        return True
