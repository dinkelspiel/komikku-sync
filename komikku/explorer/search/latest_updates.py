# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import gc
from gettext import gettext as _
import threading

from gi.repository import GLib

from komikku.explorer.common import ExplorerSearchResultRow
from komikku.explorer.common import ExplorerSearchStackPage
from komikku.models import Settings
from komikku.utils import log_error_traceback


class ExplorerSearchStackPageLatestUpdates(ExplorerSearchStackPage):
    __gtype_name__ = 'ExplorerSearchStackPageLatestUpdates'

    def __init__(self, parent):
        ExplorerSearchStackPage.__init__(self, parent)

        self.stack = self.parent.latest_updates_stack
        self.listbox = self.parent.latest_updates_listbox
        self.no_results_status_page = self.parent.latest_updates_no_results_status_page

        self.listbox.connect('row-activated', self.parent.on_manga_clicked)

        self.no_results_status_page.get_child().connect('clicked', self.populate)

    def populate(self, *args):
        def run(server):
            self.parent.register_request('latest_updates')

            try:
                if results := server.get_latest_updates(**self.parent.search_filters):
                    GLib.idle_add(complete, results, server)
                else:
                    GLib.idle_add(error, results, server)
            except Exception as e:
                GLib.idle_add(error, None, server, *log_error_traceback(e))
            finally:
                gc.collect()

        def complete(results, server):
            if not self.parent.can_page_be_updated_with_results('latest_updates', server.id):
                return

            self.listbox.set_visible(True)

            for item in results:
                row = ExplorerSearchResultRow(item)
                self.listbox.append(row)
                if row.has_cover:
                    self.queue.put((row, server))

            self.stack.set_visible_child_name('results')

            self.render_covers()

        def error(results, server, message=None, stack_trace=None):
            if stack_trace is not None and Settings.get_default().servers_bug_report:
                context = '\n'.join([
                    'Failed to fetch Latest Updates',
                    f'- Server ID: {server.id}',
                    f'- Server URL: {server.base_url}',
                ])
                self.window.open_server_bug_report_dialog(server, context, stack_trace)

            if not self.parent.can_page_be_updated_with_results('latest_updates', server.id):
                return

            if results is None:
                self.no_results_status_page.set_title(_('Oops, failed to retrieve latest updates.'))
                if message:
                    self.no_results_status_page.set_description(message)
            else:
                self.no_results_status_page.set_title(_('No Latest Updates Found'))

            self.stack.set_visible_child_name('no_results')

        self.clear()
        self.stack.set_visible_child_name('loading')

        if self.parent.requests.get('latest_updates') and self.parent.server.id in self.parent.requests['latest_updates']:
            self.window.add_notification(_('A request is already in progress.'), timeout=2)
            return

        thread = threading.Thread(target=run, args=(self.parent.server, ))
        thread.daemon = True
        thread.start()
