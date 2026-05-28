# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import pytz

from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Pango

from komikku.consts import COVER_WIDTH
from komikku.consts import MISSING_IMG_RESOURCE_PATH
from komikku.consts import TIMEZONE
from komikku.card.synopsis_fading import SynopsisFading
from komikku.models import Category
from komikku.utils import CoverPicture
from komikku.utils import folder_size
from komikku.utils import html_escape


class InfoBox:
    def __init__(self, card):
        self.card = card
        self.window = card.window

        self.title_box = self.card.title_box
        self.cover_box = self.card.cover_box
        self.cover_picture = None
        self.name_label = self.card.name_label
        self.authors_label = self.card.authors_label
        self.status_server_label = self.card.status_server_label
        self.buttons_box = self.card.buttons_box
        self.add_button = self.card.add_button
        self.resume_button = self.card.resume_button
        self.genres_wrapbox = self.card.genres_wrapbox
        self.categories_wrapbox = self.card.categories_wrapbox
        self.scanlators_label = self.card.scanlators_label
        self.chapters_label = self.card.chapters_label
        self.last_update_label = self.card.last_update_label
        self.size_on_disk_label = self.card.size_on_disk_label

        # Synopsis
        self.synopsis_box = self.card.synopsis_box
        self.synopsis_togglebutton = self.card.synopsis_togglebutton
        # To distinguish the `Show Less/More` button from the `Resume` button,
        # we apply `circular` class rather than `pill`
        # This makes it smaller in height, but it requires increasing start and end margins
        togglebutton_label = self.card.synopsis_togglebutton.get_child()
        togglebutton_label.props.margin_start = 24
        togglebutton_label.props.margin_end = 24
        self.synopsis_fading = SynopsisFading()
        self.synopsis_label = Gtk.Label(hexpand=True, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
        self.synopsis_label.set_css_classes(['document'])
        self.synopsis_fading.set_child(self.synopsis_label)
        self.synopsis_box.prepend(self.synopsis_fading)

        self.add_button.connect('clicked', self.card.on_add_button_clicked)
        self.resume_button.connect('clicked', self.card.on_resume_button_clicked)
        self.synopsis_togglebutton.connect('toggled', self.on_synopsis_togglebutton_toggled)
        self.synopsis_fading.bind_property(
            'faded', self.synopsis_togglebutton, 'visible',
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
        )

        self.window.breakpoint.add_setter(self.title_box, 'orientation', Gtk.Orientation.VERTICAL)
        self.window.breakpoint.add_setter(self.title_box, 'spacing', 12)
        self.window.breakpoint.add_setter(self.name_label, 'halign', Gtk.Align.CENTER)
        self.window.breakpoint.add_setter(self.name_label, 'justify', Gtk.Justification.CENTER)
        self.window.breakpoint.add_setter(self.status_server_label, 'halign', Gtk.Align.CENTER)
        self.window.breakpoint.add_setter(self.status_server_label, 'justify', Gtk.Justification.CENTER)
        self.window.breakpoint.add_setter(self.authors_label, 'halign', Gtk.Align.CENTER)
        self.window.breakpoint.add_setter(self.authors_label, 'justify', Gtk.Justification.CENTER)
        self.window.breakpoint.add_setter(self.buttons_box, 'orientation', Gtk.Orientation.VERTICAL)
        self.window.breakpoint.add_setter(self.buttons_box, 'spacing', 18)
        self.window.breakpoint.add_setter(self.buttons_box, 'halign', Gtk.Align.CENTER)

    def on_synopsis_togglebutton_toggled(self, button):
        active = button.get_active()
        self.synopsis_togglebutton.set_label(_('Show Less') if active else _('Show More'))
        self.synopsis_fading.set_revealed(active)

    def populate(self):
        manga = self.card.manga

        # Name
        self.name_label.set_text(manga.name)

        # Cover
        if self.cover_picture:
            self.cover_box.remove(self.cover_picture)

        if manga.cover_fs_path is None:
            self.cover_picture = CoverPicture.new_from_resource(MISSING_IMG_RESOURCE_PATH, width=COVER_WIDTH)
            self.card.remove_backdrop()
        else:
            picture = CoverPicture.new_from_file(manga.cover_fs_path, width=COVER_WIDTH)
            if picture:
                self.cover_picture = picture
                self.card.set_backdrop()
            else:
                self.cover_picture = CoverPicture.new_from_resource(MISSING_IMG_RESOURCE_PATH, width=COVER_WIDTH)
                self.card.remove_backdrop()

        self.cover_picture.props.can_shrink = False
        self.cover_picture.add_css_class('cover-dropshadow')
        self.cover_box.append(self.cover_picture)

        # Authors
        authors = html_escape(', '.join(manga.authors)) if manga.authors else _('Unknown author')
        self.authors_label.set_markup(authors)

        # Server (link to server page)
        if not manga.is_local:
            self.status_server_label.set_markup(
                '{0} · <a href="{1}">{2}</a> ({3})'.format(
                    _(manga.STATUSES[manga.status]) if manga.status else _('Unknown status'),
                    manga.server.get_manga_url(manga.slug, manga.url),
                    html_escape(manga.server.name),
                    manga.server.lang.upper() if manga.server.lang else '??'
                )
            )
        else:
            self.status_server_label.set_text('{0} · {1}'.format(_('Unknown status'), _('Local')))

        # Resume button
        if manga.in_library:
            self.add_button.set_visible(False)
            self.resume_button.add_css_class('suggested-action')
        else:
            self.add_button.set_visible(True)
            self.resume_button.remove_css_class('suggested-action')

        # Genres
        if manga.genres:
            self.genres_wrapbox.remove_all()

            for genre in sorted(manga.genres):
                label = Gtk.Label()
                label.set_ellipsize(Pango.EllipsizeMode.END)
                label.set_markup(html_escape(genre))
                label.set_css_classes(['genre-label', 'caption'])
                self.genres_wrapbox.append(label)

            self.genres_wrapbox.get_parent().set_visible(True)
        else:
            self.genres_wrapbox.get_parent().set_visible(False)

        # Categories
        self.set_categories()

        # Scanlators
        if manga.scanlators:
            self.scanlators_label.set_markup(html_escape(', '.join(manga.scanlators)))
            self.scanlators_label.get_parent().set_visible(True)
        else:
            self.scanlators_label.get_parent().set_visible(False)

        # Number of chapters
        self.chapters_label.set_text(str(len(manga.chapters)))

        # Last update date
        if manga.last_update:
            self.last_update_label.set_text(
                manga.last_update.replace(tzinfo=pytz.UTC).astimezone(TIMEZONE).strftime(_('%m/%d/%Y %H:%M'))
            )
            self.last_update_label.get_parent().set_visible(True)
        else:
            self.last_update_label.get_parent().set_visible(False)

        # Disk usage
        self.set_disk_usage()

        # Synopsis
        self.synopsis_fading.set_markup('-')
        if manga.synopsis:
            self.synopsis_box.set_visible(True)
            self.synopsis_togglebutton.set_label(_('Show More'))
            self.synopsis_togglebutton.set_active(False)

            synopsis = manga.synopsis
            if manga.server.donate_url:
                synopsis = f'<a href="{manga.server.donate_url}">{_("Donate")}</a>\n\n{synopsis}'

            self.synopsis_fading.set_markup(synopsis)  # can failed with a warning: parsing markup error
        else:
            self.synopsis_box.set_visible(False)

    def refresh(self):
        self.set_disk_usage()

    def set_categories(self):
        if self.card.manga.categories:
            self.categories_wrapbox.remove_all()

            for category_id in sorted(self.card.manga.categories):
                category = Category.get(category_id)
                label = Gtk.Label()
                label.set_ellipsize(Pango.EllipsizeMode.END)
                label.set_markup(html_escape(category.label))
                label.set_css_classes(['category-label', 'caption'])
                self.categories_wrapbox.append(label)

            self.categories_wrapbox.get_parent().set_visible(True)
        else:
            self.categories_wrapbox.get_parent().set_visible(False)

    def set_disk_usage(self):
        self.size_on_disk_label.set_text(folder_size(self.card.manga.path) or '-')
