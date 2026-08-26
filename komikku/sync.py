# SPDX-FileCopyrightText: 2026 Willem Dinkelspiel <mail@keii.dev>
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import threading
import time
from datetime import UTC
from datetime import datetime
from gettext import gettext as _

from gi.repository import GLib

from komikku.models import KomikkuSyncDAO
from komikku.models import KomikkuSyncError
from komikku.models import Manga
from komikku.models import Settings
from komikku.models import SyncedState

logger = logging.getLogger(__name__)


def get_chapter_state(chapters):
    state = {}
    for chapter in chapters:
        if chapter.slug is not None:
            key = ('slug', str(chapter.slug))
            state[key] = chapter
        if chapter.num is not None:
            key = ('num', str(chapter.num))
            state[key] = chapter
    return state


def merge_chapter_state(manga, chapters):
    imported_state = get_chapter_state(chapters)
    updated = 0
    manga_last_read = manga.last_read
    for chapter in manga.chapters:
        imported = None
        if chapter.slug is not None:
            imported = imported_state.get(('slug', str(chapter.slug)))
        if imported is None and chapter.num is not None:
            imported = imported_state.get(('num', str(chapter.num)))
        if imported is None:
            continue

        data = {}
        if imported.read and not chapter.read:
            data['read'] = 1
        if imported.last_read is not None:
            imported_last_read = datetime.fromtimestamp(imported.last_read / 1000, UTC)
            local_last_read = chapter.last_read
            if local_last_read is None or _as_utc(local_last_read) < imported_last_read:
                data['last_read'] = imported_last_read
                data['last_page_read_index'] = imported.last_page_read_index
                manga_last_read = max(_as_utc(manga_last_read), imported_last_read) if manga_last_read else imported_last_read
        if data:
            chapter.update(data)
            updated += 1
    if manga_last_read != manga.last_read:
        manga.update({'last_read': manga_last_read})
    return updated


def _as_utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def import_synced_state(state, progress_callback=None):
    imported = 0
    updated = 0
    failed = 0
    local_mangas = {(manga.server_id, manga.slug): manga for manga in Manga.all()}
    total = len(state.mangas)
    logger.info('[Cloud Sync] Importing %d manga from remote state', total)

    for index, manga_data in enumerate(state.mangas, 1):
        slug = manga_data.slug
        server_id = manga_data.server_id
        if not slug or not server_id:
            failed += 1
            continue

        try:
            manga = local_mangas.get((server_id, slug))
            if manga is None:
                manga_loader = Manga()
                manga_loader.server_id = server_id
                server = manga_loader.server
                initial_data = {
                    key: getattr(manga_data, key)
                    for key in ('slug', 'name', 'url')
                    if getattr(manga_data, key) is not None
                }
                remote_data = server.get_manga_data(initial_data)
                if remote_data is None:
                    raise RuntimeError(f'Failed to retrieve {server_id}:{slug}')
                manga = Manga.new(remote_data, server, Settings.get_default().long_strip_detection)
                manga.add_in_library()
                local_mangas[(server_id, slug)] = manga
                imported += 1
            updated += merge_chapter_state(manga, manga_data.chapters)
        except Exception:
            failed += 1
            logger.exception('Failed to import manga %s:%s', server_id, slug)
        if progress_callback:
            progress_callback(index, total)

    logger.info(
        '[Cloud Sync] Import completed: %d manga imported, %d chapters updated, %d failed',
        imported, updated, failed
    )
    return imported, updated, failed


