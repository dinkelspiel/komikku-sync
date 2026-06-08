# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _

from gi.repository import Adw
from gi.repository import GLib
from gi.repository import Gtk

from komikku.consts import PROGRESSBAR_THEMES
from komikku.models import Settings
from komikku.models.database import clear_cached_data
from komikku.preferences.servers import PreferencesServersLanguagesSubPage
from komikku.preferences.servers import PreferencesServersSettingsSubPage
from komikku.preferences.trackers import TrackerRow
from komikku.utils import folder_size
from komikku.utils import get_cached_data_dir
from komikku.utils import get_webview_data_dir


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/preferences.ui')
class PreferencesDialog(Adw.PreferencesDialog):
    __gtype_name__ = 'PreferencesDialog'

    support_group = Gtk.Template.Child('support_group')
    support_button = Gtk.Template.Child('support_button')
    support_close_button = Gtk.Template.Child('support_close_button')

    color_scheme_row = Gtk.Template.Child('color_scheme_row')
    night_light_switch = Gtk.Template.Child('night_light_switch')
    system_accent_colors_switch = Gtk.Template.Child('system_accent_colors_switch')
    progressbar_theme_row = Gtk.Template.Child('progressbar_theme_row')
    card_backdrop_method_row = Gtk.Template.Child('card_backdrop_method_row')
    desktop_notifications_switch = Gtk.Template.Child('desktop_notifications_switch')
    tracking_group = Gtk.Template.Child('tracking_group')
    tracking_switch = Gtk.Template.Child('tracking_switch')

    library_display_mode_row = Gtk.Template.Child('library_display_mode_row')
    library_servers_logo_switch = Gtk.Template.Child('library_servers_logo_switch')
    library_badge_unread_chapters_switch = Gtk.Template.Child('library_badge_unread_chapters_switch')
    library_badge_downloaded_chapters_switch = Gtk.Template.Child('library_badge_downloaded_chapters_switch')
    library_badge_recent_chapters_switch = Gtk.Template.Child('library_badge_recent_chapters_switch')
    update_at_startup_switch = Gtk.Template.Child('update_at_startup_switch')
    new_chapters_auto_download_switch = Gtk.Template.Child('new_chapters_auto_download_switch')
    nsfw_content_switch = Gtk.Template.Child('nsfw_content_switch')
    nsfw_only_content_switch = Gtk.Template.Child('nsfw_only_content_switch')
    servers_languages_actionrow = Gtk.Template.Child('servers_languages_actionrow')
    servers_settings_actionrow = Gtk.Template.Child('servers_settings_actionrow')
    long_strip_detection_switch = Gtk.Template.Child('long_strip_detection_switch')

    reading_mode_row = Gtk.Template.Child('reading_mode_row')
    scaling_filter_row = Gtk.Template.Child('scaling_filter_row')
    background_color_row = Gtk.Template.Child('background_color_row')
    page_numbering_switch = Gtk.Template.Child('page_numbering_switch')
    fullscreen_switch = Gtk.Template.Child('fullscreen_switch')
    scaling_row = Gtk.Template.Child('scaling_row')
    landscape_zoom_switch = Gtk.Template.Child('landscape_zoom_switch')
    borders_crop_switch = Gtk.Template.Child('borders_crop_switch')
    webtoon_reading_mode_group_reset_button = Gtk.Template.Child('webtoon_reading_mode_group_reset_button')
    clamp_size_adjustment = Gtk.Template.Child('clamp_size_adjustment')
    scroll_click_percentage_adjustment = Gtk.Template.Child('scroll_click_percentage_adjustment')
    scroll_drag_factor_adjustment = Gtk.Template.Child('scroll_drag_factor_adjustment')

    advanced_banner = Gtk.Template.Child('advanced_banner')
    clear_cached_data_actionrow = Gtk.Template.Child('clear_cached_data_actionrow')
    clear_cached_data_button = Gtk.Template.Child('clear_cached_data_button')
    clear_cached_data_on_app_close_switch = Gtk.Template.Child('clear_cached_data_on_app_close_switch')
    clear_webview_data_actionrow = Gtk.Template.Child('clear_webview_data_actionrow')
    clear_webview_data_button = Gtk.Template.Child('clear_webview_data_button')
    servers_external_modules_switch = Gtk.Template.Child('servers_external_modules_switch')
    servers_bug_report_switch = Gtk.Template.Child('servers_bug_report_switch')
    credentials_storage_plaintext_fallback_switch = Gtk.Template.Child('credentials_storage_plaintext_fallback_switch')
    disable_animations_switch = Gtk.Template.Child('disable_animations_switch')

    def __init__(self, window):
        Adw.PreferencesDialog.__init__(self)

        self.window = window
        self.settings = Settings.get_default()
        self.servers_external_modules_in_use = self.settings.servers_external_modules

        self.support_button.connect('clicked', lambda _btn: self.push_subpage(self.window.support))
        self.support_close_button.connect('clicked', lambda _btn: self.support_group.set_visible(False))

        self.connect('closed', self.on_closed)
        self.advanced_banner.connect('button-clicked', lambda banner: banner.set_revealed(False))

        self.set_config_values()

    def on_background_color_changed(self, row, _gparam):
        index = row.get_selected()

        if index == 0:
            self.settings.background_color = 'white'
        elif index == 1:
            self.settings.background_color = 'black'
        elif index == 2:
            self.settings.background_color = 'gray'
        elif index == 3:
            self.settings.background_color = 'system-style'

    def on_borders_crop_changed(self, switch_button, _gparam):
        self.settings.borders_crop = switch_button.get_active()

    def on_card_backdrop_method_changed(self, row, _gparam):
        index = row.get_selected()

        if index == 0:
            self.settings.card_backdrop_method = 'none'
            self.window.card.remove_backdrop()
        elif index == 1:
            self.settings.card_backdrop_method = 'linear-gradient'
            self.window.card.set_backdrop()
        elif index == 2:
            self.settings.card_backdrop_method = 'blurred-cover'
            self.window.card.set_backdrop()

    def on_closed(self, _dialog):
        # Pop subpage if one is opened when dialog is closed
        self.pop_subpage()
        # Close search if opened
        self.set_search_enabled(False)

    def on_color_scheme_changed(self, row, _gparam):
        index = row.get_selected()

        if index == 0:
            self.settings.color_scheme = 'light'
        elif index == 1:
            self.settings.color_scheme = 'dark'
        elif index == 2:
            self.settings.color_scheme = 'default'

        self.window.init_theme()
        self.window.card.set_backdrop()

    def on_clamp_size_changed(self, adjustment):
        self.settings.clamp_size = int(adjustment.get_value())

    def on_clear_cached_data_clicked(self, _button):
        # Clear cached data of manga not in library
        # If a manga is being read, it must be excluded

        def confirm_callback():
            manga_in_use = None
            if self.window.previous_page in ('card', 'reader') and not self.window.card.manga.in_library:
                manga_in_use = self.window.card.manga

            clear_cached_data(manga_in_use)
            self.update_cached_data_size()

            if self.window.previous_page == 'history':
                self.window.history.populate()

        self.window.open_dialog(
            _('Clear?'),
            body=_('Are you sure you want to clear chapters cache and database?'),
            confirm_label=_('Clear'),
            confirm_callback=confirm_callback,
            confirm_appearance=Adw.ResponseAppearance.DESTRUCTIVE
        )

    def on_clear_cached_data_on_app_close_changed(self, switch_button, _gparam):
        self.settings.clear_cached_data_on_app_close = switch_button.get_active()

    def on_clear_webview_data_clicked(self, _button):
        # Clear WebView data

        def confirm_callback():
            self.window.webview.clear_data(on_clear_data_finished)

        def on_clear_data_finished(success):
            if success:
                self.update_webview_data_size()
            else:
                self.add_toast(Adw.Toast.new(_('Failed to clear WebView data')))

        self.window.open_dialog(
            _('Clear?'),
            body=_('Are you sure you want to clear WebView data (cache, storage, cookies)?'),
            confirm_label=_('Clear'),
            confirm_callback=confirm_callback,
            confirm_appearance=Adw.ResponseAppearance.DESTRUCTIVE
        )

    def on_credentials_storage_plaintext_fallback_changed(self, switch_button, _gparam):
        self.settings.credentials_storage_plaintext_fallback = switch_button.get_active()

    def on_desktop_notifications_changed(self, switch_button, _gparam):
        if switch_button.get_active():
            self.settings.desktop_notifications = True
        else:
            self.settings.desktop_notifications = False

    def on_disable_animations_changed(self, switch_button, _gparam):
        def on_cancel():
            switch_button.set_active(False)

        def on_confirm():
            self.settings.disable_animations = True
            Gtk.Settings.get_default().set_property('gtk-enable-animations', False)

        if switch_button.get_active():
            self.window.open_dialog(
                _('Disable animations?'),
                body=_('Are you sure you want to disable animations?\n\nThe gesture navigation in the reader will not work properly anymore.'),
                confirm_label=_('Disable'),
                confirm_callback=on_confirm,
                confirm_appearance=Adw.ResponseAppearance.DESTRUCTIVE,
                cancel_callback=on_cancel
            )
        elif self.settings.disable_animations:
            self.settings.disable_animations = False
            Gtk.Settings.get_default().set_property('gtk-enable-animations', True)

    def on_fullscreen_changed(self, switch_button, _gparam):
        self.settings.fullscreen = switch_button.get_active()

    def on_landscape_zoom_changed(self, switch_button, _gparam):
        self.settings.landscape_zoom = switch_button.get_active()

    def on_library_badge_changed(self, switch_button, _gparam):
        badges = self.settings.library_badges
        if switch_button.get_active():
            if switch_button._value not in badges:
                badges.append(switch_button._value)
        else:
            if switch_button._value in badges:
                badges.remove(switch_button._value)
        self.settings.library_badges = badges

        GLib.idle_add(self.window.library.populate)

    def on_library_display_mode_changed(self, row, _gparam):
        index = row.get_selected()

        if index == 0:
            self.settings.library_display_mode = 'grid'
        elif index == 1:
            self.settings.library_display_mode = 'grid-compact'

        GLib.idle_add(self.window.library.populate)

    def on_library_servers_logo_changed(self, switch_button, _gparam):
        if switch_button.get_active():
            self.settings.library_servers_logo = True
        else:
            self.settings.library_servers_logo = False

        GLib.idle_add(self.window.library.populate)

    def on_long_strip_detection_changed(self, switch_button, _gparam):
        self.settings.long_strip_detection = switch_button.get_active()

    def on_progressbar_theme_changed(self, row, _gparam):
        self.settings.progressbar_theme = list(PROGRESSBAR_THEMES.keys())[row.get_selected()]

        self.window.init_progressbar_theme()

    def on_new_chapters_auto_download_changed(self, switch_button, _gparam):
        if switch_button.get_active():
            self.settings.new_chapters_auto_download = True
        else:
            self.settings.new_chapters_auto_download = False

    def on_night_light_changed(self, switch_button, _gparam):
        self.settings.night_light = switch_button.get_active()

        self.window.init_theme()

    def on_nsfw_content_changed(self, switch_button, _gparam):
        if switch_button.get_active():
            self.settings.nsfw_content = True
        else:
            self.settings.nsfw_content = False

    def on_nsfw_only_content_changed(self, switch_button, _gparam):
        if switch_button.get_active():
            self.settings.nsfw_only_content = True
        else:
            self.settings.nsfw_only_content = False

    def on_page_numbering_changed(self, switch_button, _gparam):
        self.settings.page_numbering = not switch_button.get_active()

    def on_reading_mode_changed(self, row, _gparam):
        index = row.get_selected()

        if index == 0:
            self.settings.reading_mode = 'right-to-left'
        elif index == 1:
            self.settings.reading_mode = 'left-to-right'
        elif index == 2:
            self.settings.reading_mode = 'vertical'
        elif index == 3:
            self.settings.reading_mode = 'webtoon'

    def on_scaling_changed(self, row, _gparam):
        index = row.get_selected()

        if index == 0:
            self.settings.scaling = 'screen'
        elif index == 1:
            self.settings.scaling = 'width'
        elif index == 2:
            self.settings.scaling = 'height'
        elif index == 3:
            self.settings.scaling = 'original'

    def on_scaling_filter_changed(self, row, _gparam):
        index = row.get_selected()

        if index == 0:
            self.settings.scaling_filter = 'linear'
        elif index == 1:
            self.settings.scaling_filter = 'trilinear'

    def on_scroll_click_percentage_changed(self, adjustment):
        self.settings.scroll_click_percentage = adjustment.get_value()

    def on_scroll_drag_factor_changed(self, adjustment):
        self.settings.scroll_drag_factor = adjustment.get_value()

    def on_servers_bug_report_changed(self, switch_button, _gparam):
        self.settings.servers_bug_report = switch_button.get_active()

    def on_servers_external_modules_changed(self, switch_button, _gparam):
        active = switch_button.get_active()
        self.advanced_banner.set_revealed(active != self.servers_external_modules_in_use)
        self.settings.servers_external_modules = active

    def on_system_accent_colors_changed(self, switch_button, _gparam):
        self.settings.system_accent_colors = switch_button.get_active()

        self.window.init_accent_colors()

    def on_tracking_changed(self, switch_button, _gparam):
        self.settings.tracking = switch_button.get_active()

    def on_update_at_startup_changed(self, switch_button, _gparam):
        if switch_button.get_active():
            self.settings.update_at_startup = True
        else:
            self.settings.update_at_startup = False

    def reset_webtoon_reading_mode_settings(self, _btn):
        self.clamp_size_adjustment.set_value(
            self.settings.get_default_value('clamp-size').get_int32()
        )
        self.scroll_click_percentage_adjustment.set_value(
            self.settings.get_default_value('scroll-click-percentage').get_double()
        )
        self.scroll_drag_factor_adjustment.set_value(
            self.settings.get_default_value('scroll-drag-factor').get_double()
        )

    def set_config_values(self):
        #
        # General
        #

        # Theme
        if not Adw.StyleManager.get_default().get_system_supports_color_schemes():
            # System doesn't support color schemes
            self.color_scheme_row.get_model().remove(2)
            if self.settings.color_scheme == 'default':
                self.settings.color_scheme = 'light'
        self.color_scheme_row.set_selected(self.settings.color_scheme_value)
        self.color_scheme_row.connect('notify::selected', self.on_color_scheme_changed)

        # Night light
        self.night_light_switch.set_active(self.settings.night_light)
        self.night_light_switch.connect('notify::active', self.on_night_light_changed)

        # Use system accent colors
        self.system_accent_colors_switch.set_active(self.settings.system_accent_colors)
        self.system_accent_colors_switch.connect('notify::active', self.on_system_accent_colors_changed)

        # Progress bars theme
        model = Gtk.StringList()
        for _key, theme in PROGRESSBAR_THEMES.items():
            model.append(theme['name'])
        self.progressbar_theme_row.set_model(model)
        self.progressbar_theme_row.set_selected(self.settings.progressbar_theme_value)
        self.progressbar_theme_row.connect('notify::selected', self.on_progressbar_theme_changed)

        progressbar = Gtk.ProgressBar(fraction=1, halign=Gtk.Align.START, margin_top=4)
        self.progressbar_theme_row.get_first_child().get_first_child().get_next_sibling().get_next_sibling().append(progressbar)

        # Card backdrop method
        self.card_backdrop_method_row.set_selected(self.settings.card_backdrop_method_value)
        self.card_backdrop_method_row.connect('notify::selected', self.on_card_backdrop_method_changed)

        # Desktop notifications
        self.desktop_notifications_switch.set_active(self.settings.desktop_notifications)
        self.desktop_notifications_switch.connect('notify::active', self.on_desktop_notifications_changed)

        # Tracking
        self.tracking_switch.set_active(self.settings.tracking)
        self.tracking_switch.connect('notify::active', self.on_tracking_changed)

        for _id, tracker in self.window.trackers.trackers.items():
            row = TrackerRow(self.window, tracker)
            self.tracking_group.add(row)

        #
        # Library
        #

        # Display mode
        self.library_display_mode_row.set_selected(self.settings.library_display_mode_value)
        self.library_display_mode_row.connect('notify::selected', self.on_library_display_mode_changed)

        # Servers logo
        self.library_servers_logo_switch.set_active(self.settings.library_servers_logo)
        self.library_servers_logo_switch.connect('notify::active', self.on_library_servers_logo_changed)

        # Badges
        self.library_badge_unread_chapters_switch.set_active('unread-chapters' in self.settings.library_badges)
        self.library_badge_unread_chapters_switch._value = 'unread-chapters'
        self.library_badge_unread_chapters_switch.connect('notify::active', self.on_library_badge_changed)
        self.library_badge_downloaded_chapters_switch.set_active('downloaded-chapters' in self.settings.library_badges)
        self.library_badge_downloaded_chapters_switch._value = 'downloaded-chapters'
        self.library_badge_downloaded_chapters_switch.connect('notify::active', self.on_library_badge_changed)
        self.library_badge_recent_chapters_switch.set_active('recent-chapters' in self.settings.library_badges)
        self.library_badge_recent_chapters_switch._value = 'recent-chapters'
        self.library_badge_recent_chapters_switch.connect('notify::active', self.on_library_badge_changed)

        # Update manga at startup
        self.update_at_startup_switch.set_active(self.settings.update_at_startup)
        self.update_at_startup_switch.connect('notify::active', self.on_update_at_startup_changed)

        # Auto download new chapters
        self.new_chapters_auto_download_switch.set_active(self.settings.new_chapters_auto_download)
        self.new_chapters_auto_download_switch.connect('notify::active', self.on_new_chapters_auto_download_changed)

        # Servers languages
        self.servers_languages_actionrow.props.activatable = True
        self.servers_languages_subpage = PreferencesServersLanguagesSubPage(self)
        self.servers_languages_actionrow.connect('activated', self.servers_languages_subpage.populate)

        # Servers settings
        self.servers_settings_actionrow.props.activatable = True
        self.servers_settings_subpage = PreferencesServersSettingsSubPage(self)
        self.servers_settings_actionrow.connect('activated', self.servers_settings_subpage.populate)

        # Long strip detection
        self.long_strip_detection_switch.set_active(self.settings.long_strip_detection)
        self.long_strip_detection_switch.connect('notify::active', self.on_long_strip_detection_changed)

        # NSFW content
        self.nsfw_content_switch.set_active(self.settings.nsfw_content)
        self.nsfw_content_switch.connect('notify::active', self.on_nsfw_content_changed)

        # NSFW only content
        self.nsfw_only_content_switch.set_active(self.settings.nsfw_only_content)
        self.nsfw_only_content_switch.connect('notify::active', self.on_nsfw_only_content_changed)

        #
        # Reader
        #

        # Reading mode
        self.reading_mode_row.set_selected(self.settings.reading_mode_value)
        self.reading_mode_row.connect('notify::selected', self.on_reading_mode_changed)

        # Image scaling filter
        self.scaling_filter_row.set_selected(self.settings.scaling_filter_value)
        self.scaling_filter_row.connect('notify::selected', self.on_scaling_filter_changed)

        # Background color
        self.background_color_row.set_selected(self.settings.background_color_value)
        self.background_color_row.connect('notify::selected', self.on_background_color_changed)

        # Page numbering
        self.page_numbering_switch.set_active(not self.settings.page_numbering)
        self.page_numbering_switch.connect('notify::active', self.on_page_numbering_changed)

        # Full screen
        self.fullscreen_switch.set_active(self.settings.fullscreen)
        self.fullscreen_switch.connect('notify::active', self.on_fullscreen_changed)

        #
        # Paged reading modes specific settings
        # Image scaling
        self.scaling_row.set_selected(self.settings.scaling_value)
        self.scaling_row.connect('notify::selected', self.on_scaling_changed)

        # Landscape pages zoom
        self.landscape_zoom_switch.set_active(self.settings.landscape_zoom)
        self.landscape_zoom_switch.connect('notify::active', self.on_landscape_zoom_changed)

        # Borders crop
        self.borders_crop_switch.set_active(self.settings.borders_crop)
        self.borders_crop_switch.connect('notify::active', self.on_borders_crop_changed)

        #
        # Webtoon reading mode specific settings
        # Reset button
        self.webtoon_reading_mode_group_reset_button.connect('clicked', self.reset_webtoon_reading_mode_settings)

        # Pager clamp size
        self.clamp_size_adjustment.set_value(self.settings.clamp_size)
        self.clamp_size_adjustment.connect('value-changed', self.on_clamp_size_changed)

        # Scroll click percentage
        self.scroll_click_percentage_adjustment.set_value(self.settings.scroll_click_percentage)
        self.scroll_click_percentage_adjustment.connect('value-changed', self.on_scroll_click_percentage_changed)

        # Scroll drag factor
        self.scroll_drag_factor_adjustment.set_value(self.settings.scroll_drag_factor)
        self.scroll_drag_factor_adjustment.connect('value-changed', self.on_scroll_drag_factor_changed)

        #
        # Advanced
        #

        # Clear chapters cache and database
        self.clear_cached_data_button.connect('clicked', self.on_clear_cached_data_clicked)

        # Clear chapters cache and database on app close
        self.clear_cached_data_on_app_close_switch.set_active(self.settings.clear_cached_data_on_app_close)
        self.clear_cached_data_on_app_close_switch.connect('notify::active', self.on_clear_cached_data_on_app_close_changed)

        # Clear webview data
        self.clear_webview_data_button.connect('clicked', self.on_clear_webview_data_clicked)

        # Servers external modules
        self.servers_external_modules_switch.set_active(self.settings.servers_external_modules)
        self.servers_external_modules_switch.connect('notify::active', self.on_servers_external_modules_changed)

        # Servers bug report
        self.servers_bug_report_switch.set_active(self.settings.servers_bug_report)
        self.servers_bug_report_switch.connect('notify::active', self.on_servers_bug_report_changed)

        # Credentials storage: allow plaintext as fallback
        self.credentials_storage_plaintext_fallback_switch.set_active(self.settings.credentials_storage_plaintext_fallback)
        self.credentials_storage_plaintext_fallback_switch.connect('notify::active', self.on_credentials_storage_plaintext_fallback_changed)

        # Disable animations
        if Gtk.Settings.get_default().get_property('gtk-enable-animations'):
            Gtk.Settings.get_default().set_property('gtk-enable-animations', not Settings.get_default().disable_animations)
            self.disable_animations_switch.set_active(self.settings.disable_animations)
        else:
            # GTK animations are already disabled (in GNOME Settings for ex.)
            self.disable_animations_switch.get_parent().get_parent().get_parent().set_sensitive(False)
            self.disable_animations_switch.set_active(False)

        self.disable_animations_switch.connect('notify::active', self.on_disable_animations_changed)

    def show(self, transition=True):
        # Update maximum value of clamp size adjustment
        self.clamp_size_adjustment.set_upper(self.window.monitor.props.geometry.width)

        self.update_cached_data_size()
        self.update_webview_data_size()

        self.set_search_enabled(True)
        self.present(self.window)

    def update_cached_data_size(self):
        self.clear_cached_data_actionrow.set_subtitle(folder_size(get_cached_data_dir()) or '-')

    def update_webview_data_size(self):
        size = folder_size(get_webview_data_dir(), exclude='cookies.sqlite')
        self.clear_webview_data_actionrow.set_subtitle(size or '-')
