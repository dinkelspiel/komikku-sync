# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import threading
import json

from gi.repository import Adw
from gi.repository import GLib
from gi.repository import Gtk

from komikku.consts import LOGO_SIZE
from komikku.models import Manga

class SyncRow(Adw.ActionRow):
    def __init__(self, window):
        self.window = window

        super().__init__(title="Cloud Sync", activatable=False)

        self.export_btn = Gtk.Button(valign=Gtk.Align.CENTER)
        self.export_btn.set_label(_('Export'))

        self.import_btn = Gtk.Button(valign=Gtk.Align.CENTER)
        self.import_btn.set_label(_('Import'))

        self.active = False
        """
        #granted, access_token_valid = self.tracker.is_granted()
        if False:
            self.active = True
            self.export_btn.set_label(_('Disconnect'))
            self.export_btn.set_css_classes(['destructive-action'])
        else:
            self.active = False

            if False:
                self.set_subtitle(_('Connection is expired'))
                self.export_btn.set_label(_('Reconnect'))
                self.export_btn.set_css_classes(['suggested-action'])
            else:
                self.export_btn.set_label(_('Connect'))
                self.export_btn.set_css_classes([])
        """

        self.export_btn.connect('clicked', self.on_export_btn_clicked)
        self.import_btn.connect('clicked', self.on_import_btn_clicked)
        self.add_suffix(self.export_btn)
        self.add_suffix(self.import_btn)

    def on_export_btn_clicked(self, _btn):
        group = None

        def open_dialog():
            nonlocal group

            group = Adw.PreferencesGroup()

            mangas = Manga.all()
            save = {}
            for manga in mangas:
                #for chapter in manga.chapters:
                #    print(str(vars(chapter)))
                _id = manga.slug
                save[_id] = {}
                save[_id]["chapters"] = [
                    {key: value for key, value in vars(chapter).items() if key in ["num", "read"]}
                    for chapter in manga.chapters
                ]

                save[_id]["slug"]      = manga.slug
                save[_id]["server_id"] = manga.server_id

            blob_label = Gtk.Label(
                label=json.dumps(save, ensure_ascii=False, indent=2),
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

            username_entry = Adw.EntryRow(title=_('Username'))
            username_entry.add_prefix(Gtk.Image.new_from_icon_name('avatar-default-symbolic'))
            group.add(username_entry)

            password_entry = Adw.PasswordEntryRow(title=_('Password'))
            password_entry.add_prefix(Gtk.Image.new_from_icon_name('dialog-password-symbolic'))
            group.add(password_entry)

            self.window.open_dialog(
                "Cloud Sync",
                child=group,
                confirm_label=_('Connect'),
                confirm_callback=connect_dialog
            )

        def connect_dialog():
            username_entry = group.get_row(0)
            password_entry = group.get_row(1)
            #success, error = self.tracker.request_access_token(username_entry.get_text(), password_entry.get_text())
            GLib.idle_add(connect_finish, success, error)

        def connect_webview():
            #success, error = self.tracker.request_access_token()
            GLib.idle_add(connect_finish, success, error)

        def connect_finish(success, error):
            if success:
                self.active = True
                self.export_btn.set_label(_('Disconnect'))
                self.export_btn.set_css_classes(['destructive-action'])

            elif error == 'load_failed':
                self.window.preferences.add_toast(Adw.Toast.new(_('Failed to request client access')))

            elif error == 'locked':
                self.window.preferences.add_toast(Adw.Toast.new(_('Webview is currently in used. Please retry later.')))

            elif error == 'canceled':
                self.window.preferences.add_toast(Adw.Toast.new(error))

        def disconnect():
            #self.tracker.data = None

            self.active = False
            self.export_btn.set_label(_('Connect'))
            self.export_btn.set_css_classes([])

        if not self.active:
            """
            if self.tracker.authorize_url:
                thread = threading.Thread(target=connect_webview)
                thread.daemon = True
                thread.start()
            else:
                open_dialog()
            """
            open_dialog()

        else:
            self.window.open_dialog(
                _('Disconnect from Cloud'),
                confirm_label=_('Disconnect'),
                confirm_callback=disconnect,
                confirm_appearance=Adw.ResponseAppearance.DESTRUCTIVE
            )

    def on_import_btn_clicked(self, _btn):
        group = None

        def open_dialog():
            nonlocal group

            group = Adw.PreferencesGroup()

            import_entry = Adw.EntryRow(title=_('Import'))
            import_entry.add_prefix(Gtk.Image.new_from_icon_name('avatar-default-symbolic'))
            group.add(import_entry)

            username_entry = Adw.EntryRow(title=_('Username'))
            username_entry.add_prefix(Gtk.Image.new_from_icon_name('avatar-default-symbolic'))
            group.add(username_entry)

            password_entry = Adw.PasswordEntryRow(title=_('Password'))
            password_entry.add_prefix(Gtk.Image.new_from_icon_name('dialog-password-symbolic'))
            group.add(password_entry)

            self.window.open_dialog(
                "Cloud Sync",
                child=group,
                confirm_label=_('Connect'),
                confirm_callback=connect_dialog
            )

        def connect_dialog():
            username_entry = group.get_row(0)
            password_entry = group.get_row(1)
            #success, error = self.tracker.request_access_token(username_entry.get_text(), password_entry.get_text())
            GLib.idle_add(connect_finish, success, error)

        def connect_webview():
            #success, error = self.tracker.request_access_token()
            GLib.idle_add(connect_finish, success, error)

        def connect_finish(success, error):
            if success:
                self.active = True
                self.export_btn.set_label(_('Disconnect'))
                self.export_btn.set_css_classes(['destructive-action'])

            elif error == 'load_failed':
                self.window.preferences.add_toast(Adw.Toast.new(_('Failed to request client access')))

            elif error == 'locked':
                self.window.preferences.add_toast(Adw.Toast.new(_('Webview is currently in used. Please retry later.')))

            elif error == 'canceled':
                self.window.preferences.add_toast(Adw.Toast.new(error))

        def disconnect():
            #self.tracker.data = None

            self.active = False
            self.export_btn.set_label(_('Connect'))
            self.export_btn.set_css_classes([])

        if not self.active:
            """
            if self.tracker.authorize_url:
                thread = threading.Thread(target=connect_webview)
                thread.daemon = True
                thread.start()
            else:
                open_dialog()
            """
            open_dialog()

        else:
            self.window.open_dialog(
                _('Disconnect from Cloud'),
                confirm_label=_('Disconnect'),
                confirm_callback=disconnect,
                confirm_appearance=Adw.ResponseAppearance.DESTRUCTIVE
            )
