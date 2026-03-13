# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from abc import ABC
from abc import abstractmethod
from functools import wraps
from gettext import gettext as _
import json
import logging
import os
import threading
import time

import jwt

from gi.repository import GObject

from komikku.consts import LOGO_SIZE
from komikku.models import create_db_connection
from komikku.models import Manga
from komikku.models import Settings
from komikku.utils import BaseServer
from komikku.utils import get_cached_logos_dir
from komikku.utils import log_error_traceback
from komikku.trackers.utils import get_trackers_list

logger = logging.getLogger(__name__)


def authenticated(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        tracker = args[0]
        granted, access_token_valid = tracker.is_granted()

        if not granted:
            return None

        if access_token_valid:
            return func(*args, **kwargs, access_token=tracker.data['access_token'])

        # Access token is expired, try to refresh it
        if new_access_token := tracker.refresh_access_token():
            logger.info('%s tracker access token has been successfully refreshed', tracker.name)
            return func(*args, **kwargs, access_token=new_access_token)

        # Tracker don't support refresh or refresh has failed
        return None

    return wrapper


class Tracker(BaseServer, ABC):
    id: str
    name: str
    base_url: str

    authorize_url: str = None
    app_redirect_url: str = 'https://komikku.info/'
    manga_url: str = None
    logo_url: str = None

    headers_images = {}

    INTERNAL_STATUSES = {
        'reading': _('Reading'),
        'completed': _('Completed'),
        'on_hold': _('On Hold'),
        'dropped': _('Dropped'),
        'plan_to_read': _('Plan to Read'),
        'rereading': _('Rereading'),
    }
    STATUSES_MAPPING: dict = None

    @property
    def data(self):
        """Tracker data saved in settings"""
        return Settings.get_default().trackers.get(self.id)

    @data.setter
    def data(self, data):
        """Save tracker data (access token, refresh token,...) in settings"""
        trackers = Settings.get_default().trackers

        trackers[self.id] = data

        Settings.get_default().trackers = trackers

    @property
    def logo_path(self):
        path = os.path.join(get_cached_logos_dir(), 'trackers', f'{self.id}.png')
        if not os.path.exists(path):
            return None

        return path

    def convert_internal_status(self, status):
        """Returns corresponding tracker status for an internal status"""
        for tracker_status, internal_status in self.STATUSES_MAPPING.items():
            if internal_status == status:
                return tracker_status

    def get_manga_data(self, id):
        data = self.get_user_manga_data(id)
        if data is None:
            data = self.get_tracker_manga_data(id)
            if data:
                # Add user's status fields that doesn't exist in tracker manga data
                data['chapters_progress'] = 0
                data['score'] = 0
                data['status'] = 'reading'

        return data

    @abstractmethod
    def get_manga_url(self, id):
        """Returns manga URL"""

    def get_status_from_index(self, index):
        return list(self.STATUSES_MAPPING.values())[index]

    def get_status_index(self, internal_status):
        for index, status in enumerate(self.STATUSES_MAPPING.values()):
            if status == internal_status:
                return index

    @abstractmethod
    def get_tracker_manga_data(self, id):
        """Retrieves tracker manga info"""

    @abstractmethod
    def get_user_manga_data(self, id):
        """Retrieves user manga info (progress, score, status)"""

    @abstractmethod
    def get_user_score_format(self, format):
        """Returns user score format (min, max, step, raw factor)"""

    def is_granted(self):
        """
        :return: is granted, is access token valid (not expired)
        :rtype: (bool, bool)
        """
        data = self.data
        if data is None:
            return False, False

        if not data.get('access_token'):
            return False, False

        # Get expires timestamp in token payload
        payload = jwt.decode(data['access_token'], options={'verify_signature': False})
        expiration_time = payload.get('exp')
        # Else, get it in data if available
        if expiration_time is None:
            expiration_time = data.get('exp')

        if expiration_time is None:
            # No expiration time, token is assumed to be valid
            return True, True

        return True, time.time() <= expiration_time - 86400

    @abstractmethod
    def refresh_access_token(self):
        """
        Refreshes the access token

        :return: The new access token
        :rtype: string
        """

    @abstractmethod
    def request_access_token(self):
        """Requests an access token"""

    def save_logo(self):
        return self.save_image(
            self.logo_url, os.path.join(get_cached_logos_dir(), 'trackers'), self.id,
            LOGO_SIZE, LOGO_SIZE, keep_aspect_ratio=False, format='PNG'
        )

    @abstractmethod
    def search(self, term):
        """Search a manga"""

    @abstractmethod
    def update_user_manga_data(self, id, data):
        """"Updates user manga data"""


class Trackers(GObject.GObject):
    __gsignals__ = {
        'manga-tracker-synced': (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT, )),
    }

    def __init__(self, window):
        super().__init__()
        self.window = window

        self.trackers = {}
        for info in get_trackers_list():
            tracker = getattr(info['module'], info['class_name'])()
            self.trackers[tracker.id] = tracker

    def sync(self):
        def run():
            db_conn = create_db_connection()

            for id, tracker in self.trackers.items():
                granted, access_token_valid = tracker.is_granted()
                if not granted or not access_token_valid:
                    continue

                query = f"SELECT id, tracking -> '{id}' AS data FROM mangas WHERE tracking -> '$.{id}._synced' = 'false'"

                for row in db_conn.execute(query).fetchall():
                    data = json.loads(row['data'])
                    try:
                        res = tracker.update_user_manga_data(data['id'], {
                            'score': data['score'],
                            'chapters_progress': data['chapters_progress'],
                            'status': data['status'],
                        })
                    except Exception as e:
                        res = False
                        log_error_traceback(e)
                        logging.warning(f'Failed to sync tracker {id}: ID={data["id"]} name={data["name"]}')

                    if res:
                        manga = Manga.get(row['id'], db_conn=db_conn)
                        manga.tracking[id]['_synced'] = True
                        manga.update({
                            'tracking': manga.tracking,
                        })

                        self.emit('manga-tracker-synced', manga)
                    else:
                        logging.warning(f'Failed to sync tracker {id}: ID={data["id"]} name={data["name"]}')

        if not Settings.get_default().tracking:
            return

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()
