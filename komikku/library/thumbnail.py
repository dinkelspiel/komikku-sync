# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gi.repository import Adw
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GObject
from gi.repository import Graphene
from gi.repository import Gsk
from gi.repository import Gtk
from gi.repository import Pango

from komikku.consts import COVER_HEIGHT
from komikku.consts import COVER_WIDTH
from komikku.consts import MISSING_IMG_RESOURCE_PATH
from komikku.models import Settings
from komikku.utils import CoverLoader


class Thumbnail(Gtk.FlowBoxChild):
    __gtype_name__ = 'Thumbnail'

    default_width = COVER_WIDTH
    default_height = COVER_HEIGHT
    padding = 6  # padding is overriding via CSS
    margin = 3   # flowbox column spacing divided by 2
    server_logo_size = 16

    def __init__(self, parent, manga, width, height):
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)

        self.parent = parent
        self.manga = manga
        self._filtered = False
        self._selected = False

        self.picture = Gtk.Picture()
        self.picture.add_css_class('cover-dropshadow')
        self.picture.set_can_shrink(False)
        self.picture.set_paintable(ThumbnailCover(manga))

        # Logo widget (Gtk.Image or Adw.Avatar as fallback)
        if Settings.get_default().library_servers_logo:
            if self.manga.server.logo_path:
                logo = Gtk.Image.new_from_file(self.manga.server.logo_path)
                logo.set_pixel_size(self.server_logo_size)
            elif self.manga.server.id == 'local':
                logo = Adw.Avatar.new(self.server_logo_size, None, False)
                logo.set_icon_name('folder-symbolic')
            else:
                logo = Adw.Avatar.new(self.server_logo_size, self.manga.server.name, True)

        if Settings.get_default().library_display_mode == 'grid-compact':
            # Compact grid
            self.overlay = Gtk.Overlay()
            self.overlay.set_child(self.picture)

            self.name_label = Gtk.Label(xalign=0)
            self.name_label.add_css_class('library-thumbnail-name-label')
            self.name_label.set_valign(Gtk.Align.END)
            self.name_label.set_wrap(True)
            self.overlay.add_overlay(self.name_label)

            if Settings.get_default().library_servers_logo:
                logo.props.margin_start = 6
                logo.props.margin_top = 6
                logo.props.halign = Gtk.Align.START
                logo.props.valign = Gtk.Align.START
                self.overlay.add_overlay(logo)

            self.set_child(self.overlay)
        else:
            # Expanded grid
            box = Gtk.Grid(row_spacing=4)
            box.attach(self.picture, 0, 0, 2, 1)

            self.name_label = Gtk.Label(hexpand=True)
            self.name_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            self.name_label.add_css_class('caption')
            self.name_label.set_lines(1)
            self.name_label.set_wrap(True)
            self.name_label.set_max_width_chars(0)

            if Settings.get_default().library_servers_logo:
                self.name_label.props.xalign = 0
                box.attach(self.name_label, 0, 1, 1, 1)

                logo.props.halign = Gtk.Align.END
                logo.props.valign = Gtk.Align.CENTER

                box.attach(logo, 1, 1, 1, 1)
            else:
                self.name_label.set_justify(Gtk.Justification.CENTER)
                box.attach(self.name_label, 0, 1, 2, 1)

            self.set_child(box)

        self.__draw_name()

        self.resize(width, height)

    def __draw_name(self):
        self.name_label.set_text(self.manga.name + ' ')

    def resize(self, width, height):
        cover = self.picture.get_paintable()
        if cover.width == width:
            return

        cover.resize(width, height)

    def update(self, manga=None):
        if manga:
            self.manga = manga
            self.__draw_name()

        self.picture.get_paintable().update(manga)


