# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
import gc
from gettext import gettext as _
import threading

from gi.repository import Adw
from gi.repository import GLib
from gi.repository import Gio
from gi.repository import Gtk
from gi.repository import Pango

from komikku.models import Settings
from komikku.servers import LANGUAGES
from komikku.utils import log_error_traceback

from komikku.explorer.common import ExplorerServerRow
from komikku.explorer.common import ExplorerSearchResultRow
from komikku.explorer.common import ExplorerSearchStackPage
from komikku.explorer.common import get_server_default_search_filters
from komikku.explorer.common import set_missing_server_logos


class ExplorerSearchStackPageSearchGlobal(ExplorerSearchStackPage):
    __gtype_name__ = 'ExplorerSearchStackPageSearchGlobal'

    lock = False
    selected_filters = []
    server_ids = []

    def __init__(self, parent):
        ExplorerSearchStackPage.__init__(self, parent)

        self.stack = self.parent.search_stack
        self.listbox = self.parent.search_listbox  # shared with explorer.search page
        self.filters_menu_button = self.parent.filters_menu_button

        self.selected_filters = Settings.get_default().explorer_search_global_selected_filters

        self.window.builder.add_from_resource('/info/febvre/Komikku/ui/menu/explorer_search_global_search.xml')
        self.filters_menu_button.set_menu_model(self.window.builder.get_object('menu-explorer-search-global-search'))

    def add_actions(self):
        action = Gio.SimpleAction.new_stateful(
            'explorer.search.global.search.pinned', None, GLib.Variant('b', 'pinned' in self.selected_filters)
        )
        action.connect('change-state', self.on_menu_action_changed)
        self.window.application.add_action(action)

    def cancel(self):
        def do_cancel():
            if self.status in ('ended', 'cancelled'):
                return False
            if self.status == 'started':
                return True

            self.status = 'cancelling'
            self.window.webview.cancel_challengers(self.server_ids, context='search')

        GLib.idle_add(do_cancel)

    def init_filters_menu(self):
        # Show filter menu button in searchbar
        self.filters_menu_button.set_visible(True)
        # Hide filters button in headerbar
        self.parent.filters_button.set_visible(False)

        if self.selected_filters:
            self.filters_menu_button.add_css_class('accent')
        else:
            self.filters_menu_button.remove_css_class('accent')

    def on_menu_action_changed(self, action, variant):
        value = variant.get_boolean()
        action.set_state(GLib.Variant('b', value))
        name = action.props.name.split('.')[-1]

        if value:
            self.selected_filters.add(name)
        else:
            self.selected_filters.remove(name)
        Settings.get_default().explorer_search_global_selected_filters = self.selected_filters

        if self.selected_filters:
            self.filters_menu_button.add_css_class('accent')
        else:
            self.filters_menu_button.remove_css_class('accent')

    def search(self, term):
        if self.lock:
            self.window.add_notification(_('A request is already in progress.'), timeout=2)
            return

        def run(servers):
            with ThreadPoolExecutor(max_workers=len(servers)) as executor:
                tasks = {}
                for server_data in servers:
                    future = executor.submit(search_server, server_data)
                    tasks[future] = server_data

                self.status = 'ongoing'

                for index, future in enumerate(as_completed(tasks)):
                    if self.window.page != self.parent.props.tag and self.window.previous_page != self.parent.props.tag:
                        executor.shutdown(False, cancel_futures=True)
                        break

                    server_data = tasks[future]
                    try:
                        results = future.result()
                    except Exception as exc:
                        user_error_message, _stack_trace = log_error_traceback(exc)
                        GLib.idle_add(complete_server, None, server_data, user_error_message)
                    else:
                        GLib.idle_add(complete_server, results, server_data)

                    self.parent.progressbar.set_fraction((index + 1) / len(servers))

            gc.collect()

            GLib.idle_add(complete)

        def complete():
            self.status = 'ended' if self.status == 'ongoing' else 'cancelled'
            self.lock = False
            self.parent.progressbar.set_fraction(0)

        def complete_server(results, server_data, message=None):
            server = getattr(server_data['module'], server_data['class_name'])()

            # Remove spinner
            for row in self.listbox:
                if row.server_data['lang'] == server.lang and row.server_data['name'] == server.name:
                    if row.position == 0:
                        row.results = results is not None and len(results) > 0
                    elif row.position == 1:
                        self.listbox.remove(row)
                        break

            if results:
                # Add results
                for index, item in enumerate(results):
                    row = ExplorerSearchResultRow(item)
                    row.server_data = server_data
                    row.position = index + 1
                    row.results = True
                    self.listbox.append(row)

                    if row.has_cover:
                        self.queue.put((row, server))
            else:
                # Error, cancelled or no results
                row = Gtk.ListBoxRow(activatable=False)
                row.server_data = server_data
                row.position = 1
                row.results = False
                row.is_result = False
                row.add_css_class('explorer-server-listboxrow')
                label = Gtk.Label(halign=Gtk.Align.CENTER, justify=Gtk.Justification.CENTER)
                if results is None:
                    if self.status == 'cancelling':
                        text = _('Search cancelled')
                    else:
                        # Error
                        text = _('Oops, search failed. Please try again.')
                        if message:
                            text = f'{text}\n{message}'
                else:
                    # No results
                    text = _('No results')
                label.set_markup(f'<i>{text}</i>')
                label.set_ellipsize(Pango.EllipsizeMode.END)
                row.set_child(label)

                self.listbox.append(row)

            self.listbox.invalidate_sort()

            self.render_covers()

        def search_server(server_data):
            server = getattr(server_data['module'], server_data['class_name'])()
            filters = get_server_default_search_filters(server)

            return server.search(term, **filters)

        def sort_results(row1, row2):
            """
            This function gets two children and has to return:
            - a negative integer if the first one should come before the second one
            - zero if they are equal
            - a positive integer if the second one should come before the firstone
            """
            row1_results = row1.results
            row1_server_lang = LANGUAGES.get(row1.server_data['lang'], '')
            row1_server_name = row1.server_data['name']
            row1_position = row1.position

            row2_results = row2.results
            row2_server_lang = LANGUAGES.get(row2.server_data['lang'], '')
            row2_server_name = row2.server_data['name']
            row2_position = row2.position

            # Servers with results first
            if row1_results and not row2_results:
                return -1
            if not row1_results and row2_results:
                return 1

            # Sort by language
            if row1_server_lang < row2_server_lang:
                return -1

            if row1_server_lang == row2_server_lang:
                # Sort by server name
                if row1_server_name < row2_server_name:
                    return -1

                # Sort by position
                if row1_server_name == row2_server_name and row1_position < row2_position:
                    return -1

            return 1

        self.clear()

        if 'pinned' in self.selected_filters:
            servers = []
            pinned_servers = Settings.get_default().pinned_servers
            for server_data in self.parent.parent.servers_page.servers:
                if server_data['id'] not in pinned_servers:
                    continue

                servers.append(server_data)
        else:
            servers = self.parent.parent.servers_page.servers

        # Init results list
        self.server_ids = []
        for server_data in servers:
            self.server_ids.append(server_data['id'])

            # Server row
            row = ExplorerServerRow(server_data, self.parent)
            row.server_data = server_data
            row.position = 0
            row.results = False
            row.is_result = False
            self.listbox.append(row)

            # Spinner
            row = Gtk.ListBoxRow(activatable=False)
            row.server_data = server_data
            row.position = 1
            row.results = False
            row.is_result = False
            row.add_css_class('explorer-server-listboxrow')
            spinner = Adw.Spinner()
            row.set_child(spinner)
            self.listbox.append(row)

        set_missing_server_logos(self.listbox)

        self.lock = True
        self.status = 'started'
        self.stack.set_visible_child_name('results')
        self.listbox.set_sort_func(sort_results)
        self.listbox.set_visible(True)

        thread = threading.Thread(target=run, args=(servers, ))
        thread.daemon = True
        thread.start()
