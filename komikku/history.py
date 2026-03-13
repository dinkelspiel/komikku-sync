# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import datetime
from gettext import gettext as _
import pytz

from gi.repository import Adw
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk

from komikku.consts import MISSING_IMG_RESOURCE_PATH
from komikku.models import Chapter
from komikku.models import create_db_connection
from komikku.utils import CoverPicture
from komikku.utils import html_escape

DAYS_LIMIT = 30
THUMB_WIDTH = 45
THUMB_HEIGHT = 62
TIMEZONE = datetime.datetime.now(tz=datetime.UTC).astimezone().tzinfo


class HistoryDateBox(Gtk.Box):
    __gtype_name__ = 'HistoryDateBox'

    def __init__(self, window, date, chapters, filter_func):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Title: Date
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        if date == today:
            label = _('Today')
        elif date == yesterday:
            label = _('Yesterday')
        else:
            label = date.strftime(_('%A, %B %e'))
        date_label = Gtk.Label(label=label, xalign=0)
        date_label.add_css_class('heading')
        self.append(date_label)

        # List of read manga
        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class('boxed-list')
        self.listbox.set_filter_func(filter_func)
        self.append(self.listbox)

        for chapter in chapters:
            self.listbox.append(HistoryDateChapterRow(window, chapter))

    def clear(self):
        for chapter_row in self.listbox:
            chapter_row.clear()


class HistoryDateChapterRow(Adw.ActionRow):
    __gtype_name__ = 'HistoryDateChapterRow'

    def __init__(self, window, chapter):
        super().__init__(activatable=True, selectable=False)

        self.window = window
        self.chapter = chapter

        self.set_title(html_escape(chapter.manga.name))
        self.set_title_lines(1)
        self.set_subtitle(html_escape(chapter.title))
        self.set_subtitle_lines(1)

        # Cover
        if chapter.manga.cover_fs_path is None:
            picture = CoverPicture.new_from_resource(MISSING_IMG_RESOURCE_PATH, THUMB_WIDTH, THUMB_HEIGHT)
        else:
            picture = CoverPicture.new_from_file(chapter.manga.cover_fs_path, THUMB_WIDTH, THUMB_HEIGHT, True)
            if picture is None:
                picture = CoverPicture.new_from_resource(MISSING_IMG_RESOURCE_PATH, THUMB_WIDTH, THUMB_HEIGHT)

        self.cover_frame = Gtk.Frame()
        self.cover_frame.add_css_class('row-rounded-cover-frame')
        self.cover_frame.set_child(picture)
        self.add_prefix(self.cover_frame)

        # Time
        last_read = chapter.last_read.replace(tzinfo=pytz.UTC).astimezone(TIMEZONE)
        label = Gtk.Label(label=last_read.strftime('%H:%M'))
        label.set_css_classes(['subtitle', 'numeric'])
        self.add_suffix(label)

        # Play/Resume button
        self.button = Gtk.Button.new_from_icon_name('media-playback-start-symbolic')
        self.button.set_tooltip_text(_('Resume'))
        self.play_button_clicked_handler_id = self.button.connect('clicked', self.on_play_button_clicked, self)
        self.button.set_valign(Gtk.Align.CENTER)
        self.add_suffix(self.button)

        self.activated_handler_id = self.connect('activated', self.on_activated)

    def clear(self):
        self.button.disconnect(self.play_button_clicked_handler_id)
        self.disconnect(self.activated_handler_id)

    def on_activated(self, row):
        self.window.card.init(row.chapter.manga)

    def on_play_button_clicked(self, _button, row):
        self.window.reader.init(row.chapter.manga, row.chapter)


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/history.ui')
class HistoryPage(Adw.NavigationPage):
    __gtype_name__ = 'HistoryPage'

    search_button = Gtk.Template.Child('search_button')

    stack = Gtk.Template.Child('stack')
    dates_box = Gtk.Template.Child('dates_box')
    searchbar = Gtk.Template.Child('searchbar')
    searchbar_separator = Gtk.Template.Child('searchbar_separator')
    searchentry = Gtk.Template.Child('searchentry')

    def __init__(self, window):
        Adw.NavigationPage.__init__(self)

        self.window = window

        self.connect('hidden', self.on_hidden)

        self.searchbar.bind_property(
            'search-mode-enabled', self.search_button, 'active',
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
        )
        self.searchbar.bind_property(
            'search-mode-enabled', self.searchbar_separator, 'visible',
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
        )
        self.searchbar.connect_entry(self.searchentry)
        self.searchbar.set_key_capture_widget(self.window)

        self.searchentry.connect('activate', self.on_searchentry_activated)
        self.searchentry.connect('search-changed', self.search)

        self.window.navigationview.add(self)

    def clear(self):
        date_box = self.dates_box.get_first_child()
        while date_box:
            next_box = date_box.get_next_sibling()
            date_box.clear()
            self.dates_box.remove(date_box)
            date_box = next_box

    def filter(self, row):
        """
        This function gets one row and has to return:
        - True if the row should be displayed
        - False if the row should not be displayed
        """
        term = self.searchentry.get_text().strip().lower()

        ret = (
            term in row.chapter.title.lower() or
            term in row.chapter.manga.name.lower()
        )

        if ret:
            # As soon as a row is visible, made grand parent date_box visible
            GLib.idle_add(row.get_parent().get_parent().set_visible, True)

        return ret

    def on_hidden(self, _page):
        # Leave search mode
        if self.searchbar.get_search_mode():
            self.searchbar.set_search_mode(False)

        # Don't clear on navigation push
        if self.window.previous_page != self.props.tag:
            self.clear()

    def on_searchentry_activated(self, _entry):
        if not self.searchbar.get_search_mode():
            return

        row = self.dates_box.get_first_child().get_last_child().get_row_at_y(0)
        if row:
            self.window.reader.init(row.chapter.manga, row.chapter)

    def populate(self):
        db_conn = create_db_connection()
        start = (datetime.date.today() - datetime.timedelta(days=DAYS_LIMIT)).strftime('%Y-%m-%d')
        query = """
            SELECT DISTINCT manga_id, date(last_read, 'localtime') AS last_read_date, id, max(last_read)
            FROM chapters WHERE date(last_read, 'localtime') >= ?
            GROUP BY manga_id, last_read_date
            ORDER BY last_read DESC
        """
        records = db_conn.execute(query, (start,)).fetchall()

        if records:
            dates = {}
            for record in records:
                chapter = Chapter.get(record['id'], db_conn=db_conn)
                date = record['last_read_date']  # ISO 8601 date string
                if date not in dates:
                    dates[date] = []
                dates[date].append(chapter)

            for iso_date, chapters in dates.items():
                date = datetime.datetime.strptime(iso_date, '%Y-%m-%d').date()
                date_box = HistoryDateBox(self.window, date, chapters, self.filter)
                self.dates_box.append(date_box)

            self.stack.set_visible_child_name('list')
        else:
            self.stack.set_visible_child_name('empty')

    def search(self, _entry):
        for date_box in self.dates_box:
            listbox = date_box.get_last_child()
            listbox.invalidate_filter()
            # Hide date_box, will be shown if a least one row of listbox is not filtered
            date_box.set_visible(False)

    def show(self):
        self.populate()

        self.window.navigationview.push(self)
