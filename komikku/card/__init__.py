# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _

from gi.repository import Adw
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Pango

from komikku.consts import COVER_WIDTH
from komikku.consts import MISSING_IMG_RESOURCE_PATH
from komikku.card.categories_list import CategoriesList
from komikku.card.chapters_list import ChaptersList
from komikku.card.tracking import TrackingDialog
from komikku.models import Category
from komikku.models import Settings
from komikku.utils import CoverPicture
from komikku.utils import folder_size
from komikku.utils import html_escape


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/card.ui')
class CardPage(Adw.NavigationPage):
    __gtype_name__ = 'CardPage'

    toolbar_view = Gtk.Template.Child('toolbar_view')
    left_button = Gtk.Template.Child('left_button')
    filters_button = Gtk.Template.Child('filters_button')
    title_stack = Gtk.Template.Child('title_stack')
    title = Gtk.Template.Child('title')
    viewswitcher = Gtk.Template.Child('viewswitcher')
    menu_button = Gtk.Template.Child('menu_button')

    activity_progressbar = Gtk.Template.Child('activity_progressbar')
    stack = Gtk.Template.Child('stack')
    categories_stack = Gtk.Template.Child('categories_stack')
    categories_scrolledwindow = Gtk.Template.Child('categories_scrolledwindow')
    categories_listbox = Gtk.Template.Child('categories_listbox')
    chapters_scrolledwindow = Gtk.Template.Child('chapters_scrolledwindow')
    chapters_listview = Gtk.Template.Child('chapters_listview')
    chapters_selection_mode_actionbar = Gtk.Template.Child('chapters_selection_mode_actionbar')
    chapters_selection_mode_download_button = Gtk.Template.Child('chapters_selection_mode_download_button')
    chapters_selection_mode_clear_button = Gtk.Template.Child('chapters_selection_mode_clear_button')
    chapters_selection_mode_clear_reset_button = Gtk.Template.Child('chapters_selection_mode_clear_reset_button')
    chapters_selection_mode_menubutton = Gtk.Template.Child('chapters_selection_mode_menubutton')
    info_scrolledwindow = Gtk.Template.Child('info_scrolledwindow')
    backdrop_picture = Gtk.Template.Child('backdrop_picture')
    title_box = Gtk.Template.Child('title_box')
    cover_box = Gtk.Template.Child('cover_box')
    name_label = Gtk.Template.Child('name_label')
    authors_label = Gtk.Template.Child('authors_label')
    status_server_label = Gtk.Template.Child('status_server_label')
    buttons_box = Gtk.Template.Child('buttons_box')
    add_button = Gtk.Template.Child('add_button')
    resume_button = Gtk.Template.Child('resume_button')
    genres_wrapbox = Gtk.Template.Child('genres_wrapbox')
    categories_wrapbox = Gtk.Template.Child('categories_wrapbox')
    scanlators_label = Gtk.Template.Child('scanlators_label')
    chapters_label = Gtk.Template.Child('chapters_label')
    last_update_label = Gtk.Template.Child('last_update_label')
    synopsis_label = Gtk.Template.Child('synopsis_label')
    size_on_disk_label = Gtk.Template.Child('size_on_disk_label')
    viewswitcherbar = Gtk.Template.Child('viewswitcherbar')

    manga = None
    pool_to_update = False
    pool_to_update_offset = 0
    selection_mode = False

    def __init__(self, window):
        Adw.NavigationPage.__init__(self)

        self.window = window
        self.builder = window.builder
        self.builder.add_from_resource('/info/febvre/Komikku/ui/menu/card.xml')
        self.builder.add_from_resource('/info/febvre/Komikku/ui/menu/card_selection_mode.xml')

        self.css_provider = Gtk.CssProvider.new()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.connect('shown', self.on_shown)
        self.stack.connect('notify::visible-child-name', self.on_page_changed)
        self.window.controller_key.connect('key-pressed', self.on_key_pressed)

        # Header bar
        self.left_button.connect('clicked', self.leave_selection_mode)
        self.filters_button.connect('clicked', self.on_filters_button_clicked)
        self.menu_button.set_menu_model(self.builder.get_object('menu-card'))
        # Focus is lost after showing popover submenu (bug?)
        self.menu_button.get_popover().connect('closed', lambda _popover: self.menu_button.grab_focus())

        # Pool-to-Update
        self.pool_to_update_revealer = self.window.pool_to_update_revealer
        self.pool_to_update_spinner = self.window.pool_to_update_spinner
        # Drag gesture
        self.gesture_drag = Gtk.GestureDrag.new()
        self.gesture_drag.set_touch_only(True)
        self.gesture_drag.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.gesture_drag.connect('drag-end', self.on_gesture_drag_end)
        self.gesture_drag.connect('drag-update', self.on_gesture_drag_update)
        self.stack.add_controller(self.gesture_drag)

        self.tracking_dialog = TrackingDialog(self.window)

        self.info_box = InfoBox(self)
        self.categories_list = CategoriesList(self)
        self.chapters_list = ChaptersList(self)

        self.filters_dialog = Adw.PreferencesDialog.new()
        self.filters_dialog.set_title(_('Filters'))
        self.filters_dialog.props.presentation_mode = Adw.DialogPresentationMode.BOTTOM_SHEET

        self.window.updater.connect('manga-updated', self.on_manga_updated)
        self.window.trackers.connect('manga-tracker-synced', self.on_manga_tracker_synced)

        self.window.breakpoint.add_setter(self.viewswitcherbar, 'reveal', True)
        self.window.breakpoint.add_setter(self.title_stack, 'visible-child', self.title)

        self.window.navigationview.add(self)

    def add_actions(self):
        self.resume_action = Gio.SimpleAction.new('card.resume', None)
        self.resume_action.connect('activate', self.on_resume_button_clicked)
        self.window.application.add_action(self.resume_action)

        self.update_action = Gio.SimpleAction.new('card.update', None)
        self.update_action.connect('activate', self.on_update_request)
        self.window.application.add_action(self.update_action)

        self.clear_action = Gio.SimpleAction.new('card.clear', None)
        self.clear_action.connect('activate', self.on_clear_menu_clicked)
        self.window.application.add_action(self.clear_action)

        self.delete_action = Gio.SimpleAction.new('card.delete', None)
        self.delete_action.connect('activate', self.on_delete_menu_clicked)
        self.window.application.add_action(self.delete_action)

        variant = GLib.Variant.new_string('desc')
        self.sort_order_action = Gio.SimpleAction.new_stateful('card.sort-order', variant.get_type(), variant)
        self.sort_order_action.connect('activate', self.chapters_list.on_sort_order_changed)
        self.window.application.add_action(self.sort_order_action)

        self.manage_tracking_action = Gio.SimpleAction.new('card.manage-tracking', None)
        self.manage_tracking_action.connect('activate', self.on_manage_tracking_menu_clicked)
        self.window.application.add_action(self.manage_tracking_action)

        self.open_in_browser_action = Gio.SimpleAction.new('card.open-in-browser', None)
        self.open_in_browser_action.connect('activate', self.on_open_in_browser_menu_clicked)
        self.window.application.add_action(self.open_in_browser_action)

        self.chapters_list.add_actions()

    def enter_selection_mode(self, init=False):
        if self.selection_mode:
            return

        self.selection_mode = True
        self.chapters_list.enter_selection_mode(init)

        self.props.can_pop = False

        self.left_button.set_label(_('Cancel'))
        self.left_button.set_tooltip_text(_('Cancel'))
        self.left_button.set_visible(True)

        self.viewswitcher.set_visible(False)
        self.viewswitcherbar.set_visible(False)
        self.title_stack.set_visible_child(self.title)

        self.menu_button.set_visible(False)

    def init(self, manga):
        # Default page is `Info`
        self.stack.set_visible_child_name('info')

        # Hide Categories if manga is not in Library
        self.stack.get_page(self.stack.get_child_by_name('categories')).set_visible(manga.in_library)

        self.manga = manga
        # Unref chapters to force a reload
        self.manga._chapters = None

        self.set_unread_chapters_badge()

        self.show()

    def leave_selection_mode(self, *args):
        self.selection_mode = False
        self.chapters_list.leave_selection_mode()

        self.props.can_pop = True

        self.left_button.set_visible(False)

        self.viewswitcher.set_visible(True)
        self.viewswitcherbar.set_visible(True)
        self.title.set_subtitle('')
        if not self.viewswitcherbar.get_reveal():
            self.title_stack.set_visible_child(self.viewswitcher)

        self.menu_button.set_visible(True)

    def on_add_button_clicked(self, _button):
        # Show categories
        self.stack.get_page(self.stack.get_child_by_name('categories')).set_visible(True)
        # Hide Add to Library button
        self.info_box.add_button.set_visible(False)
        self.info_box.resume_button.add_css_class('suggested-action')
        # Update manga
        self.manga.add_in_library()
        self.window.library.on_manga_added(self.manga)

    def on_clear_menu_clicked(self, _action, _gparam):
        def confirm_callback():
            self.manga.clear()
            self.refresh(info=True, chapters=self.manga.chapters)
            self.window.library.refresh_on_manga_state_changed(self.manga)

        self.window.open_dialog(
            _('Clear?'),
            body=_('Are you sure you want to clear all chapters?'),
            confirm_label=_('Clear'),
            confirm_callback=confirm_callback,
            confirm_appearance=Adw.ResponseAppearance.DESTRUCTIVE
        )

    def on_delete_menu_clicked(self, _action, _gparam):
        self.window.library.delete_mangas([self.manga, ])

    def on_filters_button_clicked(self, _button):
        filters = self.manga.filters or {}

        def on_active(row, _param, scanlator):
            if 'scanlators' not in filters:
                filters['scanlators'] = []

            if row.get_active():
                filters['scanlators'].remove(scanlator)
            else:
                filters['scanlators'].append(scanlator)

            if filters['scanlators']:
                self.filters_button.add_css_class('accent')
            else:
                self.filters_button.remove_css_class('accent')

            self.manga.update({
                'filters': filters,
            })

            self.chapters_list.list_model.invalidate_filter()

        # Remove a previous used page if exists
        if page := self.filters_dialog.get_visible_page():
            self.filters_dialog.remove(page)

        page = Adw.PreferencesPage(title=_('Filters'))
        self.filters_dialog.add(page)

        group = Adw.PreferencesGroup()
        group.set_title('Chapters Scanlation Groups')

        for scanlator in self.manga.chapters_scanlators:
            title = html_escape(scanlator['name'])
            if title == 'Unknown':
                title = _('Unknown')

            row = Adw.SwitchRow(title=title)
            row.set_use_markup(True)
            row.set_active(not filters or 'scanlators' not in filters or scanlator['name'] not in filters['scanlators'])
            row.connect('notify::active', on_active, scanlator['name'])

            label = Gtk.Label(label=scanlator['count'], valign=Gtk.Align.CENTER)
            label.set_css_classes(['badge', 'caption'])
            row.add_prefix(label)

            group.add(row)

        page.add(group)

        self.filters_dialog.present(self.window)

    def on_gesture_drag_end(self, _controller, _offset_x, _offset_y):
        self.stack.set_opacity(1)
        self.stack.remove_css_class('grayscale')

        if not self.pool_to_update:
            return

        self.pool_to_update = False
        self.pool_to_update_revealer.props.transition_type = Gtk.RevealerTransitionType.SLIDE_DOWN
        self.pool_to_update_revealer.set_reveal_child(False)
        self.pool_to_update_spinner.props.margin_top = 0

        if self.pool_to_update_offset > 2 * 150:
            self.on_update_request()

        self.gesture_drag.set_state(Gtk.EventSequenceState.CLAIMED)

    def on_gesture_drag_update(self, _controller, _offset_x, offset_y):
        _active, start_x, start_y = self.gesture_drag.get_start_point()

        page = self.stack.get_visible_child_name()
        if page == 'info':
            scroll_value = self.info_scrolledwindow.get_vadjustment().props.value
        elif page == 'chapters':
            scroll_value = self.chapters_scrolledwindow.get_vadjustment().props.value
        else:
            scroll_value = self.categories_scrolledwindow.get_vadjustment().props.value

        if scroll_value != 0 or offset_y < 0 or self.selection_mode or start_x < 32 or start_y > self.get_height() / 3:
            return

        self.stack.set_opacity(0.5)
        self.stack.add_css_class('grayscale')

        self.pool_to_update_offset = offset_y

        if not self.pool_to_update:
            self.pool_to_update = True
            # Adjust revealer position
            self.pool_to_update_revealer.set_margin_top(self.toolbar_view.get_top_bar_height())
            self.pool_to_update_revealer.props.transition_type = Gtk.RevealerTransitionType.NONE
            self.pool_to_update_revealer.set_reveal_child(True)
        else:
            self.pool_to_update_spinner.props.margin_top = max(0, min(150, offset_y / 2))

    def on_key_pressed(self, _controller, keyval, _keycode, state):
        if self.window.page != self.props.tag:
            return Gdk.EVENT_PROPAGATE
        if self.stack.get_visible_child_name() != 'chapters':
            return Gdk.EVENT_PROPAGATE

        modifiers = state & Gtk.accelerator_get_default_mod_mask()
        if self.selection_mode:
            if keyval == Gdk.KEY_Escape or (modifiers == Gdk.ModifierType.ALT_MASK and keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left)):
                self.leave_selection_mode()
                # Stop event to prevent back navigation
                return Gdk.EVENT_STOP
        else:
            # Allow to enter in selection mode with <SHIFT>+Arrow key
            if modifiers != Gdk.ModifierType.SHIFT_MASK or keyval not in (Gdk.KEY_Up, Gdk.KEY_KP_Up, Gdk.KEY_Down, Gdk.KEY_KP_Down):
                return Gdk.EVENT_PROPAGATE

            self.enter_selection_mode()

        return Gdk.EVENT_PROPAGATE

    def on_manage_tracking_menu_clicked(self, _action, _menu):
        self.tracking_dialog.show()

    def on_manga_tracker_synced(self, _trackers, manga):
        if (self.window.page == self.props.tag or self.window.previous_page == self.props.tag) and self.manga.id == manga.id:
            self.manga = manga

    def on_manga_updated(self, _updater, manga, chapters_changes, synced):
        if (self.window.page == self.props.tag or self.window.previous_page == self.props.tag) and self.manga.id == manga.id:
            self.manga = manga

            self.info_box.populate()
            self.toggle_filters_button()

            if sum(chapters_changes.values()) > 0:
                self.chapters_list.populate()
                self.refresh(unread_chapters=True)

            if synced:
                self.window.add_notification(_('Read progress synchronization with server completed successfully'))

    def on_open_in_browser_menu_clicked(self, _action, _gparam):
        if uri := self.manga.server.get_manga_url(self.manga.slug, self.manga.url):
            Gtk.UriLauncher.new(uri=uri).launch()
        else:
            self.window.add_notification(_('Failed to get manga URL'))

    def on_page_changed(self, _page, _gparam):
        self.toggle_filters_button()

    def on_resume_button_clicked(self, *args):
        last_read_chapter = self.manga.last_read_chapter
        if last_read_chapter and last_read_chapter.read:
            # If last read chapter has been read in full, use next chapter
            last_read_chapter = self.manga.get_next_chapter(last_read_chapter)

        if last_read_chapter is None:
            # Use first chapter
            if self.chapters_list.sort_order.endswith('desc'):
                last_read_chapter = self.chapters_list.list_model.get_item(self.chapters_list.list_model.get_n_items() - 1).chapter
            else:
                last_read_chapter = self.chapters_list.list_model.get_item(0).chapter

        self.window.reader.init(self.manga, last_read_chapter)

    def on_shown(self, _page):
        def do_populate():
            if self.manga.server.status == 'disabled':
                self.window.add_notification(
                    _('NOTICE\n{0} is no longer supported.\nPlease switch to another server.').format(self.manga.server.name)
                )

            # Show update indicator (in case an update is in progress)
            self.show_activity_indicator()

            if self.window.last_navigation_action != 'push':
                return

            # Wait page is shown (transition is ended) to populate
            # Operation is resource intensive and could disrupt page transition
            self.populate()

        if not Gtk.Settings.get_default().get_property('gtk-enable-animations'):
            # When animations are disabled, popped/pushed events are sent after `shown` event (bug?)
            # Use idle_add to be sure that last `popped` or `pushed` event has been received
            GLib.idle_add(do_populate)
        else:
            do_populate()

    def on_update_request(self, _action=None, _param=None):
        self.window.updater.add(self.manga)
        if self.window.updater.start():
            # Start update indicator
            self.show_activity_indicator()

    def populate(self):
        self.chapters_list.set_sort_order(invalidate=False)

        self.chapters_list.populate()
        self.categories_list.populate()

    def refresh(self, unread_chapters=False, info=False, chapters=None):
        if unread_chapters:
            self.set_unread_chapters_badge()

        if info:
            self.info_box.refresh()

        if chapters is not None:
            self.chapters_list.refresh(chapters)

    def remove_backdrop(self):
        self.remove_css_class('backdrop')
        self.backdrop_picture.set_paintable(None)
        self.backdrop_picture.set_opacity(1)

    def set_actions_enabled(self, enabled):
        self.delete_action.set_enabled(enabled)
        self.update_action.set_enabled(enabled)
        self.sort_order_action.set_enabled(enabled)

    def set_backdrop(self):
        self.remove_backdrop()

        method = Settings.get_default().card_backdrop_method
        if not self.manga or Adw.StyleManager.get_default().get_high_contrast() or not method:
            return

        if method == 'blurred-cover':
            if path := self.manga.backdrop_image_fs_path:
                self.backdrop_picture.set_filename(path)

                if info := self.manga.backdrop_info:
                    if Adw.StyleManager.get_default().get_dark():
                        opacity = 1 - info['luminance'][0]
                    else:
                        opacity = info['luminance'][1]
                    self.backdrop_picture.set_opacity(opacity)

        elif method == 'linear-gradient':
            if css := self.manga.backdrop_colors_css:
                self.css_provider.load_from_string(css)

        self.add_css_class('backdrop')

    def set_unread_chapters_badge(self):
        # Show unread chapters (with Adw.ViewStackPage badge) if any
        if unread_chapters := self.manga.nb_unread_chapters:
            self.stack.get_page(self.stack.get_child_by_name('chapters')).set_badge_number(unread_chapters)
        else:
            self.stack.get_page(self.stack.get_child_by_name('chapters')).set_badge_number(0)

    def show(self):
        self.props.title = self.manga.name  # Adw.NavigationPage title

        self.toggle_filters_button()
        self.title.set_title(self.manga.name)
        self.info_box.populate()

        # Adjust some buttons of action bar (visible in selection mode)
        self.chapters_selection_mode_download_button.set_sensitive(not self.manga.is_local)
        self.chapters_selection_mode_clear_button.set_sensitive(not self.manga.is_local)
        self.chapters_selection_mode_clear_reset_button.set_tooltip_text(_('Clear and Reset') if not self.manga.is_local else _('Reset'))

        self.open_in_browser_action.set_enabled(not self.manga.is_local)

        # Reset scrolling in all pages
        for page in self.stack.get_pages():
            scrolledwindow = page.get_child() if page.props.name != 'chapters' else page.get_child().get_first_child()
            scrolledwindow.get_vadjustment().configure(0, 0, 0, 0, 0, 0)

        self.window.navigationview.push(self)

    def show_activity_indicator(self):
        def pulse(manga_id):
            if self.window.page != self.props.tag:
                # Page left, stop indicator
                self.activity_progressbar.props.fraction = 0
                return GLib.SOURCE_REMOVE

            if self.window.updater.current_id == manga_id:
                self.activity_progressbar.pulse()
                return GLib.SOURCE_CONTINUE

            # Update is ended, stop indicator
            self.activity_progressbar.props.fraction = 0
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(250, pulse, self.manga.id)

    def toggle_filters_button(self):
        name = self.stack.get_visible_child_name()

        if name == 'chapters':
            # Show button if chapters have at least 2 different scanlators
            self.filters_button.set_visible(self.manga.chapters_scanlators and len(self.manga.chapters_scanlators) > 1)
            if self.manga.filters and self.manga.filters.get('scanlators'):
                self.filters_button.add_css_class('accent')
            else:
                self.filters_button.remove_css_class('accent')
        else:
            # Button is visible in `Chapters` page only
            self.filters_button.set_visible(False)

    def toggle_resume(self, state):
        self.resume_action.set_enabled(state)
        self.resume_button.set_sensitive(state)


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
        self.synopsis_label = self.card.synopsis_label
        self.size_on_disk_label = self.card.size_on_disk_label

        self.add_button.connect('clicked', self.card.on_add_button_clicked)
        self.resume_button.connect('clicked', self.card.on_resume_button_clicked)

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
            self.status_server_label.set_markup(
                '{0} · {1}'.format(
                    _('Unknown status'),
                    html_escape(_('Local'))
                )
            )

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
        self.chapters_label.set_markup(str(len(manga.chapters)))

        # Last update date
        if manga.last_update:
            self.last_update_label.set_markup(manga.last_update.strftime(_('%m/%d/%Y')))
            self.last_update_label.get_parent().set_visible(True)
        else:
            self.last_update_label.get_parent().set_visible(False)

        # Disk usage
        self.set_disk_usage()

        # Synopsis
        self.synopsis_label.set_markup('-')
        if manga.synopsis:
            synopsis = manga.synopsis
            if manga.server.donate_url:
                synopsis = f'{synopsis}\n\n<a href="{manga.server.donate_url}">{_("Donate")}</a>'

            self.synopsis_label.set_markup(synopsis)  # can failed with a warning: parsing markup error

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
