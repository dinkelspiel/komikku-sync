# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
from gettext import ngettext
from queue import Empty
from queue import Queue
import threading
import time

from gi.repository import Adw
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Pango

from komikku.consts import COVER_HEIGHT
from komikku.consts import COVER_WIDTH
from komikku.consts import DOWNLOAD_MAX_DELAY
from komikku.consts import LOGO_SIZE
from komikku.consts import MISSING_IMG_RESOURCE_PATH
from komikku.models import Settings
from komikku.servers import LANGUAGES
from komikku.utils import convert_and_resize_image
from komikku.utils import CoverPicture
from komikku.utils import html_escape

THUMB_WIDTH = 41
THUMB_HEIGHT = 58


class ExplorerSearchStackPage:
    """ Superclass for search, latest updates, most popular and global search pages """

    def __init__(self, parent):
        self.parent = parent
        self.window = self.parent.window

        self.queue = Queue()
        self.status = None
        self.thread_covers = None
        self.thread_covers_stop_flag = False

    def clear(self):
        self.listbox.set_visible(False)

        # Empty queue
        while not self.queue.empty():
            try:
                self.queue.get()
                self.queue.task_done()
            except Empty:
                continue

        # Empty listbox
        row = self.listbox.get_first_child()
        while row:
            next_row = row.get_next_sibling()

            if isinstance(row, (ExplorerServerRow, ExplorerSearchResultRow)):
                row.dispose()

            self.listbox.remove(row)
            row = next_row

    def render_covers(self):
        """
        Fetch and display covers of result rows

        This method is interrupted when the navigation page is changed.
        It can be recalled when returning to it (when last page has been popped from the navigation stack).
        Remaining items in queue will be proceeded.
        """
        if self.thread_covers and self.thread_covers.is_alive():
            return

        def run():
            while not self.queue.empty() and self.thread_covers_stop_flag is False:
                try:
                    row, server = self.queue.get()
                except Empty:
                    continue
                else:
                    try:
                        data, _etag, rtime = server.get_image(row.manga_data['cover'])
                        if data:
                            # Covers in landscape format are converted to portrait format
                            data = convert_and_resize_image(data, COVER_WIDTH, COVER_HEIGHT)
                    except Exception:
                        pass
                    else:
                        GLib.idle_add(row.set_cover, data)

                        if rtime:
                            time.sleep(min(2 * rtime, DOWNLOAD_MAX_DELAY))

                    self.queue.task_done()

        self.thread_covers_stop_flag = False
        self.thread_covers = threading.Thread(target=run)
        self.thread_covers.daemon = True
        self.thread_covers.start()


class ExplorerSearchResultRow(Adw.ActionRow):
    __gtype_name__ = 'ExplorerSearchResultRow'

    def __init__(self, data):
        Adw.ActionRow.__init__(self, activatable=True, selectable=False)

        self.has_cover = 'cover' in data
        self.is_result = True
        self.manga_data = data
        self.cover_data = None

        self.set_title(html_escape(data['name']))
        self.set_title_lines(1)

        # Use subtitle to display additional info
        subtitle = []
        if nb_chapters := data.get('nb_chapters'):
            subtitle.append(ngettext('{0} chapter', '{0} chapters', nb_chapters).format(nb_chapters))
        if last_chapter := data.get('last_chapter'):
            subtitle.append(_('Last Chapter: {}').format(last_chapter))
        if last_volume := data.get('last_volume'):
            subtitle.append(_('Last Volume: {}').format(last_volume))

        if subtitle:
            self.set_subtitle(html_escape(' · '.join(subtitle)))
            self.set_subtitle_lines(1)

        if self.has_cover:
            self.cover_button = Gtk.Button()
            self.cover_button.add_css_class('explorer-search-cover-button')
            self.cover_button.props.focus_on_click = False
            self.cover_button.props.margin_top = 2
            self.cover_button.props.margin_bottom = 2
            self.cover_button.set_size_request(THUMB_WIDTH, THUMB_HEIGHT)
            self.cover_button.set_has_frame(False)
            self.cover_button_clicked_handler_id = self.cover_button.connect('clicked', self.on_cover_clicked)
            self.add_prefix(self.cover_button)

            self.popover = Gtk.Popover()
            self.popover.set_position(Gtk.PositionType.RIGHT)
            self.popover.set_parent(self.cover_button)

    def dispose(self):
        self.cover_data = None
        self.manga_data = None

        if self.has_cover:
            self.cover_button.disconnect(self.cover_button_clicked_handler_id)

            if self.popover.get_child():
                self.popover.set_child(None)

            self.popover.unparent()

    def on_cover_clicked(self, _button):
        if self.cover_data is None:
            return

        if not self.popover.get_child():
            picture = CoverPicture.new_from_data(self.cover_data, width=COVER_WIDTH)
            picture.add_css_class('cover-dropshadow')

            self.popover.set_child(picture)
            # Avoid vertical padding in popover content
            self.popover.get_first_child().props.valign = Gtk.Align.CENTER

        self.popover.popup()

    def set_cover(self, data):
        if not self.has_cover:
            return

        picture = CoverPicture.new_from_data(data, THUMB_WIDTH, THUMB_HEIGHT, True) if data else None
        if picture is None:
            picture = CoverPicture.new_from_resource(MISSING_IMG_RESOURCE_PATH, THUMB_WIDTH, THUMB_HEIGHT)
        else:
            self.cover_data = data
        picture.add_css_class('cover-dropshadow')

        self.cover_button.set_child(picture)


