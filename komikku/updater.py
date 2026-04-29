# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
from gettext import ngettext
import threading

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject

from komikku.utils import log_error_traceback
from komikku.models import create_db_connection
from komikku.models import Manga
from komikku.models import Settings
from komikku.utils import if_network_available


class Updater(GObject.GObject):
    """
    Mangas updater
    """
    __gsignals__ = {
        'manga-updated': (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT, bool)),
    }

    current_id = None
    queue = []
    running = False
    servers_down = []
    stop_flag = False
    update_at_startup_done = False
    update_library_flag = False

    def __init__(self, window):
        GObject.GObject.__init__(self)

        self.window = window

    def add(self, mangas):
        if not isinstance(mangas, list):
            mangas = [mangas, ]

        batch = len(mangas) > 1  # is it a batch or a single update?

        for manga in mangas:
            if manga.id not in self.queue and manga.id != self.current_id and manga.server.status == 'enabled':
                self.queue.append((manga.id, batch))

    def remove(self, manga):
        if manga.id in self.queue:
            self.queue.remove(manga.id)

    @if_network_available(only_notify=True)
    def start(self):
        def show_notification(id, title, body=None):
            if Settings.get_default().desktop_notifications:
                notification = Gio.Notification.new(title)
                notification.set_priority(Gio.NotificationPriority.HIGH)
                if body:
                    notification.set_body(body)
                self.window.application.send_notification(id, notification)
            else:
                # Use in-app notification
                self.window.add_notification(f'{title}\n{body}' if body else title)

        def run():
            db_conn = create_db_connection()

            total_chapters = 0
            total_errors = 0
            total_successes = 0

            while self.queue:
                if self.stop_flag is True:
                    break

                manga_id, in_batch = self.queue.pop(0)
                manga = Manga.get(manga_id)

                if manga is None or (not manga.is_local and not self.window.network_available):
                    # Skip manga if not found or if network is not available (except for local which don't require an Internet connection)
                    continue

                if manga.server_id in self.servers_down:
                    continue

                if not manga.server.is_up():
                    self.servers_down.append(manga.server_id)
                    self.window.add_notification(
                        _('{0} seems down. Please try updating later').format(manga.server.name)
                    )
                    continue

                self.current_id = manga_id
                try:
                    success, chapters_changes, synced = manga.update_full(db_conn=db_conn)
                    if success:
                        total_successes += 1
                        if nb_recents := len(chapters_changes['recent_ids']):
                            total_chapters += nb_recents
                        GLib.idle_add(complete, manga, in_batch, chapters_changes, synced)
                    else:
                        total_errors += 1
                        GLib.idle_add(error, manga)
                except Exception as e:
                    user_error_message = log_error_traceback(e)
                    total_errors += 1
                    GLib.idle_add(error, manga, user_error_message)

            self.current_id = None
            self.running = False
            self.servers_down = []

            if not self.update_library_flag and total_successes + total_errors <= 1:
                # If only one or no comic has been updated, it's not necessary to send end notification
                return

            # End notification
            if self.update_library_flag:
                self.update_library_flag = False
                if total_errors > 0:
                    title = _('Library update completed with errors')
                else:
                    title = _('Library update completed')
            else:
                if total_errors > 0:
                    title = _('Update completed with errors')
                else:
                    title = _('Update completed')

            messages = []
            if total_chapters > 0:
                messages.append(ngettext('{0} successful update', '{0} successful updates', total_successes).format(total_successes))
                messages.append(ngettext('{0} new chapter', '{0} new chapters', total_chapters).format(total_chapters))
            else:
                messages.append(_('No new chapters'))

            if total_errors > 0:
                messages.append(ngettext('{0} update failed', '{0} updates failed', total_errors).format(total_errors))

            show_notification('updater.0', title, '\n'.join(messages))

        def complete(manga, in_batch, chapters_changes, synced):
            nb_recent_chapters = len(chapters_changes['recent_ids'])

            if nb_recent_chapters > 0:
                show_notification(
                    f'updater.{manga.id}',
                    manga.name,
                    ngettext('{0} new chapter', '{0} new chapters', nb_recent_chapters).format(nb_recent_chapters)
                )

                # Auto download new chapters
                if Settings.get_default().new_chapters_auto_download and not manga.is_local:
                    self.window.downloader.add(chapters_changes['recent_ids'], emit_signal=True)
                    self.window.downloader.start()
            elif not in_batch:
                show_notification(f'updater.{manga.id}', manga.name, _('No new chapters'))

            self.emit(
                'manga-updated',
                manga,
                dict(
                    nb_recent_chapters=nb_recent_chapters,
                    nb_updated_chapters=chapters_changes['nb_updated'],
                    nb_deleted_chapters=chapters_changes['nb_deleted'],
                ),
                synced
            )

            return False

        def error(manga, message=None):
            show_notification(
                f'updater.{manga.id}',
                manga.name,
                message or _('Oops, update has failed. Please try again.')
            )

            return False

        if self.running or len(self.queue) == 0:
            return False

        if self.update_library_flag:
            title = _('Library update started')
            show_notification('updater.0', title)

        self.running = True
        self.stop_flag = False

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()

        return True

    def stop(self):
        if self.running:
            self.stop_flag = True

    def update_library(self, startup=False):
        if startup:
            self.update_at_startup_done = True

        db_conn = create_db_connection()
        if self.window.network_available:
            # Update all manga in library
            rows = db_conn.execute('SELECT * FROM mangas WHERE in_library = 1 ORDER BY last_read DESC').fetchall()
        else:
            # Offline, update local manga only
            rows = db_conn.execute('SELECT * FROM mangas WHERE in_library = 1 AND server_id = "local" ORDER BY last_read DESC').fetchall()

        if rows:
            self.update_library_flag = True
            self.add([Manga.get(row['id']) for row in rows])
            return self.start()

        return False
