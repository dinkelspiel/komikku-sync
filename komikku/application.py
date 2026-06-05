# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from collections import deque
import datetime
from gettext import gettext as _
import gi
import logging
import os
import sys
import threading
import urllib.parse

gi.require_version('Adw', '1')
gi.require_version('Gtk', '4.0')

from gi.repository import Adw
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk

from komikku.card import CardPage
from komikku.consts import CREDITS
from komikku.consts import PROGRESSBAR_THEMES
from komikku.consts import RELEASE_NOTES
from komikku.categories_editor import CategoriesEditorPage
from komikku.debug_info import DebugInfo
from komikku.downloader import Downloader
from komikku.downloader import DownloadManagerPage
from komikku.explorer import Explorer
from komikku.history import HistoryPage
from komikku.library import LibraryPage
from komikku.models import backup_db
from komikku.models import init_db
from komikku.models import Settings
from komikku.models.database import clear_cached_data
from komikku.preferences import PreferencesDialog
from komikku.reader import ReaderPage
from komikku.servers import init_servers_modules
from komikku.servers import install_servers_modules_from_repo
from komikku.servers.utils import get_allowed_servers_list
from komikku.support import SupportPage
from komikku.trackers import Trackers
from komikku.updater import Updater
from komikku.utils import random_palette
from komikku.webview import WebviewPage

BANNER = """
██╗  ██╗ ██████╗ ███╗   ███╗██╗██╗  ██╗██╗  ██╗██╗   ██╗
██║ ██╔╝██╔═══██╗████╗ ████║██║██║ ██╔╝██║ ██╔╝██║   ██║
█████╔╝ ██║   ██║██╔████╔██║██║█████╔╝ █████╔╝ ██║   ██║
██╔═██╗ ██║   ██║██║╚██╔╝██║██║██╔═██╗ ██╔═██╗ ██║   ██║
██║  ██╗╚██████╔╝██║ ╚═╝ ██║██║██║  ██╗██║  ██╗╚██████╔╝
╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝"""


