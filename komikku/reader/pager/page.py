# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import threading

from gi.repository import Adw
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk

import cairo

from komikku.reader.pager.image import KImage
from komikku.models import Settings
from komikku.utils import log_error_traceback


class Page(Gtk.Overlay):
    __gtype_name__ = 'Page'
    __gsignals__ = {
        'rendered': (GObject.SignalFlags.RUN_FIRST, None, (bool, bool, )),
    }

    def __init__(self, pager, chapter, index):
        super().__init__(hexpand=True, vexpand=True)

        self.pager = pager
        self.reader = pager.reader
        self.window = self.reader.window

        self.chapter = self.init_chapter = chapter
        self.data = None
        self.index = self.init_index = index
        self.path = None
        self.image = None
        self.retry_button = None

        self._status = None    # rendering, allocable, rendered, offlimit, disposed
        self.error = None      # connection error, server error, corrupt file error
        self.loadable = False  # loadable from disk or downloadable from server (chapter pages are known)
        self.obscured = True

        if self.reader.reading_mode != 'webtoon':
            self.zoomable = True
            self.scrolledwindow = Gtk.ScrolledWindow()
            self.scrolledwindow.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            self.scrolledwindow.set_kinetic_scrolling(True)
            self.scrolledwindow.set_overlay_scrolling(True)

            self.set_child(self.scrolledwindow)
        else:
            self.zoomable = False

        # Activity indicator
        self.activity_indicator = Adw.Spinner(
            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, width_request=48, height_request=48, visible=False
        )
        self.add_overlay(self.activity_indicator)

        if self.reader.ocr_translator.enabled:
            # Creating a drawing area allowing to select an image portion containing text
            # in order to perform text recognition and translate it
            self.ocr_selection_da = Gtk.DrawingArea(hexpand=True, vexpand=True, can_target=False)
            self.ocr_selection_da.set_draw_func(self.draw_ocr_selection)
            self.reader.ocr_translator.bind_property(
                'active', self.ocr_selection_da, 'can-target',
                GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
            )
            self.add_overlay(self.ocr_selection_da)

            drag_gesture = Gtk.GestureDrag.new()
            drag_gesture.set_propagation_phase(Gtk.PropagationPhase.BUBBLE)
            drag_gesture.set_button(1)
            self.ocr_selection_da.add_controller(drag_gesture)
            drag_gesture.connect('drag-begin', self.on_ocr_selection_drag_begin)
            drag_gesture.connect('drag-update', self.on_ocr_selection_drag_update, False)
            drag_gesture.connect('drag-end', self.on_ocr_selection_drag_update, True)

            self.ocr_selection_surface = None
            self.ocr_selection_start_x = 0
            self.ocr_selection_start_y = 0

    @property
    def hscrollable(self):
        if self.zoomable:
            adj = self.scrolledwindow.get_hadjustment()
            return adj.props.upper > adj.props.page_size

        return False

    @property
    def scrollable(self):
        return self.hscrollable or self.vscrollable

    @GObject.Property(type=str)
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        self._status = value

    @property
    def vscrollable(self):
        if self.zoomable:
            adj = self.scrolledwindow.get_vadjustment()
            return adj.props.upper > adj.props.page_size

        return False

    def dispose(self):
        self.status = 'disposed'

        if self.image:
            self.image.dispose()
            self.image = None

        if self.get_parent().__class__.__name__ == 'KInfiniteCanvas':
            # Webtoon pager: unparent from KInfiniteCanvas
            self.unparent()
        else:
            # RTL/LTR/Vertical pager: remove from Adw.Carousel
            self.get_parent().remove(self)

    def draw_ocr_selection(self, da, ctx, width, height):
        if not self.ocr_selection_surface:
            return

        ctx.set_source_surface(self.ocr_selection_surface, 0, 0)
        ctx.paint()

    def on_button_retry_clicked(self, _button):
        self.chapter = self.init_chapter
        self.index = self.init_index

        self.retry_button.set_visible(False)

        self.render(retry=True)

    def on_clicked(self, _image, x, y):
        self.reader.pager.on_single_click(x, y)

    def on_ocr_selection_drag_begin(self, gesture, x, y):
        self.ocr_selection_start_x = x
        self.ocr_selection_start_y = y

    def on_ocr_selection_drag_update(self, gesture, offset_x, offset_y, end):
        self.ocr_selection_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.get_width(), self.get_height())

        ctx = cairo.Context(self.ocr_selection_surface)
        ctx.set_source_rgb(0.9647, 0.51, 0.462745)
        ctx.set_line_width(2)
        ctx.rectangle(self.ocr_selection_start_x, self.ocr_selection_start_y, offset_x, offset_y)
        ctx.stroke()

        self.ocr_selection_da.queue_draw()

        if end:
            # Clear context
            ctx.set_operator(cairo.OPERATOR_CLEAR)
            ctx.rectangle(0, 0, self.get_width(), self.get_height())
            ctx.paint()

            # Selection size
            w = offset_x
            h = offset_y
            if abs(w) < 1 or abs(h) < 1:
                return

            # Selection coordinates
            x = self.ocr_selection_start_x + min(0, offset_x)
            y = self.ocr_selection_start_y + min(0, offset_y)
            x = max(0, x - self.image.image_displayed_x)
            y = max(0, y - self.image.image_displayed_y)
            zoom = self.image.zoom

            # Text recognition
            self.reader.ocr_translator.recognize(
                self.image.path,
                x / zoom, y / zoom,
                (x + abs(w)) / zoom, (y + abs(h)) / zoom
            )

    def on_rendered(self, _image, update, retry):
        self.status = 'rendered'
        self.emit('rendered', update, retry)

    def on_zoom_begin(self, _image):
        self.reader.pager.interactive = False
        self.reader.toggle_controls(False)

    def on_zoom_end(self, _image):
        self.reader.pager.interactive = True

    def render(self, retry=False):
        def complete(error_code, error_message, stack_trace):
            if error_code in ('connection', 'server'):
                self.stop_activity_indicator()
                on_error(error_code, error_message, stack_trace)
                if retry:
                    return

            elif error_code == 'offlimit':
                self.stop_activity_indicator()
                self.status = 'offlimit'
                return

            if self.status == 'disposed':
                # Page has been removed from pager
                self.stop_activity_indicator()
                return

            self.set_image(retry)

        def load_chapter(prior_chapter=None):
            if self.chapter is None:
                return 'error', 'offlimit', None, None

            if self.chapter.pages and self.index >= 0 and self.index < len(self.chapter.pages):
                return 'success', None, None, None

            if self.index < 0:
                # Page belongs to another (previous) chapter
                self.chapter = self.reader.manga.get_next_chapter(self.chapter, -1)
                if self.chapter is None:
                    return 'error', 'offlimit', None, None

            if not self.chapter.pages:
                try:
                    if not self.chapter.update_full():
                        return 'error', 'server', None, None
                except Exception as e:
                    return 'error', 'connection', *log_error_traceback(e)

            if self.index > len(self.chapter.pages) - 1:
                # Page belongs to another (next) chapter
                prior_chapter = self.chapter
                self.chapter = self.reader.manga.get_next_chapter(self.chapter, 1)
                if self.chapter is None:
                    return 'error', 'offlimit', None, None

            if self.index < 0:
                self.index = len(self.chapter.pages) + self.index
            elif self.index > len(prior_chapter.pages if prior_chapter else self.chapter.pages) - 1:
                self.index = self.index - len(prior_chapter.pages)

            return load_chapter(prior_chapter)

        def on_error(kind, message=None, stack_trace=None):
            assert kind in ('connection', 'server', ), 'Invalid error kind'

            if message is not None:
                self.window.add_notification(message, timeout=2)

            elif stack_trace is not None and Settings.get_default().servers_bug_report:
                manga = self.reader.manga
                context = '\n'.join([
                    'Failed to fetch chapter data or page',
                    f'- Server ID: {manga.server.id}',
                    f'- Serie Name: {manga.name}',
                    f'- Serie URL: {manga.server.get_manga_url(manga.slug, manga.url)}',
                ])
                self.window.open_server_bug_report_dialog(manga.server, context, stack_trace)

            self.error = kind

            self.show_retry_button()

        def run():
            res, error_code, error_message, stack_trace = load_chapter()
            if res == 'error':
                GLib.idle_add(complete, error_code, error_message, stack_trace)
                return

            self.loadable = True

            if not self.reader.manga.is_local:
                page_path = self.chapter.get_page_path(self.index)
                if page_path is None:
                    try:
                        page_path, _rtime = self.chapter.get_page(self.index)
                        if page_path:
                            self.path = page_path
                        else:
                            error_code, error_message, stack_trace = 'server', None, None
                    except Exception as e:
                        error_code, error_message, stack_trace = 'connection', *log_error_traceback(e)
                else:
                    self.path = page_path
            else:
                try:
                    self.data = self.chapter.get_page_data(self.index)
                except Exception as e:
                    error_code, error_message, stack_trace = 'server', *log_error_traceback(e)

            GLib.idle_add(complete, error_code, error_message, stack_trace)

        if self.status is not None and self.error is None:
            return

        self.status = 'rendering'
        self.error = None

        self.start_activity_indicator()

        if not self.reader.manga.is_local:
            thread = threading.Thread(target=run)
            thread.daemon = True
            thread.start()
        else:
            run()

    def rescale(self):
        if self.image is None:
            return

        self.image.scaling = self.reader.scaling
        self.image.scaling_filter = self.reader.scaling_filter
        self.image.landscape_zoom = self.reader.landscape_zoom

    def set_allow_zooming(self, allow):
        if self.image is None:
            return

        if self.reader.reading_mode == 'webtoon':
            self.image.set_allow_zooming(False)
            return

        self.image.set_allow_zooming(allow)

    def set_image(self, retry):
        def on_loaded(image, error=None, mime_type=None):
            if error:
                self.error = error
                self.show_retry_button()

                if self.path:
                    GLib.unlink(self.path)

                message = [_('Failed to load image')]
                if self.error == 'corrupted-or-unsupported-format':
                    message.append(_('Corrupted file or unsupported image format ({0})').format(mime_type))
                self.window.add_notification('\n'.join(message), timeout=2)

            image.connect('clicked', self.on_clicked)
            image.connect('rendered', self.on_rendered, retry)
            image.connect('zoom-begin', self.on_zoom_begin)
            image.connect('zoom-end', self.on_zoom_end)

            if self.image:
                self.image.dispose()

            self.image = image
            self.status = 'allocable'
            if self.zoomable:
                self.scrolledwindow.set_child(self.image)
            else:
                self.set_child(self.image)

            self.stop_activity_indicator()

        if self.path is None and self.data is None:
            image = KImage()
            image.load_missing(callback=on_loaded)
        else:
            image = KImage(
                scaling=self.reader.scaling, scaling_filter=self.reader.scaling_filter,
                crop=self.reader.borders_crop, crop_threshold=self.reader.borders_crop_threshold,
                landscape_zoom=self.reader.landscape_zoom, zoomable=self.zoomable
            )
            image.load(path=self.path, data=self.data['buffer'] if self.data else None, callback=on_loaded)

    def show_retry_button(self):
        if self.retry_button is None:
            self.retry_button = Gtk.Button()
            self.retry_button.add_css_class('suggested-action')
            self.retry_button.set_valign(Gtk.Align.CENTER)
            self.retry_button.set_halign(Gtk.Align.CENTER)
            self.retry_button.connect('clicked', self.on_button_retry_clicked)

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            icon = Gtk.Image.new_from_icon_name('view-refresh-symbolic')
            icon.set_icon_size(Gtk.IconSize.LARGE)
            vbox.append(icon)
            vbox.append(Gtk.Label(label=_('Retry')))
            self.retry_button.set_child(vbox)

            self.add_overlay(self.retry_button)

        self.retry_button.set_visible(True)

    def start_activity_indicator(self):
        if self.reader.reading_mode != 'webtoon':
            self.activity_indicator.set_visible(True)

    def stop_activity_indicator(self, *args):
        if self.reader.reading_mode != 'webtoon':
            self.activity_indicator.set_visible(False)
