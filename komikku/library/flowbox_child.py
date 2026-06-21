# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
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


class LibraryFlowBoxChildBase:
    default_width = COVER_WIDTH
    default_height = COVER_HEIGHT
    margins = (3 + 3 + 3) * 2  # FlowBoxChild margin + FlowBoxChild border + FlowBoxChild child margin
    server_logo_size = 16

    cover_picture: Gtk.Picture
    name_label: Gtk.Label

    def __init__(self, parent, manga):
        self.parent = parent
        self.manga = manga
        self._filtered = False
        self._selected = False

        self.cover_picture.set_paintable(LibraryFlowBoxChildCoverPaintable(manga))

        # Logo widget (Gtk.Image or Adw.Avatar as fallback)
        if Settings.get_default().library_servers_logo:
            if self.manga.server.logo_path:
                self.logo = Gtk.Image.new_from_file(self.manga.server.logo_path)
                self.logo.set_pixel_size(self.server_logo_size)
            elif self.manga.server.id == 'local':
                self.logo = Adw.Avatar.new(self.server_logo_size, None, False)
                self.logo.set_icon_name('folder-symbolic')
            else:
                self.logo = Adw.Avatar.new(self.server_logo_size, self.manga.server.name, True)
        else:
            self.logo = None

    def draw_name(self):
        self.name_label.set_text(self.manga.name)

    def resize_cover(self, width, height):
        cover = self.cover_picture.get_paintable()
        if cover.width == width:
            return

        cover.resize(width, height)

    def update(self, manga=None):
        if manga:
            self.manga = manga
            self.draw_name()

        self.cover_picture.get_paintable().update(manga)


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/library_compact_flowbox_child.ui')
class LibraryCompactFlowBoxChild(Gtk.FlowBoxChild, LibraryFlowBoxChildBase):
    __gtype_name__ = 'LibraryCompactFlowBoxChild'

    overlay = Gtk.Template.Child('overlay')
    cover_picture = Gtk.Template.Child('cover_picture')
    name_label = Gtk.Template.Child('name_label')

    def __init__(self, parent, manga, width, height):
        Gtk.FlowBoxChild.__init__(self)
        LibraryFlowBoxChildBase.__init__(self, parent, manga)

        if self.logo:
            self.logo.props.margin_start = 6
            self.logo.props.margin_top = 6
            self.logo.props.halign = Gtk.Align.START
            self.logo.props.valign = Gtk.Align.START
            self.overlay.add_overlay(self.logo)

        self.draw_name()
        self.resize_cover(width, height)


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/library_flowbox_child.ui')
class LibraryFlowBoxChild(Gtk.FlowBoxChild, LibraryFlowBoxChildBase):
    __gtype_name__ = 'LibraryFlowBoxChild'

    grid = Gtk.Template.Child('grid')
    cover_picture = Gtk.Template.Child('cover_picture')
    name_label = Gtk.Template.Child('name_label')

    def __init__(self, parent, manga, width, height):
        Gtk.FlowBoxChild.__init__(self)
        LibraryFlowBoxChildBase.__init__(self, parent, manga)

        if self.logo:
            self.name_label.props.xalign = 0

            self.logo.props.halign = Gtk.Align.END
            self.logo.props.valign = Gtk.Align.CENTER

            self.grid.attach(self.logo, 1, 1, 1, 1)
        else:
            self.name_label.set_justify(Gtk.Justification.CENTER)

        self.draw_name()
        self.resize_cover(width, height)


class LibraryFlowBoxChildCoverPaintable(GObject.GObject, Gdk.Paintable):
    __gtype_name__ = 'LibraryFlowBoxChildCoverPaintable'

    badge_font_size = 9
    badge_layout = None
    badge_text_color = Gdk.RGBA(1, 1, 1, 1)
    rect = Graphene.Rect().alloc()
    rounded_rect = Gsk.RoundedRect()
    rounded_rect_size = Graphene.Size.init(Graphene.Size().alloc(), 8, 8)

    def __init__(self, manga):
        super().__init__()

        self.manga = manga
        self.cover_texture = None
        self.width = None
        self.height = None

        if LibraryFlowBoxChildCoverPaintable.badge_layout is None:
            pango_context = Gio.Application.get_default().window.get_pango_context()

            font = pango_context.get_font_description()
            font.set_size(self.badge_font_size * Pango.SCALE)
            font.set_weight(Pango.Weight.HEAVY)

            LibraryFlowBoxChildCoverPaintable.badge_layout = Pango.Layout(pango_context)
            LibraryFlowBoxChildCoverPaintable.badge_layout.set_font_description(font)

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
            snapshot.save()
            snapshot.translate(Graphene.Point().init(x + 7, y + 1))
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
            self.__create_cover_texture()

        self.__get_badges_values()

        self.invalidate_contents()