class Application(Adw.Application):
    application_id = None
    author = None
    description = None
    gitrepo = None
    profile = None
    version = None

    logger = None

    def __init__(self):
        super().__init__(application_id=self.application_id, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

        self.window = None

        self.add_main_option_entries([])
        self.set_resource_base_path('/info/febvre/Komikku')
        GLib.set_application_name('Komikku')

        logging.basicConfig(
            format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', datefmt='%d-%m-%y %H:%M:%S',
            level=logging.DEBUG if self.profile == 'development' else logging.INFO
        )
        self.logger = logging.getLogger('komikku')

        print(BANNER)
        print(f'v{self.version} — {self.description}\n\n{self.gitrepo}\n')

    def do_activate(self):
        # We only allow a single window and raise any existing ones
        if not self.window:
            self.window = ApplicationWindow(application=self, title='Komikku', icon_name=self.application_id)

        self.window.do_present()

    def do_command_line(self, command_line):
        self.do_activate()

        args = command_line.get_arguments()
        urls = args[1:]
        if not urls:
            return 0

        if len(urls) > 1:
            msg = _('Multiple URLs not supported')
            self.logger.warning(msg)
            self.window.add_notification(msg)

        url = urls[0]
        servers = []
        for data in get_allowed_servers_list(Settings.get_default()):
            server_class = getattr(data['module'], data['class_name'])
            if not server_class.base_url or not url.startswith(server_class.base_url):
                continue

            if initial_data := server_class.get_manga_initial_data_from_url(url):
                data['manga_initial_data'] = initial_data
                servers.append(data)

        if not servers:
            msg = _('Invalid URL {}, not handled by any server.').format(url)
            self.logger.info(msg)
            self.window.add_notification(msg)
        else:
            self.window.explorer.show(servers=servers)

        return 0

    def do_startup(self):
        Adw.Application.do_startup(self)

        init_db()
        init_servers_modules(Settings.get_default().servers_external_modules)


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/application_window.ui')
class ApplicationWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'ApplicationWindow'

    maximized_state = False
    network_available = False
    last_navigation_action = None
    servers_external_modules_update_at_startup_done = False

    overlay = Gtk.Template.Child('overlay')
    navigationview = Gtk.Template.Child('navigationview')
    breakpoint = Gtk.Template.Child('breakpoint')
    banner = Gtk.Template.Child('banner')
    notification_label = Gtk.Template.Child('notification_label')
    notification_revealer = Gtk.Template.Child('notification_revealer')
    pool_to_update_revealer = Gtk.Template.Child('pool_to_update_revealer')
    pool_to_update_spinner = Gtk.Template.Child('pool_to_update_spinner')

    notification_active = False
    notification_queue = deque()
    notification_timer = None

    servers_bug_report_lock = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.application = kwargs['application']

        self._night_light_handler_id = 0
        self._night_light_proxy = None

        self.builder = Gtk.Builder()
        self.builder.add_from_resource('/info/febvre/Komikku/ui/menu/main.xml')

        self.css_provider = Gtk.CssProvider.new()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.css_rules = {}

        self.activity_indicator = Adw.Spinner(
            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, width_request=48, height_request=48, visible=False
        )
        self.overlay.add_overlay(self.activity_indicator)

        self.downloader = Downloader(self)
        self.trackers = Trackers(self)
        self.updater = Updater(self)

        self.assemble_window()
        self.add_accelerators()
        self.add_actions()

        Gio.NetworkMonitor.get_default().connect('network-changed', self.on_network_status_changed)
        # Non-portal implementations of Gio.NetworkMonitor (app not running under Flatpak) don't actually change the value
        # unless the network state actually changes
        Gio.NetworkMonitor.get_default().emit('network-changed', None)

    @property
    def page(self):
        return self.navigationview.get_visible_page().props.tag

    @property
    def previous_page(self):
        previous_page = self.navigationview.get_previous_page(self.navigationview.get_visible_page())
        return previous_page.props.tag if previous_page else None

    @property
    def monitor(self):
        return self.get_display().get_monitor_at_surface(self.get_native().get_surface())

    def add_accelerators(self):
        self.application.set_accels_for_action('app.add', ['<Primary>plus'])
        self.application.set_accels_for_action('app.enter-search-mode', ['<Primary>f'])
        self.application.set_accels_for_action('app.fullscreen', ['F11'])
        self.application.set_accels_for_action('app.select-all', ['<Primary>a'])
        self.application.set_accels_for_action('app.preferences', ['<Primary>comma'])
        self.application.set_accels_for_action('app.shortcuts', ['<Primary>question'])
        self.application.set_accels_for_action('app.quit', ['<Primary>q', '<Primary>w'])

        self.library.add_accelerators()
        self.reader.add_accelerators()

    def add_actions(self):
        about_action = Gio.SimpleAction.new('about', None)
        about_action.connect('activate', self.on_about_menu_clicked)
        self.application.add_action(about_action)

        enter_search_mode_action = Gio.SimpleAction.new('enter-search-mode', None)
        enter_search_mode_action.connect('activate', self.enter_search_mode)
        self.application.add_action(enter_search_mode_action)

        fullscreen_action = Gio.SimpleAction.new('fullscreen', None)
        fullscreen_action.connect('activate', self.toggle_fullscreen)
        self.application.add_action(fullscreen_action)

        self.select_all_action = Gio.SimpleAction.new('select-all', None)
        self.select_all_action.connect('activate', self.select_all)
        self.application.add_action(self.select_all_action)

        preferences_action = Gio.SimpleAction.new('preferences', None)
        preferences_action.connect('activate', self.on_preferences_menu_clicked)
        self.application.add_action(preferences_action)

        shortcuts_action = Gio.SimpleAction.new('shortcuts', None)
        shortcuts_action.connect('activate', self.on_shortcuts_menu_clicked)
        self.application.add_action(shortcuts_action)

        support_action = Gio.SimpleAction.new('support', None)
        support_action.connect('activate', self.open_support)
        self.application.add_action(support_action)

        quit_action = Gio.SimpleAction.new('quit', None)
        quit_action.connect('activate', self.quit)
        self.application.add_action(quit_action)

        self.explorer.search_page.add_actions()
        self.library.add_actions()
        self.card.add_actions()
        self.reader.add_actions()
        self.download_manager.add_actions()

    def add_notification(self, message, timeout=5, priority=0):
        # We use a custom in-app notification solution (Gtk.Revealer)
        # until Adw.ToastOverlay/Adw.Toast is fixed
        # see https://gitlab.gnome.org/GNOME/libadwaita/-/issues/440

        item = {
            'message': message,
            'timeout': timeout,
        }

        if priority == 1:
            self.notification_queue.append(item)
        else:
            self.notification_queue.appendleft(item)

        GLib.idle_add(self.show_notification)

    def assemble_window(self):
        # Restore window previous state (width/height and maximized) or use default
        self.set_default_size(*Settings.get_default().window_size)
        if Settings.get_default().window_maximized_state:
            self.maximize()

        self.set_size_request(360, 288)

        # Window
        self.connect('notify::default-width', self.on_resize)
        self.connect('notify::default-height', self.on_resize)
        self.connect('notify::fullscreened', self.on_resize)
        self.connect('close-request', self.quit)

        self.navigationview.connect('popped', self.on_navigation_popped)
        self.navigationview.connect('pushed', self.on_navigation_pushed)

        self.controller_key = Gtk.EventControllerKey.new()
        self.controller_key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.add_controller(self.controller_key)

        self.gesture_click = Gtk.GestureClick.new()
        self.gesture_click.set_button(0)
        self.gesture_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.add_controller(self.gesture_click)

        self.banner.connect('button-clicked', self.on_banner_button_clicked)

        # Init pages
        self.library = LibraryPage(self)
        self.card = CardPage(self)
        self.reader = ReaderPage(self)
        self.categories_editor = CategoriesEditorPage(self)
        self.download_manager = DownloadManagerPage(self)
        self.explorer = Explorer(self)
        self.history = HistoryPage(self)
        self.support = SupportPage(self)
        self.webview = WebviewPage(self)

        # Init dialogs
        self.preferences = PreferencesDialog(self)

        if self.application.profile in ('beta', 'development'):
            self.add_css_class('devel')

        # Theme (light or dark) and accent colors
        self.init_theme()
        self.init_progressbar_theme()
        self.init_accent_colors()
        Adw.StyleManager.get_default().connect('notify::accent-color', lambda _sm, _p: self.init_accent_colors())

        GLib.idle_add(self.library.populate)

    def do_present(self):
        self.present()

        # Detect maximized/unmaximized state changes
        self.get_native().get_surface().connect('notify::state', self.on_state_changed)

    def enter_search_mode(self, _action, _param):
        if self.page == 'library':
            searchbar = self.library.searchbar
        elif self.page == 'explorer.servers':
            searchbar = self.explorer.servers_page.searchbar
        elif self.page == 'history':
            searchbar = self.history.searchbar

        searchbar.set_search_mode(not searchbar.get_search_mode())

    def hide_notification(self):
        self.notification_active = False
        self.notification_revealer.set_reveal_child(False)

        GLib.idle_add(self.show_notification)

    def init_accent_colors(self):
        if Adw.StyleManager.get_default().get_system_supports_accent_colors() and Settings.get_default().system_accent_colors:
            self.css_rules['accent-colors'] = ''
        else:
            self.css_rules['accent-colors'] = """
                :root {
                    --accent-bg-color: var(--red-1);
                    --accent-color: oklab(from var(--accent-bg-color) var(--standalone-color-oklab));
                }
            """

        self.css_provider.load_from_string('\n'.join(self.css_rules.values()))

    def init_progressbar_theme(self):
        theme = Settings.get_default().progressbar_theme

        if theme == 'accent-color':
            self.css_rules['progressbar-theme'] = ''
        else:
            if theme == 'random':
                colors = random_palette(PROGRESSBAR_THEMES[theme]['lenght'])
            else:
                colors = PROGRESSBAR_THEMES[theme]['colors']

            lg_colors = []
            step = 100 / len(colors)
            for index, color in enumerate(colors):
                lg_colors.append(f'{color} {round(step * index, 2)}% {round(step * (index + 1), 2)}%')

            self.css_rules['progressbar-theme'] = f"""
                progressbar > trough > progress {{
                    background: linear-gradient(
                        90deg,
                        {',\n\t'.join(lg_colors)}
                    );
                }}
            """  # noqa

        self.css_provider.load_from_string('\n'.join(self.css_rules.values()))

    def init_theme(self):
        def set_color_scheme():
            if ((self._night_light_proxy.get_cached_property('NightLightActive') and Settings.get_default().night_light)
                    or Settings.get_default().color_scheme == 'dark'):
                color_scheme = Adw.ColorScheme.FORCE_DARK
            elif Settings.get_default().color_scheme == 'light':
                color_scheme = Adw.ColorScheme.FORCE_LIGHT
            else:
                color_scheme = Adw.ColorScheme.DEFAULT

            Adw.StyleManager.get_default().set_color_scheme(color_scheme)

        if not self._night_light_proxy:
            # Watch night light changes
            self._night_light_proxy = Gio.DBusProxy.new_sync(
                Gio.bus_get_sync(Gio.BusType.SESSION, None),
                Gio.DBusProxyFlags.NONE,
                None,
                'org.gnome.SettingsDaemon.Color',
                '/org/gnome/SettingsDaemon/Color',
                'org.gnome.SettingsDaemon.Color',
                None
            )

            def property_changed(_proxy, changed_properties, _invalidated_properties):
                properties = changed_properties.unpack()
                if 'NightLightActive' in properties:
                    set_color_scheme()

            self._night_light_handler_id = self._night_light_proxy.connect('g-properties-changed', property_changed)

        set_color_scheme()

    def install_servers_modules(self):
        def run():
            res, status = install_servers_modules_from_repo(self.application.version)
            GLib.idle_add(complete, res, status)

        def complete(res, status):
            if res is True:
                if status == 'updated':
                    self.restart(_('Servers modules have been updated'))

            elif res is False:
                if status == 'unchanged':
                    self.application.logger.info('No servers modules updates')
                elif status == 'forbidden':
                    self.open_dialog(
                        _('External Servers Modules Update'),
                        body=_('Updating of external server modules is temporarily suspended, as changes are currently making them incompatible with the current version of the application. Please update it if a more recent version exists.'),
                        cancel_label=_('Close'),
                    )
                    self.application.logger.info('Failed to updates servers modules: incompatible app version')

            else:
                self.application.logger.info('Failed to update servers modules')

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()

    def on_about_menu_clicked(self, _action, _param):
        dialog = Adw.AboutDialog.new_from_appdata('/info/febvre/Komikku/metainfo.xml', self.application.version)

        dialog.set_copyright(f'© 2019-{datetime.date.today().year} {self.application.author} et al.')
        dialog.set_comments(_("""A manga, webtoons and comics reader

👉 Never forget, you can support the authors
by buying the official comics when they are
available in your region/language."""))
        dialog.set_artists(CREDITS['artists'])
        dialog.set_designers(CREDITS['designers'])
        dialog.set_developers(CREDITS['developers'])
        dialog.set_translator_credits('\n'.join(CREDITS['translators']))
        dialog.add_acknowledgement_section(_('Supporters'), CREDITS['supporters'])
        dialog.set_support_url('https://matrix.to/#/#komikku-gnome:matrix.org')
        dialog.add_link(_('Join Chat'), 'https://matrix.to/#/#komikku-gnome:matrix.org')

        # Override release notes
        dialog.set_release_notes(RELEASE_NOTES)

        debug_info = DebugInfo(self.application)
        dialog.set_debug_info_filename(f'Komikku-debug-info-{self.application.version}.txt')
        dialog.set_debug_info(debug_info.generate())

        dialog.present(self)

    def on_banner_button_clicked(self, _banner):
        self.banner.props.revealed = False

    def on_navigation_popped(self, _nav, _page):
        self.last_navigation_action = 'pop'

        self.activity_indicator.set_visible(False)
        self.banner.props.revealed = False

    def on_navigation_pushed(self, _nav):
        self.last_navigation_action = 'push'

        self.banner.props.revealed = False

    def on_network_status_changed(self, monitor, _connected):
        connectivity = monitor.get_connectivity()
        if _connected != self.network_available:
            self.application.logger.warning('Connection status: {}'.format(connectivity))
        self.network_available = connectivity == Gio.NetworkConnectivity.FULL

        if self.network_available:
            # Install external servers modules
            if Settings.get_default().servers_external_modules and not self.servers_external_modules_update_at_startup_done:
                self.servers_external_modules_update_at_startup_done = True
                self.install_servers_modules()

            # Automatically update library at startup
            if Settings.get_default().update_at_startup and not self.updater.update_at_startup_done:
                self.updater.update_library(startup=True)

            # Start Downloader
            if Settings.get_default().downloader_state:
                self.downloader.start()

            # Sync trackers: offline read progress
            self.trackers.sync()
        else:
            # Stop Updater
            self.updater.stop()

            # Stop Downloader
            if Settings.get_default().downloader_state:
                self.downloader.stop()

    def on_preferences_menu_clicked(self, _action, _param):
        self.preferences.show()

    def on_resize(self, _window, allocation):
        self.library.on_resize()

    def on_shortcuts_menu_clicked(self, _action, _param):
        builder = Gtk.Builder()
        builder.add_from_resource('/info/febvre/Komikku/ui/shortcuts.ui')

        dialog = builder.get_object('shortcuts_dialog')
        dialog.present(self)

    def on_state_changed(self, surface, _param):
        # Detect maximized/unmaximized
        # Only reliable method found to detect maximized/unmaximized state changes in both X11 and Wayland
        # Gtk.Window::maximized event is unreliable in X11 because it's emitted too earlier
        maximized_state = surface.props.state & Gdk.ToplevelState.MAXIMIZED == Gdk.ToplevelState.MAXIMIZED

        if self.maximized_state != maximized_state:
            self.maximized_state = maximized_state
            self.library.on_resize()

    def open_dialog(self, heading, body=None, child=None, confirm_label=None, confirm_callback=None, confirm_appearance=None, cancel_label=None, cancel_callback=None):
        def on_response(dialog, response_id):
            if response_id == 'yes':
                confirm_callback()
            elif response_id == 'cancel' and cancel_callback is not None:
                cancel_callback()

        dialog = Adw.AlertDialog.new(heading)
        dialog.set_prefer_wide_layout(True)
        if body:
            dialog.set_body_use_markup(True)
            dialog.set_body(body)
        if child:
            dialog.set_extra_child(child)

        dialog.add_response('cancel', cancel_label or _('Cancel'))
        if confirm_label is not None:
            dialog.add_response('yes', confirm_label)

        dialog.set_close_response('cancel')
        dialog.set_default_response('cancel')
        if confirm_appearance is not None:
            dialog.set_response_appearance('yes', confirm_appearance)

        dialog.connect('response', on_response)
        dialog.present(self)

    def open_server_bug_report_dialog(self, server, context, stack_trace):
        if self.servers_bug_report_lock:
            # Another server issue dialog is already open
            return

        debug_info = DebugInfo(self.application).generate()

        title = urllib.parse.quote_plus(f'[BUG Server] {server.id}')
        uri = f'https://codeberg.org/valos/Komikku/issues/new?title={title}'  # noqa
        body = '\n'.join([
            '# Context',
            f'{context}\n',
            '# Stack Trace',
            '```sh',
            stack_trace.strip(),
            '```\n',
            '# Debug Information',
            '```',
            debug_info,
            '```',
        ])

        def copy_text(_button):
            self.get_clipboard().set(body)
            button.get_child().set_icon_name('checkmark-symbolic')
            dialog.set_response_enabled('yes', True)

        def on_response(_dialog, response_id):
            if response_id == 'yes':
                Gtk.UriLauncher.new(uri=uri).launch()

            self.servers_bug_report_lock = False

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        # Copy text button
        button = Gtk.Button(hexpand=True)
        content_button = Adw.ButtonContent(label=_('Copy Text'), icon_name='edit-copy-symbolic')
        button.set_child(content_button)
        button.connect('clicked', copy_text)
        main_box.append(button)

        # Context
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        label = Gtk.Label(label=_('Context'), xalign=0)
        label.add_css_class('heading')
        box.append(label)

        frame = Gtk.Frame()
        textview = Gtk.TextView(
            editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
            bottom_margin=6, left_margin=12, right_margin=12, top_margin=6
        )
        textview.set_css_classes(['body', 'small'])
        buffer = textview.get_buffer()
        buffer.set_text(context)
        frame.set_child(textview)
        box.append(frame)

        main_box.append(box)

        # Stack trace
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        label = Gtk.Label(label=_('Stack Trace'), xalign=0)
        label.add_css_class('heading')
        box.append(label)

        frame = Gtk.Frame()
        scrolledwindow = Gtk.ScrolledWindow()
        scrolledwindow.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        textview = Gtk.TextView(
            editable=False, bottom_margin=6, left_margin=12, right_margin=12, top_margin=6
        )
        textview.set_css_classes(['body', 'small'])
        buffer = textview.get_buffer()
        buffer.set_text(stack_trace.strip())
        scrolledwindow.set_child(textview)
        frame.set_child(scrolledwindow)
        box.append(frame)

        main_box.append(box)

        # Debug info
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        label = Gtk.Label(label=_('Debug Information'), xalign=0)
        label.add_css_class('heading')
        box.append(label)

        frame = Gtk.Frame()
        textview = Gtk.TextView(
            editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
            bottom_margin=6, left_margin=12, right_margin=12, top_margin=6
        )
        textview.set_css_classes(['body', 'small'])
        buffer = textview.get_buffer()
        buffer.set_text(debug_info)
        frame.set_child(textview)
        box.append(frame)

        main_box.append(box)

        # Dialog
        self.servers_bug_report_lock = True

        dialog = Adw.AlertDialog.new(_('Server Error'))
        dialog.set_body(_('You have encountered a problem with a server (it has been updated or an unexpected case has arisen). Here is a pre-formatted text that you can copy and paste when filling out the issue.'))
        dialog.set_prefer_wide_layout(True)
        dialog.set_extra_child(main_box)

        dialog.add_response('cancel', _('Close'))
        dialog.add_response('yes', _('Create an Issue'))

        dialog.set_close_response('cancel')
        dialog.set_default_response('cancel')
        dialog.set_response_appearance('yes', Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_enabled('yes', False)

        dialog.connect('response', on_response)
        dialog.present(self)

    def open_support(self, _action, _param):
        self.support.show()

    def quit(self, *args, force=False):
        def confirm_callback():
            self.downloader.stop()
            self.updater.stop()

            GLib.idle_add(do_quit)

        def do_quit():
            if self.downloader.running or self.updater.running:
                return GLib.SOURCE_CONTINUE

            self.save_window_size()
            if Settings.get_default().clear_cached_data_on_app_close:
                clear_cached_data()

            backup_db()

            self.application.quit()

        if self.downloader.running or self.updater.running:
            message = [
                _('Are you sure you want to quit?'),
            ]
            if self.downloader.running:
                message.append(_('Some chapters are currently being downloaded.'))
            if self.updater.running:
                message.append(_('Some mangas are currently being updated.'))

            if not force:
                self.open_dialog(
                    _('Quit?'),
                    body='\n'.join(message),
                    confirm_label=_('Quit'),
                    confirm_callback=confirm_callback
                )
            else:
                confirm_callback()
        else:
            do_quit()

        return Gdk.EVENT_STOP

    def restart(self, message):
        def confirm_callback():
            os.execv(sys.argv[0], sys.argv)

        self.open_dialog(
            _('Restart?'),
            body=message,
            confirm_label=_('Restart'),
            confirm_callback=confirm_callback
        )

    def save_window_size(self):
        if self.is_fullscreen():
            return

        Settings.get_default().window_maximized_state = self.is_maximized()

        if not self.is_maximized():
            size = self.get_default_size()
            Settings.get_default().window_size = [size.width, size.height]

    def select_all(self, _action, _param):
        if self.page == 'library':
            self.library.select_all()
        elif self.page == 'card':
            self.card.chapters_list.select_all()
        elif self.page == 'download-manager':
            self.download_manager.select_all()

    def show_banner(self, title, at_bottom=False):
        self.banner.props.title = title
        if not at_bottom:
            self.banner.props.valign = Gtk.Align.START
            self.banner.props.margin_top = self.library.get_child().get_top_bar_height()
        else:
            self.banner.props.valign = Gtk.Align.END
        self.banner.props.revealed = True

    def show_notification(self):
        if len(self.notification_queue) == 0:
            return GLib.SOURCE_REMOVE

        if self.notification_revealer.get_child_revealed() or self.notification_active:
            return GLib.SOURCE_CONTINUE

        self.notification_active = True

        if self.is_fullscreen():
            self.notification_revealer.set_margin_top(0)
        else:
            self.notification_revealer.set_margin_top(self.library.get_child().get_top_bar_height())

        notification = self.notification_queue.pop()
        self.notification_label.set_text(notification['message'])
        self.notification_revealer.set_reveal_child(True)

        self.notification_timer = threading.Timer(notification['timeout'], GLib.idle_add, args=[self.hide_notification])
        self.notification_timer.start()

        return GLib.SOURCE_REMOVE

    def toggle_fullscreen(self, _object, _gparam):
        if self.page != 'reader':
            return

        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()


if __name__ == '__main__':
    app = Application()
    app.run(sys.argv)