class ExplorerServerRow(Gtk.ListBoxRow):
    __gtype_name__ = 'ExplorerServerRow'

    def __init__(self, data, page):
        Gtk.ListBoxRow.__init__(self)

        self.page = page

        self.pin_button_toggled_handler_id = None
        self.local_folder_button_clicked_handler_id = None

        # Used in `explorer.servers` and `explorer.search` (global search) pages
        if page.props.tag == 'explorer.search':
            self.props.activatable = False
            self.add_css_class('explorer-server-section-listboxrow')
        else:
            self.props.activatable = True
            self.add_css_class('explorer-server-listboxrow')

        self.server_data = data
        if 'manga_initial_data' in data:
            self.manga_data = data.pop('manga_initial_data')

        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.set_child(self.box)

        # Server logo
        self.set_logo(use_fallback=False)

        # Server title & language
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        title = data['name']
        if data['lang']:
            subtitle = LANGUAGES[data['lang']]
        elif data['description']:
            subtitle = data['description']
        else:
            subtitle = None

        label = Gtk.Label(xalign=0, hexpand=True, vexpand=True)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_text(title)
        vbox.append(label)

        if subtitle:
            subtitle_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

            label = Gtk.Label(xalign=0)
            label.set_wrap(True)
            label.set_text(subtitle)
            label.add_css_class('subtitle')
            subtitle_box.append(label)

            if data['is_nsfw'] or data['is_nsfw_only']:
                label = Gtk.Label(xalign=0)
                label.set_markup('<b>' + _('18+') + '</b>')
                label.add_css_class('subtitle')
                label.add_css_class('warning')
                subtitle_box.append(label)

            vbox.append(subtitle_box)

        self.box.append(vbox)

        if page.props.tag == 'explorer.search':
            return

        # Server requires a user account
        if data['has_login']:
            login_image = Gtk.Image.new_from_icon_name('dialog-password-symbolic')
            self.box.append(login_image)

        # Info button
        if data['lang'] or data['id'] == 'local':
            button = Gtk.Button(valign=Gtk.Align.CENTER)
            button.set_icon_name('help-about-symbolic')
            if data['id'] == 'local':
                # Info button
                button.set_tooltip_text(_('Help'))
                title = _('Local Folder')
                message = [
                    _('A specific folder structure is required for local comics to be properly processed.'),
                    _('Each comic must have its own folder which must contain the chapters/volumes as archive files in CBZ, CBR, CBT, EPUB or PDF formats.'),
                    _("The folder's name will be used as name for the comic."),
                    _("NOTE: The 'unrar' or 'unar' command-line tool is required for CBR archives."),
                ]

                # Button to open local folder
                self.local_folder_button = Gtk.Button(valign=Gtk.Align.CENTER)
                self.local_folder_button.set_icon_name('folder-visiting-symbolic')
                self.local_folder_button.set_tooltip_text(_('Open local folder'))
                self.local_folder_button_clicked_handler_id = self.local_folder_button.connect(
                    'clicked', self.page.open_local_folder)
                self.box.append(self.local_folder_button)

            elif data['content']:
                button.set_tooltip_text(_('Content Information'))
                title = '\n'.join([
                    _('Content Information'),
                    data['name'],
                ])
                message = []
                if type := data['content'].type:
                    message.append(_('Type: {0}').format(', '.join(type)))
                if license := data['content'].license:
                    message.append(
                        _('Copyrighted: Reproduction and distribution authorized under certain conditions ({0} license)').format(license)
                    )
                elif data['content'].public_domain:
                    message.append(f'{_("Royalty-free, Public domain")}')
                else:
                    message.append(f'{_("Copyrighted works")}')

            else:
                button.set_tooltip_text(_('Content Information'))
                button.add_css_class('destructive-action')
                title = '\n'.join([
                    _('Content Information'),
                    data['name'],
                ])
                message = [
                    _('Use with caution!'),
                    _('Copyrighted works'),
                ]
                message.append(_('Licensed/Published and/or Unlicensed works'))
                message.append(_('It may be partially or totally illegal'))

            button.connect(
                'clicked',
                lambda x: self.page.window.open_dialog(
                    title,
                    body='\n\n'.join(message),
                    cancel_label=_('Close')
                )
            )
            self.box.append(button)

        # Button to pin/unpin
        self.pin_button = Gtk.ToggleButton(valign=Gtk.Align.CENTER)
        self.pin_button.set_icon_name('view-pin-symbolic')
        self.pin_button.set_tooltip_text(_('Toggle pinned status'))
        self.pin_button.set_active(data['id'] in Settings.get_default().pinned_servers)
        self.pin_button_toggled_handler_id = self.pin_button.connect(
            'toggled', self.page.toggle_server_pinned_state, self)
        self.box.append(self.pin_button)

    def dispose(self):
        if self.local_folder_button_clicked_handler_id:
            self.local_folder_button.disconnect(self.local_folder_button_clicked_handler_id)
        if self.pin_button_toggled_handler_id:
            self.pin_button.disconnect(self.pin_button_toggled_handler_id)

    def get_logo(self):
        server = getattr(self.server_data['module'], self.server_data['class_name'])()

        if not server.has_cf:
            if server.logo_path:
                # Avoid to fetch the same logo several times
                # In the case of servers belonging to a multi-language server and therefore sharing the same logo,
                # it's possible that logo has been previously fetched
                res = True
            else:
                try:
                    res = server.save_logo()
                except Exception:
                    res = False

            if res:
                self.server_data['logo_path'] = server.logo_path
            else:
                self.page.window.application.logger.info('Failed to get `%s` server logo', server.id)

        GLib.idle_add(self.set_logo)

    def set_logo(self, use_fallback=True):
        if self.server_data['logo_url']:
            if self.server_data['logo_path']:
                self.logo = Gtk.Image()
                self.logo.set_pixel_size(LOGO_SIZE)
                self.logo.set_from_file(self.server_data['logo_path'])
            elif use_fallback:
                # Fallback to an Adw.Avatar if logo fetching failed
                self.logo = Adw.Avatar.new(LOGO_SIZE, self.server_data['name'], True)
            else:
                self.logo = None
                return

        else:
            self.logo = Adw.Avatar.new(LOGO_SIZE, None, False)
            if self.server_data['id'] == 'local':
                self.logo.set_icon_name('folder-symbolic')
            else:
                self.logo.set_show_initials(True)
                self.logo.set_text(self.server_data['name'])

        if self.page.props.tag == 'explorer.search':
            # Align horizontally with covers in global search
            self.logo.set_margin_start(6)
            self.logo.set_margin_end(4)

        self.box.prepend(self.logo)


def get_server_default_search_filters(server):
    filters = {}

    if not server.filters:
        return filters

    for filter_ in server.filters:
        if filter_['type'] == 'select' and filter_['value_type'] == 'multiple':
            filters[filter_['key']] = [option['key'] for option in filter_['options'] if option['default']]
        else:
            filters[filter_['key']] = filter_['default']

    return filters


def set_missing_server_logos(listbox):
    def run():
        row = listbox.get_first_child()
        while row:
            if isinstance(row, ExplorerServerRow) and row.logo is None:
                row.get_logo()

            row = row.get_next_sibling()

    thread = threading.Thread(target=run)
    thread.daemon = True
    thread.start()
