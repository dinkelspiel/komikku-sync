# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
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
from komikku.utils import convert_and_resize_image
from komikku.utils import CoverPicture
from komikku.utils import html_escape
from komikku.utils import log_error_traceback

THUMB_WIDTH = 96
THUMB_HEIGHT = 136


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/card_tracking.ui')
class TrackingDialog(Adw.PreferencesDialog):
    __gtype_name__ = 'TrackingDialog'

    group = Gtk.Template.Child('group')
    selected_tracker_row = None
    tracker_rows = []

    def __init__(self, window):
        super().__init__(follows_content_size=True)

        self.window = window

        for _id, tracker in self.window.trackers.trackers.items():
            row = TrackerRow(window, tracker)
            self.group.add(row)
            self.tracker_rows.append(row)

        self.search_subpage = TrackingSearchSubPage(self.window)
        self.search_subpage.connect('hiding', self.on_search_subpage_hiding)

        self.connect('closed', self.on_closed)

    def add_tracking(self, id):
        def run():
            manga = self.window.card.manga
            if manga.tracking is None:
                manga.tracking = {}

            tracker = self.selected_tracker_row.tracker
            data = tracker.get_manga_data(id)
            if data:
                data['_synced'] = True

                manga.tracking[tracker.id] = data

                manga.update({'tracking': manga.tracking})

            GLib.idle_add(complete, data)

        def complete(data):
            if data is None:
                self.add_toast(Adw.Toast.new(_('Failed to get data from tracker')))
                return

            self.pop_subpage()
            self.selected_tracker_row.init(data)

        self.selected_tracker_row.set_arrow_visible(True)
        self.selected_tracker_row.btn.set_visible(False)

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()

    def on_closed(self, _dialog):
        self.window.trackers.sync()
        self.pop_subpage()

    def on_search_subpage_hiding(self, _page):
        self.search_subpage.thread_covers_stop_flag = True
        self.search_subpage.clear()

    def show(self):
        count = 0
        for tracker_row in self.tracker_rows:
            if tracker_row.init():
                count += 1

        if count == 0:
            self.window.add_notification(_('No tracking services available'))
            return

        self.present(self.window)

    def show_search(self, tracker):
        self.push_subpage(self.search_subpage)
        self.search_subpage.init(tracker, self.window.card.manga.name)


class TracherResultRow(Gtk.ListBoxRow):
    def __init__(self, window, data):
        self.window = window
        self.data = data

        super().__init__()

        box = Gtk.Box(margin_top=6, margin_bottom=6, margin_start=6, margin_end=6, spacing=6)

        self.cover_bin = Adw.Bin()
        self.cover_bin.set_size_request(THUMB_WIDTH, THUMB_HEIGHT)
        box.append(self.cover_bin)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        hbox = Gtk.Box(spacing=6)

        vbox_details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        title = Gtk.Label(
            label=html_escape(data['name']),
            use_markup=True,
            ellipsize=Pango.EllipsizeMode.END,
            xalign=0,
            hexpand=True
        )
        title.add_css_class('title')
        vbox_details.append(title)

        if data.get('authors'):
            label = Gtk.Label(
                label=html_escape(data['authors']),
                use_markup=True,
                ellipsize=Pango.EllipsizeMode.END,
                xalign=0,
                hexpand=True
            )
            label.add_css_class('subtitle')
            vbox_details.append(label)

        details = []
        if data.get('start_date'):
            details.append(data['start_date'])

        if 'status' in data:
            details.append(data['status'] or _('Unknown status'))

        if data.get('score'):
            details.append(f'{data["score"]}/10')

        label = Gtk.Label(
            label=' · '.join(details),
            use_markup=True,
            ellipsize=Pango.EllipsizeMode.END,
            xalign=0,
            hexpand=True
        )
        label.add_css_class('subtitle')
        vbox_details.append(label)

        hbox.append(vbox_details)
        vbox.append(hbox)
        box.append(vbox)

        if data.get('synopsis'):
            label = Gtk.Label(
                label=html_escape(data['synopsis'].replace('\n', '')),
                use_markup=True,
                ellipsize=Pango.EllipsizeMode.END,
                xalign=0,
                hexpand=True,
                lines=4,
                wrap=True
            )
            label.add_css_class('caption')
            vbox.append(label)

        self.btn = Gtk.Button(valign=Gtk.Align.START)
        self.btn.set_label(_('Track'))
        self.btn.connect('clicked', lambda _btn: self.window.card.tracking_dialog.add_tracking(data['id']))
        hbox.append(self.btn)

        self.set_child(box)

    def set_cover(self, data):
        picture = CoverPicture.new_from_data(data, THUMB_WIDTH, THUMB_HEIGHT, True) if data else None
        if picture is None:
            picture = CoverPicture.new_from_resource(MISSING_IMG_RESOURCE_PATH, THUMB_WIDTH, THUMB_HEIGHT)

        self.cover_bin.set_child(picture)


