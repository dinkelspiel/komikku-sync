# SPDX-FileCopyrightText: 2026 Willem Dinkelspiel <mail@keii.dev>
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import logging
import os
from urllib.parse import urlparse

import requests

from komikku.models.synced_state import SyncedState
from komikku.utils import get_data_dir

logger = logging.getLogger(__name__)


class KomikkuSyncError(Exception):
    pass


class KomikkuSyncDAO:
    def __init__(self, path=None):
        self.path = path or os.path.join(get_data_dir(), 'cloud-sync.json')
        self.server = None
        self.username = None
        self.api_token = None
        self.load()

    @property
    def configured(self):
        return bool(self.server and self.username and self.api_token)

    def load(self):
        try:
            with open(self.path, encoding='utf-8') as file:
                data = json.load(file)
            server = self.normalize_server(data.get('server', ''))
            username = data.get('username')
            api_token = data.get('api_token')
            if not server or not isinstance(username, str) or not username or not isinstance(api_token, str) or not api_token:
                raise ValueError
            self.server = server
            self.username = username
            self.api_token = api_token
            logger.info('[Cloud Sync] Loaded saved session for %s', server)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.server = None
            self.username = None
            self.api_token = None
            logger.debug('[Cloud Sync] No valid saved session at %s', self.path)

    def login(self, server, username, password):
        server = self.normalize_server(server)
        if not server or not username or not password:
            raise KomikkuSyncError('Server, username, and password are required')

        try:
            logger.debug('[Cloud Sync] POST %s/api/login', server)
            response = requests.post(
                f'{server}/api/login',
                data={'username': username, 'password': password},
                timeout=15,
            )
        except requests.RequestException as error:
            raise KomikkuSyncError('Unable to reach the sync server') from error
        if response.status_code != 200 or not response.text.strip():
            logger.warning('[Cloud Sync] Login returned HTTP %d', response.status_code)
            raise KomikkuSyncError('Invalid username or password')

        self.server = server
        self.username = username
        self.api_token = response.text.strip()
        self.save()
        logger.info('[Cloud Sync] Saved session for %s', server)

    def validate(self):
        if not self.configured:
            return False
        try:
            logger.debug('[Cloud Sync] GET %s/api/auth/validate', self.server)
            response = requests.get(
                f'{self.server}/api/auth/validate',
                headers=self.auth_headers,
                timeout=15,
            )
        except requests.RequestException as error:
            logger.warning('[Cloud Sync] Session validation request failed: %s', error)
            return False
        logger.debug('[Cloud Sync] Session validation returned HTTP %d', response.status_code)
        return response.status_code == 200

    def pull(self):
        self.require_configured()
        try:
            logger.debug('[Cloud Sync] GET %s/api/state', self.server)
            response = requests.get(
                f'{self.server}/api/state',
                headers=self.auth_headers,
                timeout=30,
            )
        except requests.RequestException as error:
            raise KomikkuSyncError('Unable to pull sync state') from error
        if response.status_code != 200:
            raise KomikkuSyncError('Unable to pull sync state')
        try:
            logger.debug('[Cloud Sync] Decoding %d pulled bytes', len(response.content))
            return SyncedState.decode(response.content)
        except (TypeError, ValueError) as error:
            raise KomikkuSyncError('The server returned invalid sync data') from error

    def push(self, state):
        self.require_configured()
        headers = self.auth_headers
        headers['Content-Type'] = SyncedState.CONTENT_TYPE
        try:
            payload = state.encode()
            logger.debug('[Cloud Sync] POST %s/api/state with %d bytes', self.server, len(payload))
            response = requests.post(
                f'{self.server}/api/state',
                headers=headers,
                data=payload,
                timeout=30,
            )
        except requests.RequestException as error:
            raise KomikkuSyncError('Unable to push sync state') from error
        if response.status_code != 200:
            logger.warning('[Cloud Sync] State push returned HTTP %d: %s', response.status_code, response.text[:200])
            raise KomikkuSyncError('Unable to push sync state')
        try:
            logger.debug('[Cloud Sync] Decoding %d merged bytes', len(response.content))
            return SyncedState.decode(response.content)
        except (TypeError, ValueError) as error:
            raise KomikkuSyncError('The server returned invalid sync data') from error

    def logout(self):
        self.server = None
        self.username = None
        self.api_token = None
        try:
            os.remove(self.path)
            logger.info('[Cloud Sync] Removed saved session')
        except FileNotFoundError:
            logger.debug('[Cloud Sync] Saved session was already absent')

    @property
    def auth_headers(self):
        return {'Authorization': f'Bearer {self.api_token}'}

    def require_configured(self):
        if not self.configured:
            raise KomikkuSyncError('Cloud sync is not configured')

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temporary_path = f'{self.path}.tmp'
        with open(temporary_path, 'w', encoding='utf-8') as file:
            json.dump({
                'server': self.server,
                'username': self.username,
                'api_token': self.api_token,
            }, file)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, self.path)

    @staticmethod
    def normalize_server(server):
        server = server.strip().rstrip('/')
        if server and '://' not in server:
            server = f'http://{server}'
        parsed = urlparse(server)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path not in ('', '/'):
            return None
        return f'{parsed.scheme}://{parsed.netloc}'
