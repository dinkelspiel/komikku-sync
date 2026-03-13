# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import logging

from komikku.models.database import create_db_connection
from komikku.models.database import update_row
from komikku.models.database.mangas import Chapter

logger = logging.getLogger(__name__)


class Download:
    _chapter = None

    STATUSES = dict(
        pending=_('Download pending'),
        downloaded=_('Downloaded'),
        downloading=_('Downloading'),
        canceled=_('Download canceled'),
        error=_('Download error'),
    )

    @classmethod
    def get(cls, id_, db_conn=None):
        if db_conn is None:
            db_conn = create_db_connection()

        row = db_conn.execute('SELECT * FROM downloads WHERE id = ?', (id_,)).fetchone()

        if row is None:
            return None

        d = cls()
        for key in row.keys():
            setattr(d, key, row[key])

        return d

    @classmethod
    def get_by_chapter_id(cls, chapter_id, db_conn=None):
        if db_conn is None:
            db_conn = create_db_connection()

        row = db_conn.execute('SELECT * FROM downloads WHERE chapter_id = ?', (chapter_id,)).fetchone()

        if row:
            d = cls()

            for key in row.keys():
                setattr(d, key, row[key])

            return d

        return None

    @property
    def chapter(self):
        if self._chapter is None:
            self._chapter = Chapter.get(self.chapter_id)

        return self._chapter

    def delete(self, db_conn=None):
        if db_conn is None:
            db_conn = create_db_connection()

        with db_conn:
            db_conn.execute('DELETE FROM downloads WHERE id = ?', (self.id, ))

    def update(self, data, db_conn=None):
        """
        Updates download

        :param data: percent of pages downloaded, errors or status
        :return: True on success False otherwise
        """
        if db_conn is None:
            db_conn = create_db_connection()

        result = False

        with db_conn:
            if update_row(db_conn, 'downloads', self.id, data):
                result = True
                for key in data:
                    setattr(self, key, data[key])

        return result