class TrackerRow(Adw.ExpanderRow):
    def __init__(self, window, tracker):
        self.window = window
        self.tracker = tracker

        super().__init__(title=self.tracker.name)

        self.set_logo()

        self.set_arrow_visible(False)

        self.btn = Gtk.Button(valign=Gtk.Align.CENTER)
        self.btn.set_label(_('Use'))
        self.btn.connect('clicked', self.on_btn_clicked)
        self.add_suffix(self.btn)

        # Action (tracker page, delete)
        self.action_row = Adw.ActionRow()
        cancel_button = Gtk.Button.new_from_icon_name('user-trash-symbolic')
        cancel_button.props.valign = Gtk.Align.CENTER
        cancel_button.set_tooltip_text(_('Cancel Tracking'))
        cancel_button.connect('clicked', self.cancel_tracking)
        self.action_row.add_suffix(cancel_button)
        self.add_row(self.action_row)

        # Status
        self.status_row = Adw.ComboRow(title=_('Status'))
        statuses = Gtk.StringList()
        for _status, internal_status in self.tracker.STATUSES_MAPPING.items():
            statuses.append(_(self.tracker.INTERNAL_STATUSES[internal_status]))
        self.status_row.set_model(statuses)
        self.status_changed_handler_id = self.status_row.connect('notify::selected', self.update_tracking_data)
        self.add_row(self.status_row)

        # Score
        self.score_row = Adw.SpinRow(title=_('Score'), wrap=True)
        self.score_changed_handler_id = self.score_row.connect('notify::value', self.update_tracking_data)
        self.add_row(self.score_row)

        # Chapters progress
        self.chapters_progress_row = Adw.SpinRow(title=_('Chapter'), wrap=True)
        self.num_chapter_changed_handler_id = self.chapters_progress_row.connect('notify::value', self.update_tracking_data)
        self.add_row(self.chapters_progress_row)

    def cancel_tracking(self, _btn):
        def confirm_callback():
            manga = self.window.card.manga
            manga.tracking.pop(self.tracker.id)
            manga.update({'tracking': manga.tracking})
            self.init()

        self.window.open_dialog(
            _('Delete?'),
            body=_('Are you sure you want to cancel tracking?'),
            confirm_label=_('Delete'),
            confirm_callback=confirm_callback,
            confirm_appearance=Adw.ResponseAppearance.DESTRUCTIVE
        )

    def get_logo(self):
        def run():
            try:
                res = self.tracker.save_logo()
            except Exception:
                res = False

            GLib.idle_add(complete, res)

        def complete(res):
            if not res:
                self.window.application.logger.info('Failed to get `%s` tracker logo', self.tracker.id)

            self.set_logo(use_fallback=True)

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()

    def init(self, data=None):
        def run():
            try:
                id = self.window.card.manga.tracking[self.tracker.id]['id']
                data = self.tracker.get_manga_data(id)
            except Exception as e:
                log_error_traceback(e)
                data = None

            if data is None:
                data = self.window.card.manga.tracking[self.tracker.id]

            GLib.idle_add(complete, data)

        def complete(data):
            if data is None:
                # Failed to get data from tracker (connection error, server error or invalid request)
                return

            self.set_enable_expansion(True)
            self.set_expanded(True)
            self.set_arrow_visible(True)
            self.set_activatable(True)
            self.set_subtitle('')
            self.btn.set_visible(False)

            if data.get('url'):
                tracker_manga_url = data['url']
            else:
                tracker_manga_url = self.tracker.get_manga_url(data['id'])
            self.action_row.set_title(f'<a href="{tracker_manga_url}">{html_escape(data["name"])}</a>')

            with self.chapters_progress_row.handler_block(self.num_chapter_changed_handler_id):
                adj = Gtk.Adjustment(
                    value=float(data['chapters_progress']) or 0,
                    lower=0,
                    upper=data['chapters'] or 10000,
                    step_increment=1,
                    page_increment=10
                )
                self.chapters_progress_row.set_adjustment(adj)

            with self.score_row.handler_block(self.score_changed_handler_id):
                self.score_row.format = self.tracker.get_user_score_format(data['score_format'])
                adj = Gtk.Adjustment(
                    value=data['score'] or 0,
                    lower=self.score_row.format['min'],
                    upper=self.score_row.format['max'],
                    step_increment=self.score_row.format['step'],
                )
                self.score_row.configure(adj, 0, self.score_row.format['step'] * 10 if self.score_row.format['step'] != 1 else 0)

            with self.status_row.handler_block(self.status_changed_handler_id):
                self.status_row.set_selected(self.tracker.get_status_index(data['status']))

        # Is the tracker granted?
        granted, access_token_valid = self.tracker.is_granted()
        self.set_visible(granted)

        if data is None:
            tracked = self.window.card.manga.tracking and self.window.card.manga.tracking.get(self.tracker.id)

            if access_token_valid and tracked:
                thread = threading.Thread(target=run)
                thread.daemon = True
                thread.start()
            else:
                self.set_expanded(False)
                self.set_enable_expansion(False)
                self.action_row.set_title('')

                if access_token_valid:
                    self.set_arrow_visible(False)
                    self.btn.set_visible(True)
                    self.set_activatable(True)
                    self.set_subtitle('')
                else:
                    self.set_arrow_visible(True)
                    self.btn.set_visible(False)
                    self.set_activatable(False)
                    self.set_subtitle(_('Connection is expired'))
        else:
            complete(data)

        return granted and access_token_valid

    def on_btn_clicked(self, _btn):
        self.window.card.tracking_dialog.show_search(self.tracker)
        self.window.card.tracking_dialog.selected_tracker_row = self

    def set_arrow_visible(self, visible):
        action_row = self.get_first_child().get_first_child().get_first_child()
        arrow_img = action_row.get_first_child().get_last_child().get_last_child()
        arrow_img.set_visible(visible)

    def set_logo(self, use_fallback=False):
        if self.tracker.logo_url:
            if self.tracker.logo_path:
                self.logo = Gtk.Image()
                self.logo.set_pixel_size(LOGO_SIZE)
                self.logo.props.margin_top = 9
                self.logo.props.margin_bottom = 9
                self.logo.set_from_file(self.tracker.logo_path)
            elif use_fallback:
                # Fallback to an Adw.Avatar if logo fetching failed
                self.logo = Adw.Avatar.new(LOGO_SIZE, self.tracker.name, True)
            else:
                self.get_logo()
                return

        else:
            self.logo = Adw.Avatar.new(LOGO_SIZE, self.tracker.name, True)

        self.add_prefix(self.logo)

    def update_tracking_data(self, _row, _gparam):
        data = {
            'chapters_progress': self.chapters_progress_row.get_value(),
            'score': self.score_row.get_value() * self.score_row.format['raw_factor'],  # RAW
            'status': self.tracker.get_status_from_index(self.status_row.get_selected()),
            '_synced': False,
        }

        manga = self.window.card.manga
        manga.tracking[self.tracker.id].update(data)
        manga.update({'tracking': manga.tracking})


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/card_tracking_search.ui')
class TrackingSearchSubPage(Adw.NavigationPage):
    __gtype_name__ = 'TrackingSearchSubPage'

    searchentry = Gtk.Template.Child('searchentry')
    stack = Gtk.Template.Child('stack')
    listbox = Gtk.Template.Child('listbox')
    no_results_status_page = Gtk.Template.Child('no_results_status_page')

    def __init__(self, window):
        super().__init__()

        self.window = window
        self.queue = Queue()
        self.thread_covers = None
        self.thread_covers_stop_flag = False

        self.tracker = None

        self.searchentry.connect('activate', lambda _w: self.search())
        self.searchentry.connect('search-changed', self.on_search_changed)

    def clear(self):
        # Empty queue
        while not self.queue.empty():
            try:
                self.queue.get()
                self.queue.task_done()
            except Empty:
                continue

        # Empty group
        row = self.listbox.get_first_child()
        while row:
            next_row = row.get_next_sibling()

            self.listbox.remove(row)
            row = next_row

    def init(self, tracker, name=None):
        self.tracker = tracker

        self.searchentry.set_placeholder_text(_('Search {}').format(self.tracker.name))
        self.searchentry.set_text(name)

        self.search()

    def on_search_changed(self, _entry):
        if not self.searchentry.get_text().strip():
            self.stack.set_visible_child_name('intro')

    def render_covers(self):
        """
        Fetch and display covers of result rows

        This method is interrupted when the navigation page is left.
        """
        def run():
            while not self.queue.empty() and self.thread_covers_stop_flag is False:
                try:
                    row = self.queue.get()
                except Empty:
                    continue
                else:
                    try:
                        data, _etag, rtime = self.tracker.get_image(row.data['cover'])
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

    def search(self):
        def run(term):
            try:
                results = self.tracker.search(term)
            except Exception as e:
                log_error_traceback(e)
                results = None

            GLib.idle_add(complete, results)

        def complete(results):
            if results:
                for result in results:
                    row = TracherResultRow(self.window, result)
                    self.listbox.append(row)
                    self.queue.put(row)

                self.stack.set_visible_child_name('results')
                self.render_covers()

            elif results is None:
                self.no_results_status_page.set_title(_('Oops, search failed. Please try again.'))
                self.stack.set_visible_child_name('no_results')

            else:
                self.no_results_status_page.set_title(_('No Results Found'))
                self.no_results_status_page.set_description(_('Try a different search'))
                self.stack.set_visible_child_name('no_results')

        self.clear()
        self.stack.set_visible_child_name('loading')

        term = self.searchentry.get_text().strip()

        self.thread = threading.Thread(target=run, args=(term,))
        self.thread.daemon = True
        self.thread.start()
