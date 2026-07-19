# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from io import BytesIO
import logging
import math

import gi
from PIL import Image
from PIL import ImageChops

gi.require_version('Gdk', '4.0')
gi.require_version('Gtk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Graphene', '1.0')

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Graphene
from gi.repository import Gsk
from gi.repository import Gtk
from gi.repository.GdkPixbuf import Colorspace
from gi.repository.GdkPixbuf import Pixbuf
from gi.repository.GdkPixbuf import PixbufAnimation

from komikku.consts import MISSING_IMG_RESOURCE_PATH
from komikku.models import Settings
from komikku.utils import get_image_info

logger = logging.getLogger('komikku')

TEXTURES_CHUNK_MAX_HEIGHT = 30000
ZOOM_FACTOR_DOUBLE_TAP = 2.5
ZOOM_FACTOR_MAX = 20
ZOOM_FACTOR_SCROLL_WHEEL = 1.3


def chunk_pixbuf(pixbuf, chunk_height):
    """Chunk a long vertical GdkPixbuf.Pixbuf into multiple GdkPixbuf.Pixbuf"""

    width = pixbuf.get_width()
    full_height = pixbuf.get_height()

    chunks = []
    for index in range(math.ceil(full_height / chunk_height)):
        y = index * chunk_height
        height = chunk_height if y + chunk_height <= full_height else full_height - y

        chunk = Pixbuf.new(Colorspace.RGB, pixbuf.get_has_alpha(), 8, width, height)
        pixbuf.copy_area(0, y, width, height, chunk, 0, 0)
        chunks.append(chunk)

    return chunks


