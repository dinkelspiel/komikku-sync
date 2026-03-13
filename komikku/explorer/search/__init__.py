# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from copy import deepcopy
from gettext import gettext as _
import threading

from gi.repository import Adw
from gi.repository import GLib
from gi.repository import Gtk

from komikku.explorer.common import get_server_default_search_filters
from komikku.explorer.search.latest_updates import ExplorerSearchStackPageLatestUpdates
from komikku.explorer.search.most_popular import ExplorerSearchStackPageMostPopular
from komikku.explorer.search.search import ExplorerSearchStackPageSearch
from komikku.explorer.search.search_global import ExplorerSearchStackPageSearchGlobal
from komikku.models import create_db_connection
from komikku.models import Manga
from komikku.models import Settings
from komikku.utils import log_error_traceback


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/explorer_search.ui')
class ExplorerSearchPage(Adw.NavigationPage):
    __gtype_name__ = 'ExplorerSearchPage'

    title_stack = Gtk.Template.Child('title_stack')
    title = Gtk.Template.Child('title')
    viewswitcher = Gtk.Template.Child('viewswitcher')
    server_website_button = Gtk.Template.Child('server_website_button')
    filters_button = Gtk.Template.Child('filters_button')

    progressbar = Gtk.Template.Child('progressbar')
    stack = Gtk.Template.Child('stack')
    searchentry = Gtk.Template.Child('searchentry')
    filters_menu_button = Gtk.Template.Child('filters_menu_button')
    search_stack = Gtk.Template.Child('search_stack')
    search_listbox = Gtk.Template.Child('search_listbox')
    search_no_results_status_page = Gtk.Template.Child('search_no_results_status_page')
    search_intro_status_page = Gtk.Template.Child('search_intro_status_page')
    most_popular_stack = Gtk.Template.Child('most_popular_stack')
    most_popular_listbox = Gtk.Template.Child('most_popular_listbox')
    most_popular_no_results_status_page = Gtk.Template.Child('most_popular_no_results_status_page')
    latest_updates_stack = Gtk.Template.Child('latest_updates_stack')
    latest_updates_listbox = Gtk.Template.Child('latest_updates_listbox')
    latest_updates_no_results_status_page = Gtk.Template.Child('latest_updates_no_results_status_page')
    viewswitcherbar = Gtk.Template.Child('viewswitcherbar')

    page = None
    requests = {}
    search_global_mode = False
    search_filters = None
    server = None

    def __init__(self, parent):
        Adw.NavigationPage.__init__(self)

        self.parent = parent
        self.window = parent.window

        self.connect('hidden', self.on_hidden)
        self.connect('shown', self.on_shown)

        self.page_changed_handler_id = self.stack.connect('notify::visible-child-name', self.on_page_changed)

        self.server_website_button.connect('clicked', self.on_server_website_button_clicked)
        self.filters_button.connect('clicked', self.on_filters_button_clicked)

        self.searchentry.connect('activate', self.search)
        self.searchentry.connect('search-changed', self.on_search_changed)
        self.searchentry.connect('stop-search', self.on_search_stopped)

        self.filters_dialog = Adw.PreferencesDialog.new()
        self.filters_dialog.set_title(_('Filters'))
        self.filters_dialog.props.presentation_mode = Adw.DialogPresentationMode.BOTTOM_SHEET

        self.window.breakpoint.add_setter(self.viewswitcherbar, 'reveal', True)
        self.window.breakpoint.add_setter(self.title_stack, 'visible-child', self.title)

        self.latest_updates_page = ExplorerSearchStackPageLatestUpdates(self)
        self.most_popular_page = ExplorerSearchStackPageMostPopular(self)
        self.search_page = ExplorerSearchStackPageSearch(self)
        self.search_global_page = ExplorerSearchStackPageSearchGlobal(self)

    def add_actions(self):
        self.search_global_page.add_actions()

    def can_page_be_updated_with_results(self, page, server_id):
        self.requests[page].remove(server_id)

        if self.window.page != self.props.tag:
            # Not in Explorer search page
            return False
        if server_id != self.server.id:
            # server_id is not the current server
            return False
        if page != self.page:
            # page is not the current page
            return False

        return True

    def clear(self):
        self.search_page.clear()
        self.most_popular_page.clear()
        self.latest_updates_page.clear()

        self.search_global_mode = False

    def init_filters_dialog(self):
        defaults = get_server_default_search_filters(self.server)
        self.search_filters = deepcopy(defaults)

        # Hide filter menu button (global search only) in searchbar
        self.filters_menu_button.set_visible(False)

        # Show or hide filters button in headerbar
        if not self.search_filters:
            self.filters_button.set_visible(False)
            return

        self.filters_button.set_visible(True)
        self.filters_button.remove_css_class('accent')

        def build_entry(group, filter_):
            def on_changed(row):
                self.search_filters[filter_['key']] = row.get_text()

                if defaults != self.search_filters:
                    self.filters_button.add_css_class('accent')
                else:
                    self.filters_button.remove_css_class('accent')

            group.set_title(filter_['name'])

            row = Adw.EntryRow(title=filter_['description'])
            row.set_use_markup(True)
            row.connect('changed', on_changed)

            group.add(row)

            return group

        def build_select_single(group, filter_):
            def on_selected(row, _param):
                position = row.get_selected()
                self.search_filters[filter_['key']] = filter_['options'][position]['key']

                if defaults != self.search_filters:
                    self.filters_button.add_css_class('accent')
                else:
                    self.filters_button.remove_css_class('accent')

            labels = Gtk.StringList()
            selected_position = 0
            for index, option in enumerate(filter_['options']):
                labels.append(option['name'])
                if option['key'] == defaults[filter_['key']]:
                    selected_position = index

            row = Adw.ComboRow(title=filter_['name'], subtitle=filter_['description'])
            row.set_use_markup(True)
            row.set_model(labels)
            row.set_selected(selected_position)
            row.connect('notify::selected', on_selected)

            group.add(row)

            return group

        def build_select_multiple(group, filter_):
            def on_active(row, _param, key):
                if row.get_active():
                    self.search_filters[filter_['key']].append(key)
                else:
                    self.search_filters[filter_['key']].remove(key)

                if defaults != self.search_filters:
                    self.filters_button.add_css_class('accent')
                else:
                    self.filters_button.remove_css_class('accent')

            group.set_title(filter_['name'])
            group.set_description(filter_['description'])

            for option in filter_['options']:
                row = Adw.SwitchRow(title=option['name'])
                row.set_use_markup(True)
                row.set_active(option['key'] in defaults[filter_['key']])
                row.connect('notify::active', on_active, option['key'])

                group.add(row)

            return group

        def build_switch(group, filter_):
            def on_active(row, _param, key):
                self.search_filters[filter_['key']] = row.get_active()

                if defaults != self.search_filters:
                    self.filters_button.add_css_class('accent')
                else:
                    self.filters_button.remove_css_class('accent')

            row = Adw.SwitchRow(title=filter_['name'])
            row.set_use_markup(True)
            row.set_subtitle(filter_['description'])
            row.set_active(defaults[filter_['key']])
            row.connect('notify::active', on_active, filter_['key'])

            group.add(row)

            return group

        # Remove a previous used page if exists
        if page := self.filters_dialog.get_visible_page():
            self.filters_dialog.remove(page)

        page = Adw.PreferencesPage(title=_('Filters'))
        self.filters_dialog.add(page)

        for index, filter_ in enumerate(self.server.filters):
            group = Adw.PreferencesGroup()

            if filter_['type'] == 'select':
                if filter_['value_type'] == 'single':
                    build_select_single(group, filter_)
                elif filter_['value_type'] == 'multiple':
                    build_select_multiple(group, filter_)
                else:
                    raise ValueError('Invalid select value_type')  # noqa: TC003
            elif filter_['type'] == 'checkbox':
                build_switch(group, filter_)
            elif filter_['type'] == 'entry':
                build_entry(group, filter_)
            else:
                raise ValueError('Invalid filter type')  # noqa: TC003

            page.add(group)

    def on_filters_button_clicked(self, _button):
        self.filters_dialog.present(self.window)

    def on_hidden(self, _page):
        # Told thread covers to stop
        self.put_covers_rendering_on_hold()

        if self.window.previous_page == self.props.tag:
            # Don't clear on navigation push
            # The page must remain unchanged if the user comes back to this page
            return

        self.clear()

    def on_manga_clicked(self, _listbox, row):
        # Told thread covers to stop
        self.put_covers_rendering_on_hold()

        if self.search_global_mode:
            self.server = getattr(row.server_data['module'], row.server_data['class_name'])()

        self.show_manga_card(row.manga_data)

    def on_page_changed(self, _stack, _param):
        # Told thread covers to stop
        self.put_covers_rendering_on_hold()

        self.page = self.stack.props.visible_child_name

        if self.page == 'most_popular':
            self.most_popular_page.populate()
        elif self.page == 'latest_updates':
            self.latest_updates_page.populate()

    def on_search_changed(self, _entry):
        if not self.searchentry.get_text().strip():
            self.search_stack.set_visible_child_name('intro')
            self.on_search_stopped(_entry)

    def on_search_stopped(self, _entry):
        if self.page == 'search' and self.search_global_mode and self.search_global_page.lock:
            self.window.add_notification(_('Search was cancelled'), timeout=2)
            self.search_global_page.cancel()

    def on_server_website_button_clicked(self, _button):
        if self.server.base_url:
            Gtk.UriLauncher.new(uri=self.server.base_url).launch()
        else:
            self.window.add_notification(_('Oops, server website URL is unknown.'), timeout=2)

    def on_shown(self, _page):
        def do_render_covers():
            if self.window.last_navigation_action != 'pop':
                return

            # Last page has been popped from the navigation stack (user comes back)
            # Recall render_covers(), some covers may not yet have been processed
            if self.page == 'search':
                if self.search_global_mode:
                    self.search_global_page.render_covers()
                else:
                    self.search_page.render_covers()
            elif self.page == 'most_popular':
                self.most_popular_page.render_covers()
            elif self.page == 'latest_updates':
                self.latest_updates_page.render_covers()

        if not Gtk.Settings.get_default().get_property('gtk-enable-animations'):
            # When animations are disabled, popped/pushed events are sent after `shown` event (bug?)
            # Use idle_add to be sure that last `popped` or `pushed` event has been received
            GLib.idle_add(do_render_covers)
        else:
            do_render_covers()

    def put_covers_rendering_on_hold(self):
        if self.page == 'search':
            if self.search_global_mode:
                self.search_global_page.thread_covers_stop_flag = True
            else:
                self.search_page.thread_covers_stop_flag = True
        elif self.page == 'most_popular':
            self.most_popular_page.thread_covers_stop_flag = True
        elif self.page == 'latest_updates':
            self.latest_updates_page.thread_covers_stop_flag = True

    def register_request(self, page):
        if page not in self.requests:
            self.requests[page] = []

        self.requests[page].append(self.server.id)

    def reinstantiate_server(self, servers):
        """Used when servers modules origin change: server variable needs to be re-instantiated"""

        if self.server is None:
            return

        for server in servers:
            if server['id'] != self.server.id:
                continue

            self.server = getattr(server['module'], server['class_name'])()
            break

    def search(self, _entry=None):
        term = self.searchentry.get_text().strip()

        if self.search_global_mode:
            self.search_global_page.search(term)
            return

        self.search_page.search(term)

    def show(self, server=None):
        self.server = server
        self.search_global_mode = server is None

        if self.search_global_mode:
            self.search_global_page.init_filters_menu()
        else:
            self.init_filters_dialog()

        if not self.search_global_mode:
            # Search, Most Popular, Latest Updates
            self.title.set_title(self.server.name)

            has_search = self.server.true_search
            has_most_popular = getattr(self.server, 'get_most_populars', None) is not None
            has_latest_updates = getattr(self.server, 'get_latest_updates', None) is not None

            with self.stack.handler_block(self.page_changed_handler_id):
                self.stack.get_page(self.stack.get_child_by_name('most_popular')).set_visible(has_most_popular)
                self.stack.get_page(self.stack.get_child_by_name('latest_updates')).set_visible(has_latest_updates)
                self.stack.get_page(self.stack.get_child_by_name('search')).set_visible(has_search)

            if has_search:
                self.searchentry.props.placeholder_text = _('Search {}').format(self.server.name)
                self.searchentry.set_text('')
                self.search_intro_status_page.set_title(_('Search for Reading'))
                if self.server.id == 'local':
                    description = _('Empty search is allowed.')
                else:
                    description = _("""Alternatively, you can look up specific comics using the syntax:

<b>id:ID from comic URL</b>""")
                self.search_intro_status_page.set_description(description)
                self.search_stack.set_visible_child_name('intro')

            if has_search:
                start_page = 'search'
            elif has_most_popular:
                start_page = 'most_popular'
            elif has_latest_updates:
                start_page = 'latest_updates'

            viewswitcher_enabled = has_search + has_most_popular + has_latest_updates > 1
            if viewswitcher_enabled:
                self.viewswitcher.set_visible(True)
                self.viewswitcherbar.set_visible(True)
                if self.viewswitcherbar.get_reveal():
                    self.title_stack.set_visible_child(self.title)
                else:
                    self.title_stack.set_visible_child(self.viewswitcher)
            else:
                self.title_stack.set_visible_child(self.title)
                self.viewswitcher.set_visible(False)
                self.viewswitcherbar.set_visible(False)
            self.server_website_button.set_visible(self.server.id != 'local')
        else:
            # Global Search (use `search` page)
            self.title.set_title(_('Global Search'))

            self.searchentry.props.placeholder_text = _('Search globally by name')
            self.searchentry.set_text('')
            self.search_intro_status_page.set_title(_('Search for Comics'))
            self.search_intro_status_page.set_description('')
            self.search_stack.set_visible_child_name('intro')
            start_page = 'search'

            self.viewswitcher.set_visible(False)
            self.viewswitcherbar.set_visible(False)
            self.server_website_button.set_visible(False)

        self.page = start_page
        self.progressbar.set_fraction(0)
        # To be sure to be notify on next page change
        self.stack.set_visible_child_name('search')
        GLib.idle_add(self.stack.set_visible_child_name, start_page)

        self.window.navigationview.push(self)

    def show_manga_card(self, manga_data, server=None):
        def run_get(server, initial_data):
            try:
                manga_data = self.server.get_manga_data(initial_data)

                if manga_data is not None:
                    GLib.idle_add(complete_get, manga_data, server)
                else:
                    GLib.idle_add(error, server)
            except Exception as e:
                user_error_message = log_error_traceback(e)
                GLib.idle_add(error, server, user_error_message)

        def run_update(server, manga_id):
            manga = Manga.get(manga_id, server)
            try:
                success, chapters_changes, synced = manga.update_full()
                if success:
                    GLib.idle_add(complete_update, manga, server, chapters_changes, synced)
                else:
                    GLib.idle_add(error, server)
            except Exception as e:
                user_error_message = log_error_traceback(e)
                GLib.idle_add(error, server, user_error_message)

        def complete_get(manga_data, server):
            if server != self.server:
                return False

            self.window.activity_indicator.set_visible(False)

            manga = Manga.new(manga_data, self.server, Settings.get_default().long_strip_detection)

            self.window.card.init(manga)

        def complete_update(manga, server, chapters_changes, _synced):
            if chapters_changes['recent_ids']:
                # Auto download new chapters
                if Settings.get_default().new_chapters_auto_download and not manga.is_local:
                    self.window.downloader.add(chapters_changes['recent_ids'], emit_signal=True)
                    self.window.downloader.start()

                self.window.library.refresh_on_manga_state_changed(manga)

            if server != self.server:
                return False

            self.window.activity_indicator.set_visible(False)

            self.window.card.init(manga)

        def error(server, message=None):
            if server != self.server:
                return False

            self.window.activity_indicator.set_visible(False)

            self.window.add_notification(message or _("Oops, failed to retrieve manga's information."), timeout=2)

            return False

        self.window.activity_indicator.set_visible(True)

        if server is not None:
            self.server = server

        # Check if selected manga is already in database
        db_conn = create_db_connection()
        record = db_conn.execute(
            'SELECT * FROM mangas WHERE slug = ? AND server_id = ?',
            (manga_data['slug'], self.server.id)
        ).fetchone()

        if record:
            thread = threading.Thread(target=run_update, args=(self.server, record['id'], ))
        else:
            thread = threading.Thread(target=run_get, args=(self.server, manga_data, ))

        thread.daemon = True
        thread.start()
