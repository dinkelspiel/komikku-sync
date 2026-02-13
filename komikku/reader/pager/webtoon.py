# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _

from gi.repository import Adw
from gi.repository import GLib
from gi.repository import Gtk

from komikku.models import Settings
from komikku.reader.pager import BasePager
from komikku.reader.pager.infinite_canvas import KInfiniteCanvas
from komikku.reader.pager.page import Page


class WebtoonPager(Adw.Bin, BasePager):
    """Vertical smooth/continuous scrolling (a.k.a. infinite canvas) pager"""

    __gtype_name__ = 'WebtoonPager'

    current_chapter_id = None
    scroll_page = None

    def __init__(self, reader):
        super().__init__()
        BasePager.__init__(self, reader)

        self.scrolledwindow = Gtk.ScrolledWindow()
        self.scrolledwindow.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scrolledwindow.get_vscrollbar().set_visible(False)
        self.scrolledwindow.set_kinetic_scrolling(True)
        self.set_child(self.scrolledwindow)

        self.vadjustment_value_changed_handler_id = self.scrolledwindow.get_vadjustment().connect('value-changed', self.on_scroll)

        self.clamp = Adw.ClampScrollable()
        self.set_clamp_size()
        self.scrolledwindow.set_child(self.clamp)

        self.canvas = KInfiniteCanvas(self)
        self.canvas.connect('keyboard-navigation', self.on_keyboard_navigation)
        self.canvas.connect('controls-zone-clicked', self.on_controls_zone_clicked)
        self.canvas.connect('offlimit', self.on_offlimit)
        self.canvas.connect('page-requested', self.on_page_requested)
        self.clamp.set_child(self.canvas)

    @property
    def pages(self):
        return self.canvas.pages

    def dispose(self):
        self.scrolledwindow.get_vadjustment().disconnect(self.vadjustment_value_changed_handler_id)

        self.canvas.dispose()
        self.canvas.unparent()
        self.canvas = None

    def goto_page(self, index):
        # TODO: use self.canvas.scroll_by_increment when possible
        self.canvas.disconnect_signals()
        self.canvas.clear()
        self.canvas.connect_signals()

        self.init(self.current_page.chapter, index)

    def init(self, chapter, page_index=None):
        if page_index is None:
            if chapter.read:
                page_index = 0
            elif chapter.last_page_read_index is not None:
                page_index = chapter.last_page_read_index
            else:
                page_index = 0

        page = Page(self, chapter, page_index)
        self.canvas.append(page)

        self.current_page = page

        GLib.idle_add(self.update, self.current_page)
        GLib.timeout_add(100, self.save_progress, page)

    def on_controls_zone_clicked(self, _canvas):
        self.reader.toggle_controls()

    def on_keyboard_navigation(self, _canvas):
        self.hide_cursor()

    def on_offlimit(self, _canvas, position):
        if position == 'bottom':
            message = _('It was the last chapter.')
        else:
            message = _('There is no previous chapter.')
        self.window.add_notification(message, timeout=1)

    def on_page_requested(self, _canvas, position):
        """
        Depending on the position parameter, adds a page at start (top) or at end (bottom)
        """

        if position == 'start':
            top_page = self.canvas.get_first_child()
            new_page = Page(self, top_page.chapter, top_page.index - 1)
            self.canvas.prepend(new_page)
        else:
            bottom_page = self.canvas.get_last_child()
            new_page = Page(self, bottom_page.chapter, bottom_page.index + 1)
            self.canvas.append(new_page)

    def on_scroll(self, _vadj):
        # Hide controls
        self.reader.toggle_controls(False)

        if self.canvas.scroll_direction == Gtk.DirectionType.DOWN:
            current_page = self.canvas.current_page_bottom
        else:
            current_page = self.canvas.current_page_top

        if current_page and current_page != self.current_page:
            self.current_page = current_page

            GLib.idle_add(self.update, current_page)

            pages = self.pages
            GLib.timeout_add(
                100, self.save_progress,
                pages[pages.index(self.canvas.current_page_top):pages.index(self.current_page) + 1]
            )

    def set_clamp_size(self, zoom=1):
        """
        Adjust clamp width (increase/decrease) by a zoom factor

        Use to allow pseudo-zoom limited to the width of the window

        :param zoom: A zoom factor to be applied to the width of the clamp
        :type zoom: float

        :return: Zoom factor applied taking into account size limitations
        :rtype: float
        """
        size = min(max(360, Settings.get_default().clamp_size * zoom), self.reader.window.monitor.props.geometry.width)

        self.clamp.set_maximum_size(size)
        self.clamp.set_tightening_threshold(size)

        return size / Settings.get_default().clamp_size

    def set_orientation(self, _orientation):
        return

    def update(self, page, _direction=None):
        if self.window.page != 'reader' or page.status == 'disposed' or self.current_page != page:
            return GLib.SOURCE_REMOVE

        if not page.loadable and page.error is None:
            # Loop until page is loadable or page is on error
            return GLib.SOURCE_CONTINUE

        # Update title, initialize controls and notify user if chapter changed
        if self.current_chapter_id != page.chapter.id:
            self.current_chapter_id = page.chapter.id

            self.reader.update_title(page.chapter)
            self.window.add_notification(page.chapter.title, timeout=2)
            self.reader.controls.init(page.chapter)

        if not page.loadable:
            self.window.add_notification(_('This chapter is inaccessible.'), timeout=2)

        # Update page number and controls page slider
        self.reader.update_page_numbering(page.index + 1, len(page.chapter.pages) if page.loadable else None)
        self.reader.controls.set_scale_value(page.index + 1)

        return GLib.SOURCE_REMOVE
