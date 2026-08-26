# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>
# Author: Willem Dinkelspiel <mail@keii.dev>

from gettext import gettext as _
import logging
import threading

from gi.repository import Adw
from gi.repository import GLib
from gi.repository import Gtk

from komikku.models import Manga
from komikku.models import SyncedState
from komikku.sync import import_synced_state

logger = logging.getLogger(__name__)


class SyncRow(Adw.ActionRow):
    def __init__(self, window):
        self.window = window

        super().__init__(title=_('Sync State'), activatable=False)

        self.export_btn = Gtk.Button(valign=Gtk.Align.CENTER)
        self.export_btn.set_label(_('Export'))

        self.import_btn = Gtk.Button(valign=Gtk.Align.CENTER)
        self.import_btn.set_label(_('Import'))

        self.export_btn.connect('clicked', self.on_export_btn_clicked)
        self.import_btn.connect('clicked', self.on_import_btn_clicked)
        self.add_suffix(self.export_btn)
        self.add_suffix(self.import_btn)

    def on_export_btn_clicked(self, _btn):
        def run_export():
            try:
                blob = SyncedState.from_mangas(Manga.all()).to_text()
                GLib.idle_add(open_dialog, blob)
            except Exception:
                logger.exception('Failed to export sync data')
                GLib.idle_add(export_failed)

        def open_dialog(blob):
            group = Adw.PreferencesGroup()

            blob_label = Gtk.Label(
                label=blob,
                selectable=True,
                wrap=True,
                xalign=0,
            )
            blob_label.set_margin_top(12)
            blob_label.set_margin_bottom(12)
            blob_label.set_margin_start(12)
            blob_label.set_margin_end(12)

            blob_row = Gtk.ListBoxRow()
            blob_row.set_activatable(False)
            blob_row.set_selectable(False)
            blob_row.set_child(blob_label)
            group.add(blob_row)

            self.window.open_dialog(
                _('Sync State'),
                child=group,
                cancel_label=_('Close')
            )
            export_finished()

        def export_failed():
            export_finished()
            self.window.preferences.add_toast(Adw.Toast.new(_('Failed to export sync data')))

        def export_finished():
            self.window.activity_indicator.set_visible(False)
            self.export_btn.set_sensitive(True)
            self.import_btn.set_sensitive(True)

        self.window.activity_indicator.set_visible(True)
        self.export_btn.set_sensitive(False)
        self.import_btn.set_sensitive(False)
        thread = threading.Thread(target=run_export, daemon=True)
        thread.start()

    def on_import_btn_clicked(self, _btn):
        import_entry = None

        def open_dialog():
            nonlocal import_entry

            group = Adw.PreferencesGroup()

            import_entry = Gtk.TextView(
                accepts_tab=False,
                bottom_margin=12,
                height_request=120,
                left_margin=12,
                right_margin=12,
                top_margin=12,
                wrap_mode=Gtk.WrapMode.WORD_CHAR,
            )
            group.add(import_entry)

            self.window.open_dialog(
                _('Sync State'),
                child=group,
                confirm_label=_('Import'),
                confirm_callback=import_data
            )

        def import_data():
            buffer = import_entry.get_buffer()
            text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

            try:
                state = SyncedState.from_text(text.strip())
            except (TypeError, ValueError):
                self.window.preferences.add_toast(Adw.Toast.new(_('Invalid sync data')))
                return

            self.window.preferences.add_toast(Adw.Toast.new(_('Importing sync data…')))
            self.window.activity_indicator.set_visible(True)
            thread = threading.Thread(target=run_import, args=(state,), daemon=True)
            thread.start()

        def run_import(state):
            imported, updated, failed = import_synced_state(state)
            GLib.idle_add(import_finished, imported, updated, failed)

        def import_finished(imported, updated, failed):
            self.window.activity_indicator.set_visible(False)
            self.window.library.populate()
            if failed:
                message = _('%d manga imported, %d chapters updated, %d failed') % (imported, updated, failed)
            else:
                message = _('%d manga imported, %d chapters updated') % (imported, updated)
            self.window.preferences.add_toast(Adw.Toast.new(message))

        open_dialog()


class CloudSyncRow(Adw.ActionRow):
    def __init__(self, window):
        self.window = window
        self.controller = window.cloud_sync

        super().__init__(title=_('Cloud Sync'), activatable=False)

        self.btn = Gtk.Button(valign=Gtk.Align.CENTER)
        self.btn.connect('clicked', self.on_btn_clicked)
        self.add_suffix(self.btn)
        self.update_state()

    def update_state(self):
        if self.controller.authenticated:
            self.set_subtitle(f'{self.controller.dao.username} - {self.controller.dao.server}')
            self.btn.set_label(_('Log Out'))
            self.btn.set_css_classes(['destructive-action'])
        elif self.controller.dao.configured:
            self.set_subtitle(_('Connection is expired'))
            self.btn.set_label(_('Reconnect'))
            self.btn.set_css_classes(['suggested-action'])
        else:
            self.set_subtitle('')
            self.btn.set_label(_('Log In'))
            self.btn.set_css_classes(['suggested-action'])

    def on_btn_clicked(self, _btn):
        if self.controller.authenticated:
            self.window.open_dialog(
                _('Log Out of Cloud Sync?'),
                confirm_label=_('Log Out'),
                confirm_callback=self.logout,
                confirm_appearance=Adw.ResponseAppearance.DESTRUCTIVE,
            )
        else:
            self.open_login_dialog()

    def open_login_dialog(self, reconnect=False):
        group = Adw.PreferencesGroup()
        server_entry = Adw.EntryRow(title=_('Server'))
        server_entry.set_text(self.controller.dao.server or 'http://localhost:8010')
        group.add(server_entry)

        username_entry = Adw.EntryRow(title=_('Username'))
        username_entry.set_text(self.controller.dao.username or '')
        username_entry.add_prefix(Gtk.Image.new_from_icon_name('avatar-default-symbolic'))
        group.add(username_entry)

        password_entry = Adw.PasswordEntryRow(title=_('Password'))
        password_entry.add_prefix(Gtk.Image.new_from_icon_name('dialog-password-symbolic'))
        group.add(password_entry)

        def connect():
            self.btn.set_sensitive(False)
            self.controller.login_async(
                server_entry.get_text(),
                username_entry.get_text(),
                password_entry.get_text(),
                self.login_finished,
            )

        title = _('Cloud Sync Login') if not reconnect else _('Cloud Sync Login Required')
        self.window.open_dialog(
            title,
            child=group,
            confirm_label=_('Connect'),
            confirm_callback=connect,
        )

    def login_finished(self, success, error, result):
        self.btn.set_sensitive(True)
        if not success:
            self.window.preferences.add_toast(Adw.Toast.new(error))
            return
        self.update_state()
        imported, updated, failed = result
        if failed:
            message = _('%d manga imported, %d chapters updated, %d failed') % (imported, updated, failed)
        else:
            message = _('%d manga imported, %d chapters updated') % (imported, updated)
        self.window.preferences.add_toast(Adw.Toast.new(message))

    def logout(self):
        self.controller.logout()
        self.update_state()
