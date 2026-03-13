# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
import datetime
from gettext import gettext as _
from gettext import ngettext
import threading
import time

from gi.repository import Adw
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk

from komikku.consts import DOWNLOAD_MAX_DELAY
from komikku.models import Chapter
from komikku.models import create_db_connection
from komikku.models import Download
from komikku.models import insert_rows
from komikku.models import Settings
from komikku.utils import if_network_available


class Downloader(GObject.GObject):
    """
    Chapters downloader
    """
    __gsignals__ = {
        'download-changed': (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT, )),
        'ended': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'started': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    current_download = None
    running = False
    stop_flag = False

    def __init__(self, window):
        GObject.GObject.__init__(self)

        self.window = window

    def add(self, chapters, emit_signal=False):
        """Add chapters to download"""
        chapters_ids = []
        rows_data = []
        db_conn = create_db_connection()

        for chapter in chapters:
            if isinstance(chapter, Chapter):
                if chapter.downloaded:
                    continue
                chapter_id = chapter.id
            else:
                chapter_id = chapter

            if Download.get_by_chapter_id(chapter_id, db_conn=db_conn) is not None:
                # Chapter download is already scheduled
                continue

            rows_data.append(dict(
                chapter_id=chapter_id,
                status='pending',
                percent=0,
                date=datetime.datetime.now(datetime.UTC),
            ))
            chapters_ids.append(chapter_id)

        if not chapters_ids:
            return

        with db_conn:
            insert_rows(db_conn, 'downloads', rows_data)

        if emit_signal:
            for chapter_id in chapters_ids:
                download = Download.get_by_chapter_id(chapter_id, db_conn=db_conn)
                if download:
                    self.emit('download-changed', download, None)

    def cancel(self, chapters):
        """Cancel downloads"""
        db_conn = create_db_connection()

        for chapter in chapters:
            download = Download.get_by_chapter_id(chapter.id, db_conn=db_conn)
            if not download:
                continue

            if self.current_download and self.current_download.id == download.id:
                self.current_download.status = 'canceled'

            download.delete(db_conn=db_conn)

            self.emit('download-changed', None, chapter)

    @if_network_available
    def start(self):
        def run(exclude_errors=False):
            db_conn = create_db_connection()

            # Get pending downloads sorted by server
            sql = """
                SELECT d.id, m.id AS manga_id, m.server_id FROM downloads d
                JOIN chapters c ON d.chapter_id = c.id
                JOIN mangas m ON c.manga_id = m.id
            """
            if exclude_errors:
                sql += ' WHERE d.status != "error"'

            sql += ' ORDER BY m.server_id ASC, m.id ASC, d.id ASC'
            rows = db_conn.execute(sql).fetchall()

            if not rows or self.stop_flag:
                self.running = False
                GLib.idle_add(self.emit, 'ended')
                return

            # Build dict with list of downloads per server
            server_downloads = {}
            for row in rows:
                if row['server_id'] not in server_downloads:
                    server_downloads[row['server_id']] = {}
                if row['manga_id'] not in server_downloads[row['server_id']]:
                    server_downloads[row['server_id']][row['manga_id']] = []
                server_downloads[row['server_id']][row['manga_id']].append(row['id'])

            with ThreadPoolExecutor(max_workers=len(server_downloads)) as executor:
                tasks = {}
                for _server_id, manga_downloads in server_downloads.items():
                    for _manga_id, downloads in manga_downloads.items():
                        future = executor.submit(process_manga_downloads, downloads)
                        tasks[future] = None

                for _future in as_completed(tasks):
                    if self.stop_flag:
                        executor.shutdown(False, cancel_futures=True)
                        break

            # Continue, new downloads may have been added in the meantime
            run(exclude_errors=True)

        def process_manga_downloads(downloads):
            db_conn = create_db_connection()
            manga = None
            cancelations = 0
            errors = 0
            failures = 0
            successes = 0

            for download_id in downloads:
                self.current_download = None
                if self.stop_flag:
                    break

                download = Download.get(download_id, db_conn=db_conn)
                if download is None:
                    # Download has been canceled in the meantime
                    cancelations += 1
                    continue

                chapter = download.chapter
                if manga is None:
                    manga = chapter.manga

                download.update(dict(status='downloading'), db_conn=db_conn)
                GLib.idle_add(self.emit, 'download-changed', download, None)

                try:
                    if chapter.update_full(db_conn=db_conn) and len(chapter.pages) > 0:
                        self.current_download = download
                        page_errors = 0
                        page_successes = 0

                        for index, _page in enumerate(chapter.pages):
                            if self.stop_flag:
                                # Downloader has been stopped
                                break
                            if download.status == 'canceled':
                                # Download has been canceled
                                break

                            if chapter.get_page_path(index) is None:
                                # Depending on amount of bandwidth the server has, we must be mindful not to overload it
                                # with our requests.
                                #
                                # Furthermore, multiple and fast-paced requests from same IP address can alert the system
                                # administrator that potentially unwanted actions are taking place.
                                # This may result in an IP ban.
                                #
                                # Easiest way to avoid server  overloading is to set a time-out between requests
                                # equal to 2x the time it took to load the page (responsive delay).
                                path, rtime = chapter.get_page(index, db_conn=db_conn)

                                if path is not None:
                                    page_successes += 1
                                    download.update(dict(percent=(index + 1) * 100 / len(chapter.pages)), db_conn=db_conn)
                                else:
                                    page_errors += 1
                                    download.update(dict(errors=page_errors), db_conn=db_conn)

                                GLib.idle_add(self.emit, 'download-changed', download, None)

                                if index < len(chapter.pages) - 1 and not self.stop_flag and rtime:
                                    time.sleep(min(2 * rtime, DOWNLOAD_MAX_DELAY))
                            else:
                                page_successes += 1

                        if page_successes == len(chapter.pages):
                            # Download ended
                            # All pages were successfully downloaded
                            successes += 1
                            chapter.update(dict(downloaded=1), db_conn=db_conn)
                            download.delete(db_conn=db_conn)
                            GLib.idle_add(self.emit, 'download-changed', None, chapter)

                        elif page_successes + page_errors == len(chapter.pages):
                            # Download has ended
                            # But at least one page failed to be downloaded
                            errors += 1
                            download.update(dict(status='error'), db_conn=db_conn)
                            GLib.idle_add(self.emit, 'download-changed', download, None)

                        else:
                            # Download has been interruped
                            if self.stop_flag:
                                # Downloader has been stopped
                                # Restore pending status of current unfinished download
                                download.update(dict(status='pending'), db_conn=db_conn)

                            elif download.status == 'canceled':
                                # Download has been canceled
                                cancelations += 1
                                GLib.idle_add(self.emit, 'download-changed', None, chapter)
                    else:
                        # Possible causes:
                        # - Empty chapter
                        # - Outdated chapter info
                        # - Server has undergone changes (API, HTML) and plugin code is outdated
                        failures += 1
                        download.update(dict(status='error'), db_conn=db_conn)
                        GLib.idle_add(self.emit, 'download-changed', download, None)
                except Exception:
                    # Possible causes:
                    # - No Internet connection
                    # - Connection timeout, read timeout
                    # - Server down
                    # - Bad/corrupt local archive
                    failures += 1
                    download.update(dict(status='error'), db_conn=db_conn)
                    GLib.idle_add(self.emit, 'download-changed', download, None)

            self.current_download = None
            if not self.stop_flag:
                GLib.idle_add(
                    notify_manga_chapters_download_ended,
                    manga, len(downloads), successes, errors, cancelations, failures
                )

        def notify_manga_chapters_download_ended(manga, total, successes, errors, cancelations, failures):
            if notification is None:
                return

            if cancelations + errors + failures == 0:
                notification.set_category('transfer.success')
            elif errors + failures != 0:
                notification.set_category('transfer.error')

            notification.set_title(_('[{0}] Chapters download ended').format(manga.name))

            body = []
            if successes:
                body.append('🟢 ' + '{0}/{1} completed'.format(successes, total))
            if cancelations:
                body.append('🟡 ' + '{0}/{1} canceled'.format(cancelations, total))
            if errors:
                body.append('🟠 ' + '{0}/{1} with errors'.format(errors, total))
            if failures:
                body.append('🔴 ' + '{0}/{1} failed'.format(failures, total))

            notification.set_body(' | '.join(body))
            self.window.application.send_notification(f'downloader.{manga.id}', notification)

        if self.running:
            return

        Settings.get_default().downloader_state = True
        self.running = True
        self.stop_flag = False

        if Settings.get_default().desktop_notifications:
            notification = Gio.Notification()
        else:
            notification = None

        GLib.idle_add(self.emit, 'started')

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()

    def stop(self, save_state=False):
        if not self.running:
            return

        self.stop_flag = True
        if save_state:
            Settings.get_default().downloader_state = False


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/download_manager.ui')
class DownloadManagerPage(Adw.NavigationPage):
    __gtype_name__ = 'DownloadManagerPage'
    __gsignals_handlers_ids__ = None

    selection_mode = False
    selection_mode_range = False
    selection_mode_last_row_index = None

    left_button = Gtk.Template.Child('left_button')
    title = Gtk.Template.Child('title')
    start_stop_button = Gtk.Template.Child('start_stop_button')
    menu_button = Gtk.Template.Child('menu_button')

    stack = Gtk.Template.Child('stack')
    listbox = Gtk.Template.Child('listbox')
    selection_mode_actionbar = Gtk.Template.Child('selection_mode_actionbar')

    def __init__(self, window):
        Adw.NavigationPage.__init__(self)

        self.window = window
        self.downloader = self.window.downloader

        self.builder = window.builder
        self.builder.add_from_resource('/info/febvre/Komikku/ui/menu/download_manager.xml')

        # Header bar
        self.left_button.connect('clicked', self.leave_selection_mode)
        self.start_stop_button.connect('clicked', self.on_start_stop_button_clicked)
        self.menu_button.set_menu_model(self.builder.get_object('menu-download-manager'))
        # Focus is lost after showing popover submenu (bug?)
        self.menu_button.get_popover().connect('closed', lambda _popover: self.menu_button.grab_focus())

        self.listbox.connect('row-activated', self.on_download_row_activated)
        self.listbox.connect('selected-rows-changed', self.on_selection_changed)
        self.window.controller_key.connect('key-pressed', self.on_key_pressed)

        # Gestures for multi-selection mode
        self.gesture_click = Gtk.GestureClick.new()
        self.gesture_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.gesture_click.set_button(3)
        self.gesture_click.connect('pressed', self.on_download_row_right_click)
        self.listbox.add_controller(self.gesture_click)

        self.gesture_long_press = Gtk.GestureLongPress.new()
        self.gesture_long_press.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.gesture_long_press.set_touch_only(False)
        self.gesture_long_press.connect('pressed', self.on_gesture_long_press_activated)
        self.listbox.add_controller(self.gesture_long_press)

        self.__gsignals_handlers_ids__ = [
            self.downloader.connect('download-changed', self.update_row),
            self.downloader.connect('ended', self.update_headerbar),
            self.downloader.connect('started', self.update_headerbar),
        ]

        self.window.navigationview.add(self)

    def add_actions(self):
        # Delete All action
        delete_all_action = Gio.SimpleAction.new('download-manager.delete-all', None)
        delete_all_action.connect('activate', self.on_menu_delete_all_clicked)
        self.window.application.add_action(delete_all_action)

        # Delete Selected action
        delete_selected_action = Gio.SimpleAction.new('download-manager.delete-selected', None)
        delete_selected_action.connect('activate', self.on_menu_delete_selected_clicked)
        self.window.application.add_action(delete_selected_action)

    def enter_selection_mode(self):
        self.props.can_pop = False
        self.left_button.set_label(_('Cancel'))
        self.left_button.set_tooltip_text(_('Cancel'))
        self.left_button.set_visible(True)
        self.start_stop_button.set_visible(False)
        self.menu_button.set_visible(False)

        self.selection_mode = True

        self.listbox.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.selection_mode_actionbar.set_revealed(True)

    def leave_selection_mode(self, *args):
        self.props.can_pop = True
        self.left_button.set_visible(False)
        self.start_stop_button.set_visible(True)
        self.menu_button.set_visible(True)

        self.selection_mode = False

        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        for row in self.listbox:
            row._selected = False
        self.selection_mode_actionbar.set_revealed(False)

    def on_download_row_activated(self, _listbox, row):
        row.grab_focus()

        if not self.selection_mode:
            return

        if self.selection_mode_range and self.selection_mode_last_row_index is not None:
            # Range selection mode: select all rows between last selected row and clicked row
            walk_index = self.selection_mode_last_row_index
            last_index = row.get_index()

            while walk_index != last_index:
                walk_row = self.listbox.get_row_at_index(walk_index)
                if walk_row and not walk_row._selected:
                    self.listbox.select_row(walk_row)
                    walk_row._selected = True

                if walk_index < last_index:
                    walk_index += 1
                else:
                    walk_index -= 1

        self.selection_mode_range = False

        if row._selected:
            self.listbox.unselect_row(row)
            self.selection_mode_last_row_index = None
            row._selected = False
        else:
            self.listbox.select_row(row)
            self.selection_mode_last_row_index = row.get_index()
            row._selected = True

        if len(self.listbox.get_selected_rows()) == 0:
            self.leave_selection_mode()

    def on_download_row_right_click(self, _gesture, _n_press, _x, y):
        """Allow to enter in selection mode with a right click on a row"""
        if self.selection_mode:
            return Gdk.EVENT_PROPAGATE

        row = self.listbox.get_row_at_y(y)
        if not self.selection_mode and row is not None:
            self.enter_selection_mode()
            self.on_download_row_activated(None, row)
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def on_gesture_long_press_activated(self, _gesture, _x, y):
        """Allow to enter in selection mode with a long press on a row"""
        if not self.selection_mode:
            self.enter_selection_mode()
        else:
            # Enter in 'Range' selection mode
            # Long press on a download row then long press on another to select everything in between
            self.selection_mode_range = True

        selected_row = self.listbox.get_row_at_y(y)
        self.on_download_row_activated(None, selected_row)

    def on_key_pressed(self, _controller, keyval, _keycode, state):
        if self.window.page != self.props.tag:
            return Gdk.EVENT_PROPAGATE

        modifiers = state & Gtk.accelerator_get_default_mod_mask()

        if self.selection_mode:
            if keyval == Gdk.KEY_Escape or (modifiers == Gdk.ModifierType.ALT_MASK and keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left)):
                self.leave_selection_mode()
                # Stop event to prevent back navigation
                return Gdk.EVENT_STOP
        else:
            # Allow to enter in selection mode with <SHIFT>+Arrow key
            if modifiers != Gdk.ModifierType.SHIFT_MASK or keyval not in (Gdk.KEY_Up, Gdk.KEY_KP_Up, Gdk.KEY_Down, Gdk.KEY_KP_Down):
                return Gdk.EVENT_PROPAGATE

            if row := self.listbox.get_focus_child():
                self.enter_selection_mode()
                self.on_download_row_activated(None, row)

        return Gdk.EVENT_PROPAGATE

    def on_menu_delete_all_clicked(self, _action, _param):
        chapters = []

        row = self.listbox.get_first_child()
        while row:
            next_row = row.get_next_sibling()
            chapters.append(row.download.chapter)
            self.listbox.remove(row)
            row = next_row

        self.downloader.cancel(chapters)

        self.leave_selection_mode()
        self.update_headerbar()
        GLib.idle_add(self.stack.set_visible_child_name, 'empty')

    def on_menu_delete_selected_clicked(self, _action, _param):
        chapters = []

        row = self.listbox.get_first_child()
        while row:
            next_row = row.get_next_sibling()
            if row._selected:
                chapters.append(row.download.chapter)
                self.listbox.remove(row)
            row = next_row

        self.downloader.cancel(chapters)

        self.leave_selection_mode()
        self.update_headerbar()
        if self.listbox.get_first_child() is None:
            # No more downloads
            GLib.idle_add(self.stack.set_visible_child_name, 'empty')

    def on_selection_changed(self, _flowbox):
        number = len(self.listbox.get_selected_rows())
        if number:
            self.title.set_subtitle(ngettext('{0} selected', '{0} selected', number).format(number))
        else:
            self.title.set_subtitle('')

    @if_network_available
    def on_start_stop_button_clicked(self, _button):
        self.start_stop_button.set_sensitive(False)

        if self.downloader.running:
            self.downloader.stop(save_state=True)
        else:
            self.downloader.start()

    def populate(self):
        # Clear
        row = self.listbox.get_first_child()
        while row:
            next_row = row.get_next_sibling()
            self.listbox.remove(row)
            row = next_row

        db_conn = create_db_connection()
        records = db_conn.execute('SELECT * FROM downloads ORDER BY date ASC').fetchall()

        if records:
            for record in records:
                download = Download.get(record['id'], db_conn=db_conn)

                row = DownloadRow(download)
                self.listbox.append(row)

            self.stack.set_visible_child_name('list')
        else:
            # No downloads
            self.stack.set_visible_child_name('empty')

    def select_all(self):
        if not self.selection_mode:
            self.enter_selection_mode()

        for row in self.listbox:
            if row._selected:
                continue
            self.listbox.select_row(row)
            row._selected = True

    def show(self):
        self.populate()

        self.update_headerbar(forced=True)
        self.window.navigationview.push(self)

    def update_headerbar(self, *args, forced=False):
        if self.window.page != self.props.tag and not forced:
            return

        if self.listbox.get_first_child() is not None:
            if self.downloader.running:
                self.start_stop_button.get_first_child().set_from_icon_name('media-playback-stop-symbolic')
                self.menu_button.set_visible(False)
            else:
                self.start_stop_button.get_first_child().set_from_icon_name('media-playback-start-symbolic')
                self.menu_button.set_visible(True)

            self.start_stop_button.set_sensitive(True)
            self.start_stop_button.set_visible(True)
        else:
            # No downloads
            self.start_stop_button.set_visible(False)
            self.menu_button.set_visible(False)

    def update_row(self, _downloader, download, chapter):
        chapter_id = chapter.id if chapter is not None else download.chapter.id

        for row in self.listbox:
            if row.download.chapter.id == chapter_id:
                row.download = download
                if row.download:
                    row.update()
                else:
                    self.listbox.remove(row)
                break

        if self.listbox.get_first_child() is None:
            # No more downloads
            self.stack.set_visible_child_name('empty')