class KImage(Gtk.Widget, Gtk.Scrollable):
    __gtype_name__ = 'KImage'
    __gsignals__ = {
        'clicked': (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        'rendered': (GObject.SignalFlags.RUN_FIRST, None, (bool, )),
        'zoom-begin': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'zoom-end': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, scaling='screen', scaling_filter='linear', crop=False, crop_threshold=None, landscape_zoom=False, zoomable=False):
        super().__init__()

        self.__crop = crop
        self.__crop_threshold = crop_threshold
        self.__hadj = None
        self.__landscape_zoom = zoomable and landscape_zoom
        self.__rendered = False
        self.__scaling = scaling
        self.__scaling_filter = scaling_filter
        self.__vadj = None
        self.__zoom = 1
        self.__zoomable = zoomable

        self.data = None
        self.path = None

        self.textures = None
        self.textures_crop = None
        self.crop_bbox = None

        self.animation = None  # PixbufAnimation
        self.animation_iter = None
        self.animation_tick_callback_id = None

        self.hadjustment_value_changed_handler_id = None
        self.vadjustment_value_changed_handler_id = None

        self.gesture_click_timeout_id = None
        self.pointer_position = None  # current pointer position
        self.zoom_center = None  # zoom position in image
        self.zoom_gesture_begin = None
        self.zoom_scaling = None  # zoom factor at scaling

        self.set_overflow(Gtk.Overflow.HIDDEN)

        if self.__zoomable:
            # Controller to track pointer motion: used to know current cursor position
            self.controller_motion = Gtk.EventControllerMotion.new()
            self.add_controller(self.controller_motion)
            self.controller_motion.connect('motion', self.on_pointer_motion)

            # Controller to zoom with Ctrl + mouse wheel or 2-fingers touchpad gesture
            self.controller_scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
            self.controller_scroll.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            self.add_controller(self.controller_scroll)
            self.controller_scroll.connect('scroll', self.on_scroll)

            # Gesture click controller: double-tap zoom
            self.gesture_click = Gtk.GestureClick.new()
            self.gesture_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            self.gesture_click.set_button(1)
            self.gesture_click.connect('released', self.on_gesture_click_released)
            self.add_controller(self.gesture_click)

            # Gesture zoom controller (2-fingers touchpad/touchscreen gesture)
            self.gesture_zoom = Gtk.GestureZoom.new()
            self.gesture_zoom.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            self.gesture_zoom.connect('begin', self.on_gesture_zoom_begin)
            self.gesture_zoom.connect('end', self.on_gesture_zoom_end)
            self.gesture_zoom.connect('scale-changed', self.on_gesture_zoom_scale_changed)
            self.add_controller(self.gesture_zoom)

    @property
    def borders(self):
        """ Width of vertical (top, bottom) and horizontal (left, right) bars """
        if self.widget_width > self.image_displayed_width:
            hborder = (self.widget_width - self.image_displayed_width) / 2
        else:
            hborder = 0

        if self.widget_height > self.image_displayed_height:
            vborder = (self.widget_height - self.image_displayed_height) / 2
        else:
            vborder = 0

        return (hborder, vborder)

    @GObject.Property(type=bool, default=False)
    def crop(self):
        return self.__crop and not self.animation

    @crop.setter
    def crop(self, value):
        if self.__crop == value or self.animation:
            return

        self.__crop = value
        self.queue_resize()

    @GObject.Property(type=int, default=0)
    def crop_threshold(self):
        return self.__crop_threshold or Settings.get_default().borders_crop_threshold

    @crop_threshold.setter
    def crop_threshold(self, value):
        if self.__crop_threshold == value:
            return

        self.__crop_threshold = value
        self.queue_resize()

    @GObject.Property(type=Gtk.Adjustment)
    def hadjustment(self):
        return self.__hadj or Gtk.Adjustment()

    @hadjustment.setter
    def hadjustment(self, adj):
        if not adj:
            return

        self.__hadj = adj
        self.hadjustment_value_changed_handler_id = adj.connect('value-changed', lambda _adj: self.queue_draw())
        self.configure_adjustments()

    @GObject.Property(type=Gtk.ScrollablePolicy, default=Gtk.ScrollablePolicy.MINIMUM)
    def hscroll_policy(self):
        return Gtk.ScrollablePolicy.MINIMUM

    @property
    def image_height(self):
        """ Image original height """
        if self.animation:
            return self.animation.get_height()

        if self.crop and self.crop_bbox:
            return self.crop_bbox[3] - self.crop_bbox[1]

        return sum(texture.get_height() for texture in self.textures) if self.textures else 0

    @property
    def image_width(self):
        """ Image original width """
        if self.animation:
            return self.animation.get_width()

        if self.crop and self.crop_bbox:
            return self.crop_bbox[2] - self.crop_bbox[0]

        return self.textures[0].get_width() if self.textures else 0

    @property
    def image_displayed_height(self):
        """ Image height with current zoom factor """
        return int(self.image_height * self.zoom)

    @property
    def image_displayed_width(self):
        """ Image width with current zoom factor """
        return int(self.image_width * self.zoom)

    @GObject.Property(type=bool, default=False)
    def landscape_zoom(self):
        return self.__landscape_zoom

    @landscape_zoom.setter
    def landscape_zoom(self, value):
        if self.__landscape_zoom == value:
            return

        self.__landscape_zoom = value
        self.queue_resize()

    @property
    def max_hadjustment_value(self):
        return max(self.image_displayed_width - self.widget_width, 0)

    @property
    def max_vadjustment_value(self):
        return max(self.image_displayed_height - self.widget_height, 0)

    @property
    def obscured(self):
        parent = self.get_parent()
        if isinstance(parent, Gtk.ScrolledWindow):
            return parent.get_parent().obscured

        return parent.obscured

    @property
    def ratio(self):
        return self.image_width / self.image_height

    @GObject.Property(type=str, default='screen')
    def scaling(self):
        """ Type of scaling:
        - adapt to screen (best-fit)
        - adapt to width
        - adapt to height
        - original size
        """
        return self.__scaling

    @scaling.setter
    def scaling(self, value):
        if self.__scaling == value:
            return

        self.__scaling = value
        self.queue_resize()

    @GObject.Property(type=str, default='linear')
    def scaling_filter(self):
        """ Scaling filters:
        - linear
        - trilinear
        """
        return self.__scaling_filter

    @scaling_filter.setter
    def scaling_filter(self, value):
        if self.__scaling_filter == value:
            return

        self.__scaling_filter = value
        self.queue_resize()

    @property
    def scaling_size(self):
        """ Image size at defined scaling """
        scaling = self.scaling
        if scaling != 'original':
            if self.landscape_zoom and scaling == 'screen' and self.image_width > self.image_height:
                # When page is landscape and scaling is 'screen', scale page to fit height
                scaling = 'height'

            max_width = self.widget_width
            max_height = self.widget_height

            adapt_to_width_height = max_width * self.image_height / self.image_width
            adapt_to_height_width = max_height * self.image_width / self.image_height

            if scaling == 'width' or (scaling == 'screen' and adapt_to_width_height <= max_height):
                # Adapt image to width
                width = max_width
                height = adapt_to_width_height
            elif scaling == 'height' or (scaling == 'screen' and adapt_to_height_width <= max_width):
                # Adapt image to height
                width = adapt_to_height_width
                height = max_height
        else:
            width = self.image_width
            height = self.image_height

        return (width, height)

    @property
    def scrollable(self):
        return isinstance(self.get_parent(), Gtk.ScrolledWindow)

    @GObject.Property(type=Gtk.Adjustment)
    def vadjustment(self):
        return self.__vadj or Gtk.Adjustment()

    @vadjustment.setter
    def vadjustment(self, adj):
        if not adj:
            return

        self.__vadj = adj
        self.vadjustment_value_changed_handler_id = adj.connect('value-changed', lambda _adj: self.queue_draw())
        self.configure_adjustments()

    @GObject.Property(type=Gtk.ScrollablePolicy, default=Gtk.ScrollablePolicy.MINIMUM)
    def vscroll_policy(self):
        return Gtk.ScrollablePolicy.MINIMUM

    @property
    def widget_height(self):
        return self.get_height()

    @property
    def widget_width(self):
        return self.get_width()

    @GObject.Property(type=float)
    def zoom(self):
        """ Displayed zoom level """
        return self.__zoom

    @zoom.setter
    def zoom(self, value):
        if self.__zoom == value:
            return
        self.__zoom = value
        self.queue_resize()

    @property
    def zoomable(self):
        return self.__zoomable

    def __animation_tick_callback(self, image, clock):
        if self.animation is not None and self.animation_iter is None:
            return GLib.SOURCE_REMOVE

        # Do not animate if not visible (obscured)
        if self.obscured or not self.get_mapped():
            return GLib.SOURCE_CONTINUE

        # Check if it's time to show the next frame
        if self.animation_iter.advance(None):
            self.queue_draw()

        return GLib.SOURCE_CONTINUE

    def __compute_borders_crop_bbox(self):
        if self.path is None and self.data is None:
            return None

        def lookup(x):
            return 255 if x > self.crop_threshold else 0

        try:
            with Image.open(self.path or BytesIO(self.data)) as im:
                with im.convert('L') as im_bw:
                    im_lookup = im_bw.point(lookup, mode='1')
        except Exception as exc:
            logger.error('Failed to compute image white borders bbox', exc_info=exc)
            return None

        with Image.new(im_lookup.mode, im_lookup.size, 255) as im_bg:
            return ImageChops.difference(im_lookup, im_bg).getbbox()

    def cancel_deceleration(self):
        if self.scrollable:
            self.get_parent().set_kinetic_scrolling(False)
            self.get_parent().set_kinetic_scrolling(True)

    def configure_adjustments(self):
        self.hadjustment.configure(
            # value
            max(min(self.hadjustment.props.value, self.max_hadjustment_value), 0),
            # lower value
            0,
            # upper value
            self.image_displayed_width,
            # step increment
            self.widget_width * 0.1,
            # page increment
            self.widget_width * 0.9,
            # page size
            min(self.widget_width, self.image_displayed_width)
        )

        self.vadjustment.configure(
            max(min(self.vadjustment.props.value, self.max_vadjustment_value), 0),
            0,
            self.image_displayed_height,
            self.widget_height * 0.1,
            self.widget_height * 0.9,
            min(self.widget_height, self.image_displayed_height)
        )

    def crop_borders(self):
        """ Crop white borders """
        bbox = self.crop_bbox
        textures_width = self.textures[0].get_width()
        textures_height = sum(texture.get_height() for texture in self.textures)

        # Crop is possible if computed bbox is included in textures
        if bbox and (bbox[2] - bbox[0] < textures_width or bbox[3] - bbox[1] < textures_height):
            try:
                with Image.open(self.path or BytesIO(self.data)) as im:
                    with im.convert('RGB') as im_rgb:
                        with im_rgb.crop(bbox) as im_crop:
                            with BytesIO() as io_buffer:
                                # Use the very fast TIFF format (Pillow uses libtiff)
                                im_crop.save(io_buffer, 'tiff')

                                if bbox[3] - bbox[1] > TEXTURES_CHUNK_MAX_HEIGHT:
                                    stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(io_buffer.getvalue()))

                                    textures = []
                                    for pix in chunk_pixbuf(Pixbuf.new_from_stream(stream), TEXTURES_CHUNK_MAX_HEIGHT):
                                        textures.append(Gdk.Texture.new_for_pixbuf(pix))

                                    stream.close()

                                    return textures
                                else:
                                    return [Gdk.Texture.new_from_bytes(GLib.Bytes.new(io_buffer.getvalue()))]
            except Exception as exc:
                logger.error('Failed to crop image white borders', exc_info=exc)

        return self.textures

    def dispose(self):
        if self.hadjustment_value_changed_handler_id:
            self.hadjustment.disconnect(self.hadjustment_value_changed_handler_id)
        if self.vadjustment_value_changed_handler_id:
            self.vadjustment.disconnect(self.vadjustment_value_changed_handler_id)

        if self.zoomable:
            self.controller_motion.disconnect_by_func(self.on_pointer_motion)
            self.controller_scroll.disconnect_by_func(self.on_scroll)
            self.gesture_click.disconnect_by_func(self.on_gesture_click_released)
            self.gesture_zoom.disconnect_by_func(self.on_gesture_zoom_begin)
            self.gesture_zoom.disconnect_by_func(self.on_gesture_zoom_end)
            self.gesture_zoom.disconnect_by_func(self.on_gesture_zoom_scale_changed)

        if self.animation_tick_callback_id:
            self.remove_tick_callback(self.animation_tick_callback_id)

        self.data = None
        self.textures = None
        self.textures_crop = None
        self.animation_iter = None
        self.animation = None

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 0, int(for_size * self.ratio) if for_size != -1 else -1, -1, -1

        return 0, int(for_size / self.ratio) if for_size != -1 else -1, -1, -1

    def do_size_allocate(self, w, h, b):
        if self.crop and self.crop_bbox is None:
            self.crop_bbox = self.__compute_borders_crop_bbox()

        if self.zoom_scaling is None or self.zoom == self.zoom_scaling:
            self.zoom_scaling = self.scaling_size[1] / self.image_height
            self.set_zoom()
        else:
            self.configure_adjustments()

    def do_snapshot(self, snapshot):
        if self.animation_iter:
            # Get next frame (animated GIF)
            self.textures = [Gdk.Texture.new_for_pixbuf(self.animation_iter.get_pixbuf())]

        elif self.crop and self.textures_crop is None and self.textures:
            # Crop white borders
            self.textures_crop = self.crop_borders()

        self.configure_adjustments()

        snapshot.save()

        width = self.image_displayed_width
        height = self.image_displayed_height

        if self.scrollable:
            x = -(self.hadjustment.props.value - (self.hadjustment.props.upper - width) / 2)
            snapshot.translate(Graphene.Point().init(int(x), 0))
            y = -(self.vadjustment.props.value - (self.vadjustment.props.upper - height) / 2)
            snapshot.translate(Graphene.Point().init(0, int(y)))

        # Center in widget
        snapshot.translate(
            Graphene.Point().init(
                max((self.widget_width - width) // 2, 0),
                max((self.widget_height - height) // 2, 0),
            )
        )

        # Append textures
        scale_factor = self.get_native().get_surface().get_scale()
        if scale_factor != 1:
            snapshot.scale(1 / scale_factor, 1 / scale_factor)

        filter = Gsk.ScalingFilter.LINEAR if self.scaling_filter == 'linear' else Gsk.ScalingFilter.TRILINEAR
        rect = Graphene.Rect().alloc()
        textures = self.textures_crop if self.crop else self.textures
        y = 0
        for texture in textures:
            h = int(texture.get_height() * self.zoom) * scale_factor
            rect.init(0, y, int(texture.get_width() * self.zoom) * scale_factor, h)
            snapshot.append_scaled_texture(texture, filter, rect)
            y += h

        snapshot.restore()

        self.emit('rendered', self.__rendered)
        if not self.__rendered:
            self.__rendered = True

    def load(self, path=None, data=None, callback=None, static_animation=False):
        info, mime_type = get_image_info(path or data)
        if info is None:
            self.load_missing(callback=callback, error='corrupted-or-unsupported-format', mime_type=mime_type)
            return

        try:
            if path:
                with open(path, 'rb') as fp:
                    stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(fp.read()))
            elif data:
                stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))

            if not info['is_animated']:
                Pixbuf.new_from_stream_async(stream, None, self.load_ready, callback, info, mime_type)
            else:
                PixbufAnimation.new_from_stream_async(stream, None, self.load_ready, callback, info, mime_type)

        except Exception as exc:
            logger.warning('Failed to create textures: corrupted file or unsupported image format', exc_info=exc)
            self.load_missing(callback=callback, error='corrupted-or-unsupported-format', mime_type=mime_type)
            return

        self.path = path
        self.data = data

    def load_missing(self, callback=None, error=None, mime_type=None):
        self.path = MISSING_IMG_RESOURCE_PATH

        # Reset instance variables and controllers
        self.dispose()
        self.__scaling = 'screen'
        self.__scaling_filter = 'linear'
        self.__crop = False
        self.__landscape_zoom = False
        self.__zoomable = False

        try:
            self.textures = [Gdk.Texture.new_from_resource(self.path)]

        except Exception as exc:
            logger.warning('Failed to create textures: corrupted file or unsupported image format', exc_info=exc)
            return

        if callback:
            callback(self, error=error, mime_type=mime_type)

    def load_ready(self, stream, result, callback, info, mime_type):
        stream.close()

        try:
            if not info['is_animated']:
                pixbuf = Pixbuf.new_from_stream_finish(result)

                self.textures = []
                if info['height'] < TEXTURES_CHUNK_MAX_HEIGHT:
                    self.textures.append(Gdk.Texture.new_for_pixbuf(pixbuf))
                else:
                    # Chunk a long vertical pixbuf into several textures
                    for cpixbuf in chunk_pixbuf(pixbuf, TEXTURES_CHUNK_MAX_HEIGHT):
                        self.textures.append(Gdk.Texture.new_for_pixbuf(cpixbuf))

            else:
                self.animation = PixbufAnimation.new_from_stream_finish(result)
                self.animation_iter = self.animation.get_iter(None)
                self.animation_tick_callback_id = self.add_tick_callback(self.__animation_tick_callback)

        except Exception as exc:
            logger.warning('Failed to create textures: corrupted file or unsupported image format', exc_info=exc)
            self.load_missing(callback=callback, error='corrupted-or-unsupported-format', mime_type=mime_type)
            return

        callback(self)

    def on_gesture_click_released(self, _gesture, n_press, x, y):
        def emit_clicked(x, y):
            GLib.source_remove(self.gesture_click_timeout_id)
            self.gesture_click_timeout_id = None
            self.emit('clicked', x, y)

        if n_press == 1 and self.gesture_click_timeout_id is None and self.zoom == self.zoom_scaling:
            # Schedule single click event to be able to detect double click
            dbl_click_time = Gtk.Settings.get_default().get_property('gtk-double-click-time')
            self.gesture_click_timeout_id = GLib.timeout_add(dbl_click_time, emit_clicked, x, y)

        elif n_press == 2:
            # Remove scheduled single click event
            if self.gesture_click_timeout_id:
                GLib.source_remove(self.gesture_click_timeout_id)
                self.gesture_click_timeout_id = None

            if self.zoom == self.zoom_scaling:
                self.set_zoom(self.zoom * ZOOM_FACTOR_DOUBLE_TAP, (x, y))
            else:
                self.set_zoom(self.zoom_scaling)

    def on_gesture_zoom_begin(self, _gesture, _sequence):
        self.cancel_deceleration()

        _active, x, y = self.gesture_zoom.get_bounding_box_center()
        self.zoom_center = (x, y)
        self.zoom_gesture_begin = self.zoom

        self.gesture_zoom.set_state(Gtk.EventSequenceState.CLAIMED)

    def on_gesture_zoom_end(self, _gesture, _sequence):
        self.gesture_zoom.set_state(Gtk.EventSequenceState.CLAIMED)

    def on_gesture_zoom_scale_changed(self, _gesture, scale):
        self.set_zoom(self.zoom_gesture_begin * scale, self.zoom_center)

        if self.gesture_zoom.get_device().get_source() == Gdk.InputSource.TOUCHSCREEN and self.zoom_center:
            # Move image to follow zoom position on touchscreen
            _active, x, y = self.gesture_zoom.get_bounding_box_center()
            self.hadjustment.set_value(self.hadjustment.get_value() + self.zoom_center[0] - x)
            self.vadjustment.set_value(self.vadjustment.get_value() + self.zoom_center[1] - y)
            self.zoom_center = (x, y)

        self.gesture_zoom.set_state(Gtk.EventSequenceState.CLAIMED)

    def on_pointer_motion(self, _controller, x, y):
        self.pointer_position = (x, y)

    def on_scroll(self, _controller, _dx, dy):
        """ <Ctrl>+Scroll zooming """
        modifiers = Gtk.accelerator_get_default_mod_mask()
        state = self.controller_scroll.get_current_event_state()
        if state & modifiers == Gdk.ModifierType.CONTROL_MASK:
            factor = math.exp(-dy * math.log(ZOOM_FACTOR_SCROLL_WHEEL))
            self.set_zoom(self.zoom * factor, self.pointer_position)
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def set_allow_zooming(self, allow):
        if not self.zoomable:
            return

        self.controller_scroll.set_propagation_phase(Gtk.PropagationPhase.CAPTURE if allow else Gtk.PropagationPhase.NONE)
        self.gesture_zoom.set_propagation_phase(Gtk.PropagationPhase.CAPTURE if allow else Gtk.PropagationPhase.NONE)

    def set_zoom(self, zoom=None, center=None):
        """ Set zoom level for given position """

        if zoom is None:
            zoom = self.zoom_scaling
        else:
            zoom = min(max(zoom, self.zoom_scaling), ZOOM_FACTOR_MAX)

            if zoom != self.zoom_scaling and self.zoom == self.zoom_scaling:
                self.emit('zoom-begin')
            elif zoom == self.zoom_scaling and self.zoom != self.zoom_scaling:
                self.emit('zoom-end')

        if center:
            borders = self.borders
            zoom_ratio = self.zoom / zoom

        self.zoom = zoom

        self.configure_adjustments()

        if center:
            hadjustment_value = self.hadjustment.get_value()
            vadjustment_value = self.vadjustment.get_value()

            x = center[0]
            y = center[1]

            value = max((x + hadjustment_value - borders[0]) / zoom_ratio - x, 0)
            self.hadjustment.set_value(value)

            value = max((y + vadjustment_value - borders[1]) / zoom_ratio - y, 0)
            self.vadjustment.set_value(value)

    def set_zoom_by_key(self, keyval, reading_mode):
        # Compute center depending on reading mode
        if reading_mode == 'left-to-right':
            # Top left
            center = (0, 0)

        elif reading_mode == 'vertical':
            # Center top
            center = (self.widget_width // 2, 0)

        else:
            # Top right
            center = (self.widget_width, 0)

        if keyval in (Gdk.KEY_plus, Gdk.KEY_KP_Add):
            # Zoom in
            self.set_zoom(self.zoom * ZOOM_FACTOR_SCROLL_WHEEL, center)

        elif keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            # Zoom out
            self.set_zoom(self.zoom / ZOOM_FACTOR_SCROLL_WHEEL, center)

        elif keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
            # Reset
            self.set_zoom()