class ThumbnailCover(GObject.GObject, Gdk.Paintable):
    __gtype_name__ = 'ThumbnailCover'

    corners_radius = 8
    cover_font_size = 9
    width = None
    height = None

    def __init__(self, manga):
        super().__init__()

        self.manga = manga

        self.cover_texture = None

        self.rect = Graphene.Rect().alloc()
        self.rounded_rect = Gsk.RoundedRect()
        self.rounded_rect_size = Graphene.Size().alloc()
        self.rounded_rect_size.init(self.corners_radius, self.corners_radius)

        font = Pango.FontDescription.new()
        font.set_weight(Pango.Weight.HEAVY)
        font.set_size(self.cover_font_size * Pango.SCALE)
        self.badge_layout = Pango.Layout(Gio.Application.get_default().window.get_pango_context())
        self.badge_layout.set_font_description(font)
        self.badge_text_color = Gdk.RGBA()
        self.badge_text_color.parse('#ffffff')

        self.__get_badges_values()
        self.__create_cover_texture()

    def __create_cover_texture(self):
        if self.manga.cover_fs_path is None:
            paintable = CoverLoader.new_from_resource(MISSING_IMG_RESOURCE_PATH, COVER_WIDTH, None)
        else:
            paintable = CoverLoader.new_from_file(self.manga.cover_fs_path, COVER_WIDTH, None, True)
            if paintable is None:
                paintable = CoverLoader.new_from_resource(MISSING_IMG_RESOURCE_PATH, COVER_WIDTH, None)

        self.cover_texture = Gdk.Texture.new_for_pixbuf(paintable.pixbuf) if paintable.pixbuf else paintable.texture

    def __get_badges_values(self):
        badges = Settings.get_default().library_badges
        self.nb_unread_chapters = self.manga.nb_unread_chapters if 'unread-chapters' in badges else None
        self.nb_downloaded_chapters = self.manga.nb_downloaded_chapters if 'downloaded-chapters' in badges else None
        self.nb_recent_chapters = self.manga.nb_recent_chapters if 'recent-chapters' in badges else None

    def do_get_intrinsic_height(self):
        return self.height

    def do_get_intrinsic_width(self):
        return self.width

    def do_snapshot(self, snapshot, width, height):
        self.rect.init(0, 0, width, height)

        # Draw cover (rounded)
        self.rounded_rect.init(self.rect, self.rounded_rect_size, self.rounded_rect_size, self.rounded_rect_size, self.rounded_rect_size)
        snapshot.push_rounded_clip(self.rounded_rect)
        snapshot.append_texture(self.cover_texture, self.rect)
        snapshot.pop()  # remove the clip

        # Draw badges (top right corner)
        spacing = 5  # with top border, right border and between badges
        x = width

        def draw_badge(value, color):
            nonlocal x

            if not value:
                return

            self.badge_layout.set_text(str(value))
            extent = self.badge_layout.get_pixel_extents()[1]
            w = extent.width + 2 * 7
            h = extent.height + 2 * 1

            # Draw rounded rectangle (pill)
            x = x - spacing - w
            y = spacing

            bg_color = Gdk.RGBA()
            bg_color.parse(color)

            rect = self.rect.init(x, y, w, h)
            self.rounded_rect.init_from_rect(self.rect, radius=90)

            snapshot.push_rounded_clip(self.rounded_rect)
            snapshot.append_color(bg_color, rect)
            snapshot.pop()  # remove the clip

            # Draw number
            point = Graphene.Point()
            point.init(x + 7, y + 1)

            snapshot.save()
            snapshot.translate(point)
            snapshot.append_layout(self.badge_layout, self.badge_text_color)
            snapshot.restore()

        draw_badge(self.nb_unread_chapters, '#62a0ea')      # @blue_2
        draw_badge(self.nb_downloaded_chapters, '#f68276')
        draw_badge(self.nb_recent_chapters, '#33d17a')      # @green_3

    def resize(self, width, height):
        self.width = width
        self.height = height

        self.invalidate_size()

    def update(self, manga=None):
        if manga:
            self.manga = manga

            self.cover_texture = None
            self.__create_cover_texture()

        self.__get_badges_values()

        self.invalidate_contents()