class DownloadRow(Gtk.ListBoxRow):
    _selected = False

    def __init__(self, download):
        Gtk.ListBoxRow.__init__(self)

        self.add_css_class('download-manager-download-listboxrow')

        self.download = download

        if self.download.percent and download.chapter.pages:
            nb_pages = len(download.chapter.pages)
            counter = int((nb_pages / 100) * self.download.percent)
            fraction = self.download.percent / 100
        else:
            counter = None
            fraction = None

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        # Manga
        label = Gtk.Label(xalign=0)
        label.add_css_class('body')
        label.set_valign(Gtk.Align.CENTER)
        label.set_wrap(True)
        label.set_text(download.chapter.manga.name)
        hbox.append(label)

        # Progress label
        self.progress_label = Gtk.Label(xalign=0)
        self.progress_label.add_css_class('caption')
        self.progress_label.set_valign(Gtk.Align.CENTER)
        self.progress_label.set_wrap(True)
        text = _(Download.STATUSES[self.download.status]).upper() if self.download.status == 'error' else ''
        if counter:
            text = f'{text} {counter}/{nb_pages}'
        if text:
            self.progress_label.set_text(text)
        hbox.append(self.progress_label)

        vbox.append(hbox)

        # Chapter
        label = Gtk.Label(xalign=0)
        label.add_css_class('caption')
        label.set_valign(Gtk.Align.CENTER)
        label.set_wrap(True)
        label.set_text(download.chapter.title)
        vbox.append(label)

        # Progress bar
        self.progressbar = Gtk.ProgressBar()
        self.progressbar.set_show_text(False)
        if fraction:
            self.progressbar.set_fraction(fraction)
        vbox.append(self.progressbar)

        self.set_child(vbox)

    def update(self):
        """
        Updates chapter download progress
        """
        if not self.download.chapter.pages:
            return

        nb_pages = len(self.download.chapter.pages)
        counter = int((nb_pages / 100) * self.download.percent)
        fraction = self.download.percent / 100

        self.progressbar.set_fraction(fraction)
        text = _(Download.STATUSES[self.download.status]).upper() if self.download.status == 'error' else ''
        text = f'{text} {counter}/{nb_pages}'
        self.progress_label.set_text(text)
