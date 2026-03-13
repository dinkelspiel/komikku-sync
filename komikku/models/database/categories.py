# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from enum import IntEnum
import logging

from komikku.models.database import create_db_connection
from komikku.models.database import insert_row
from komikku.models.database import update_row

logger = logging.getLogger(__name__)


class Category:
    def __init__(self, row=None):
        if row is not None:
            for key in row.keys():
                setattr(self, key, row[key])

    @classmethod
    def get(cls, id_, db_conn=None):
        if db_conn is None:
            db_conn = create_db_connection()

        row = db_conn.execute('SELECT * FROM categories WHERE id = ?', (id_,)).fetchone()

        if row is None:
            return None

        return cls(row)

    @classmethod
    def new(cls, label):
        data = dict(
            label=label,
        )

        db_conn = create_db_connection()
        with db_conn:
            id_ = insert_row(db_conn, 'categories', data)

        category = cls.get(id_, db_conn=db_conn) if id_ is not None else None

        return category

    @property
    def mangas(self):
        db_conn = create_db_connection()
        rows = db_conn.execute('SELECT manga_id FROM categories_mangas_association WHERE category_id = ?', (self.id,)).fetchall()

        return [row['manga_id'] for row in rows] if rows else []

    def delete(self):
        db_conn = create_db_connection()

        with db_conn:
            db_conn.execute('DELETE FROM categories WHERE id = ?', (self.id, ))

    def update(self, data):
        """
        Updates specific fields

        :param dict data: fields to update
        :return: True on success False otherwise
        """
        ret = False

        for key in data:
            setattr(self, key, data[key])

        db_conn = create_db_connection()
        with db_conn:
            ret = update_row(db_conn, 'categories', self.id, data)

        return ret


class CategoryVirtual(IntEnum):
    ALL = 0
    UNCATEGORIZED = -1