class CloudSyncController:
    PULL_INTERVAL = 5 * 60

    def __init__(self, window):
        self.window = window
        self.dao = KomikkuSyncDAO()
        self.authenticated = False
        self.last_pull = 0
        self.sync_lock = threading.Lock()
        self.push_timer = None
        self.started = False
        self.window.connect('notify::is-active', self.on_window_active_changed)

    def startup(self):
        if self.started:
            return
        self.started = True
        logger.info('[Cloud Sync] Checking saved sync configuration')
        self.window.add_notification(_('Checking sync...'), timeout=2)
        if not self.dao.configured:
            logger.info('[Cloud Sync] No saved sync session found')
            return
        logger.info('[Cloud Sync] Validating saved session with %s', self.dao.server)
        thread = threading.Thread(target=self._validate_startup, daemon=True)
        thread.start()

    def _validate_startup(self):
        valid = self.dao.validate()
        GLib.idle_add(self._validation_finished, valid)

    def _validation_finished(self, valid):
        self.authenticated = valid
        self.window.preferences.cloud_sync_row.update_state()
        if valid:
            logger.info('[Cloud Sync] Saved session is valid')
            self.window.add_notification(_('Cloud sync connected'), timeout=2)
            self.pull_async(notify=True, push_after=True)
        else:
            logger.warning('[Cloud Sync] Saved session is invalid or the server is unavailable')
            self.window.add_notification(_('Cloud sync login required'))
            self.window.preferences.cloud_sync_row.open_login_dialog(reconnect=True)

    def login_async(self, server, username, password, callback):
        logger.info('[Cloud Sync] Logging in to %s', server)
        self.window.activity_indicator.set_visible(True)

        def run():
            try:
                self.dao.login(server, username, password)
                logger.info('[Cloud Sync] Login succeeded; pulling remote state')
                state = self.dao.pull()
                result = import_synced_state(state)
                logger.info('[Cloud Sync] Pushing merged local state after login')
                local_state = SyncedState.from_mangas(Manga.all())
                merged = self.dao.push(local_state)
                import_synced_state(merged)
                GLib.idle_add(finish, True, None, result)
            except Exception as error:
                if not isinstance(error, KomikkuSyncError):
                    logger.exception('[Cloud Sync] Unexpected login synchronization failure')
                logger.warning('[Cloud Sync] Login or initial pull failed: %s', error)
                GLib.idle_add(finish, False, str(error), None)

        def finish(success, error, result):
            self.window.activity_indicator.set_visible(False)
            if success:
                self.authenticated = True
                self.last_pull = time.monotonic()
                self.window.library.populate()
            callback(success, error, result)

        threading.Thread(target=run, daemon=True).start()

    def logout(self):
        logger.info('[Cloud Sync] Logging out and removing saved session')
        self.dao.logout()
        self.authenticated = False
        if self.push_timer:
            self.push_timer.cancel()
            self.push_timer = None

    def pull_async(self, notify=False, push_after=False):
        if not self.authenticated or self.sync_lock.locked():
            logger.debug('[Cloud Sync] Pull skipped because sync is unavailable or busy')
            return
        logger.info('[Cloud Sync] Pulling state from %s', self.dao.server)
        self.window.activity_indicator.set_visible(True)

        def run():
            try:
                with self.sync_lock:
                    state = self.dao.pull()
                    result = import_synced_state(state)
                    if push_after:
                        logger.info('[Cloud Sync] Pushing merged local state after startup pull')
                        local_state = SyncedState.from_mangas(Manga.all())
                        merged = self.dao.push(local_state)
                        import_synced_state(merged)
                GLib.idle_add(finish, result, None)
            except KomikkuSyncError as error:
                GLib.idle_add(finish, None, str(error))

        def finish(result, error):
            self.window.activity_indicator.set_visible(False)
            if error:
                logger.warning('[Cloud Sync] Pull failed: %s', error)
                if notify:
                    self.window.add_notification(error)
                return
            self.last_pull = time.monotonic()
            self.window.library.populate()
            imported, updated, failed = result
            logger.info(
                '[Cloud Sync] Pull completed: %d manga imported, %d chapters updated, %d failed',
                imported, updated, failed
            )
            if notify:
                self.window.add_notification(
                    _('%d manga imported, %d chapters updated, %d failed') % (imported, updated, failed)
                )

        threading.Thread(target=run, daemon=True).start()

    def schedule_push(self):
        if not self.authenticated:
            logger.debug('[Cloud Sync] Push not scheduled because there is no active session')
            return
        if self.push_timer:
            self.push_timer.cancel()
        self.push_timer = threading.Timer(1.0, self.push_async)
        self.push_timer.daemon = True
        self.push_timer.start()
        logger.debug('[Cloud Sync] State push scheduled')

    def push_async(self):
        self.push_timer = None
        if not self.authenticated:
            return
        if self.sync_lock.locked():
            logger.debug('[Cloud Sync] Push delayed because another sync is running')
            self.schedule_push()
            return

        def run():
            try:
                with self.sync_lock:
                    logger.info('[Cloud Sync] Pushing local state to %s', self.dao.server)
                    state = SyncedState.from_mangas(Manga.all())
                    merged = self.dao.push(state)
                    import_synced_state(merged)
                logger.info('[Cloud Sync] Push completed')
                GLib.idle_add(self._push_finished, None)
            except Exception as error:
                logger.exception('[Cloud Sync] Push failed: %s', error)
                GLib.idle_add(self._push_finished, str(error))

        threading.Thread(target=run, daemon=True).start()

    def _push_finished(self, error):
        if error:
            self.window.add_notification(_('Cloud sync push failed'))
        else:
            self.window.add_notification(_('Cloud sync updated'), timeout=2)

    def on_window_active_changed(self, window, _param):
        if window.is_active() and time.monotonic() - self.last_pull >= self.PULL_INTERVAL:
            logger.info('[Cloud Sync] Window focused after sync interval; checking remote state')
            self.pull_async()
