# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from copy import deepcopy
from gettext import gettext as _

from gi.repository import Adw
from gi.repository import Gtk

from komikku.models import Settings
from komikku.models.keyring import KeyringHelper
from komikku.servers import LANGUAGES
from komikku.servers.utils import get_server_main_id_by_id
from komikku.servers.utils import get_servers_list
from komikku.utils import html_escape


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/preferences_server_params.ui')
class PreferencesServerParamsSupPage(Adw.NavigationPage):
    __gtype_name__ = 'PreferencesServerParamsSubPage'

    headerbar = Gtk.Template.Child('headerbar')
    page = Gtk.Template.Child('page')

    def __init__(self, data):
        Adw.NavigationPage.__init__(self)

        self.data = data
        self.keyring_helper = KeyringHelper()
        self.settings = Settings.get_default()

        self.headerbar.get_title_widget().set_subtitle(data['name'])

        # Populate
        self.add_credentials_form()
        self.add_params_fields()

    def add_credentials_form(self):
        if not self.data['has_login']:
            return

        group = Adw.PreferencesGroup()
        group.set_title(_('User Account'))
        self.page.add(group)

        if self.data['base_url'] is None:
            # Server has a customizable address/base_url (ex. Komga)
            address_entry = Adw.EntryRow(title=_('Address'))
            address_entry.add_prefix(Gtk.Image.new_from_icon_name('network-server-symbolic'))
            group.add(address_entry)
        else:
            address_entry = None

        username_entry = Adw.EntryRow(title=_('Username'))
        username_entry.add_prefix(Gtk.Image.new_from_icon_name('avatar-default-symbolic'))
        group.add(username_entry)

        password_entry = Adw.PasswordEntryRow(title=_('Password'))
        password_entry.add_prefix(Gtk.Image.new_from_icon_name('dialog-password-symbolic'))
        group.add(password_entry)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=12, margin_bottom=12, spacing=12)
        group.add(box)

        plaintext_checkbutton = None
        if self.keyring_helper.is_disabled or not self.keyring_helper.has_recommended_backend:
            label = Gtk.Label(hexpand=True)
            label.set_wrap(True)
            if self.keyring_helper.is_disabled:
                label.add_css_class('dimmed')
                label.set_text(_('System keyring service is disabled. Credential cannot be saved.'))
                box.append(label)
            elif not self.keyring_helper.has_recommended_backend:
                if not self.settings.credentials_storage_plaintext_fallback:
                    plaintext_checkbutton = Gtk.CheckButton.new()
                    label.set_text(_('No keyring backends were found to store credential. Use plaintext storage as fallback.'))
                    plaintext_checkbutton.set_child(label)
                    box.append(plaintext_checkbutton)
                else:
                    label.add_css_class('dimmed')
                    label.set_text(_('No keyring backends were found to store credential. Plaintext storage will be used as fallback.'))
                    box.append(label)

        btn = Gtk.Button()
        btn_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_hbox.set_halign(Gtk.Align.CENTER)
        btn.icon = Gtk.Image(visible=False)
        btn_hbox.append(btn.icon)
        btn_hbox.append(Gtk.Label(label=_('Test')))
        btn.connect(
            'clicked', self.save_credential,
            username_entry, password_entry, address_entry, plaintext_checkbutton
        )
        btn.set_child(btn_hbox)
        box.append(btn)

        credential = self.keyring_helper.get(self.data['main_id'])
        if credential:
            if address_entry is not None:
                address_entry.set_text(credential.address)
            username_entry.set_text(credential.username)
            password_entry.set_text(credential.password)

    def add_params_fields(self):
        defaults = get_server_default_params(self.data)
        if not defaults:
            return

        servers_settings = deepcopy(self.settings.servers_settings)

        if self.data['main_id'] not in servers_settings:
            servers_settings[self.data['main_id']] = {'params': defaults}
        elif 'params' not in servers_settings[self.data['main_id']]:
            servers_settings[self.data['main_id']]['params'] = defaults
        else:
            for key, value in defaults.items():
                if key not in servers_settings[self.data['main_id']]['params']:
                    servers_settings[self.data['main_id']]['params'][key] = value

        def build_select_single(group, param):
            def on_selected(row, _param):
                position = row.get_selected()
                servers_settings[self.data['main_id']]['params'][param['key']] = param['options'][position]['key']
                self.settings.servers_settings = servers_settings

            labels = Gtk.StringList()
            selected_position = 0
            if param['key'] in servers_settings[self.data['main_id']]['params']:
                value = servers_settings[self.data['main_id']]['params'][param['key']]
            else:
                value = param['default']
            for index, option in enumerate(param['options']):
                labels.append(option['name'])
                if option['key'] == value:
                    selected_position = index

            row = Adw.ComboRow(title=param['name'], subtitle=param['description'])
            row.set_use_markup(True)
            row.set_model(labels)
            row.set_selected(selected_position)
            row.connect('notify::selected', on_selected)

            group.add(row)

            return group

        def build_select_multiple(group, param):
            def on_active(row, _param, key):
                if row.get_active():
                    servers_settings[self.data['main_id']]['params'][param['key']].append(key)
                else:
                    servers_settings[self.data['main_id']]['params'][param['key']].remove(key)
                self.settings.servers_settings = servers_settings

            group.set_title(param['name'])
            group.set_description(param['description'])

            for option in param['options']:
                row = Adw.SwitchRow(title=option['name'])
                row.set_use_markup(True)
                row.set_active(option['key'] in servers_settings[self.data['main_id']]['params'].get(param['key'], defaults[param['key']]))
                row.connect('notify::active', on_active, option['key'])

                group.add(row)

            return group

        def build_switch(group, param):
            def on_active(row, _param, key):
                servers_settings[self.data['main_id']]['params'][param['key']] = row.get_active()
                self.settings.servers_settings = servers_settings

            row = Adw.SwitchRow(title=param['name'])
            row.set_use_markup(True)
            row.set_subtitle(param['description'])
            if param['key'] in servers_settings[self.data['main_id']]['params']:
                row.set_active(servers_settings[self.data['main_id']]['params'][param['key']])
            else:
                row.set_active(param['default'])
            row.connect('notify::active', on_active, param['key'])

            group.add(row)

            return group

        for param in self.data['params']:
            group = Adw.PreferencesGroup()

            if param['type'] == 'select':
                if param['value_type'] == 'single':
                    build_select_single(group, param)
                elif param['value_type'] == 'multiple':
                    build_select_multiple(group, param)
                else:
                    raise ValueError('Invalid select value_type')  # noqa: TC003
            elif param['type'] == 'checkbox':
                build_switch(group, param)
            else:
                raise ValueError('Invalid param type')  # noqa: TC003

            self.page.add(group)

        # Add some filters (include_in_settings key == True)
        # Allow to define default values for server filters in Explorer (search)
        # and to configure the server's behavior
        for param in self.data['filters']:
            if not param.get('include_in_settings'):
                continue

            group = Adw.PreferencesGroup()

            if param['type'] == 'select':
                if param['value_type'] == 'single':
                    build_select_single(group, param)
                elif param['value_type'] == 'multiple':
                    build_select_multiple(group, param)
                else:
                    raise ValueError('Invalid select value_type')  # noqa: TC003
            elif param['type'] == 'checkbox':
                build_switch(group, param)
            else:
                raise ValueError('Invalid param type')  # noqa: TC003

            self.page.add(group)

    def save_credential(self, button, username_entry, password_entry, address_entry, plaintext_checkbutton):
        class_ = getattr(self.data['module'], self.data['main_id'].capitalize())

        username = username_entry.get_text()
        password = password_entry.get_text()
        if address_entry is not None:
            address = address_entry.get_text().strip()
            if not address.startswith(('http://', 'https://')):
                return

            server = class_(username=username, password=password, address=address)
        else:
            address = None
            server = class_(username=username, password=password)

        button.icon.set_visible(True)
        if server.logged_in:
            button.icon.set_from_icon_name('checkmark-symbolic')
            if self.keyring_helper.is_disabled or plaintext_checkbutton is not None and not plaintext_checkbutton.get_active():
                return

            if plaintext_checkbutton is not None and plaintext_checkbutton.get_active():
                # Save user agrees to save credentials in plaintext
                self.parent.credentials_storage_plaintext_fallback_switch.set_active(True)

            self.keyring_helper.store(self.data['main_id'], username, password, address)
        else:
            button.icon.set_from_icon_name('computer-fail-symbolic')


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/preferences_servers_languages.ui')
class PreferencesServersLanguagesSubPage(Adw.NavigationPage):
    __gtype_name__ = 'PreferencesServersLanguagesSubPage'

    group = Gtk.Template.Child('group')

    def __init__(self, parent):
        Adw.NavigationPage.__init__(self)

        self.parent = parent
        self.window = self.parent.window
        self.settings = Settings.get_default()

    def clear(self):
        row = self.group.get_row(0)
        while row:
            next_row = row.get_next_sibling()
            self.group.remove(row)
            row = next_row

    def on_language_activated(self, switchrow, _gparam, code):
        if switchrow.get_active():
            self.settings.add_servers_language(code)
        else:
            self.settings.remove_servers_language(code)

        # Update Explorer servers page
        if self.window.explorer.servers_page in self.window.navigationview.get_navigation_stack():
            self.window.explorer.servers_page.populate()

    def populate(self, *args):
        self.clear()

        servers_languages = self.settings.servers_languages

        for code, language in LANGUAGES.items():
            switchrow = Adw.SwitchRow()
            switchrow.set_title(language)
            switchrow.set_active(code in servers_languages)
            switchrow.connect('notify::active', self.on_language_activated, code)

            self.group.add(switchrow)

        self.parent.push_subpage(self)


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/preferences_servers_settings.ui')
class PreferencesServersSettingsSubPage(Adw.NavigationPage):
    __gtype_name__ = 'PreferencesServersSettingsSubPage'

    group = Gtk.Template.Child('group')

    def __init__(self, parent):
        Adw.NavigationPage.__init__(self)

        self.parent = parent
        self.window = self.parent.window
        self.settings = Settings.get_default()

    def clear(self):
        row = self.group.get_row(0)
        while row:
            next_row = row.get_next_sibling()
            self.group.remove(row)
            row = next_row

    def on_server_activated(self, row, _gparam, server_main_id):
        if isinstance(row, Adw.ExpanderRow):
            self.settings.toggle_server(server_main_id, row.get_enable_expansion())
        else:
            self.settings.toggle_server(server_main_id, row.get_active())

        # Update explorer servers page
        if self.window.explorer.servers_page in self.window.navigationview.get_navigation_stack():
            self.window.explorer.servers_page.populate()

    def on_server_language_activated(self, switch_button, _gparam, server_main_id, lang):
        self.settings.toggle_server_lang(server_main_id, lang, switch_button.get_active())

        # Update explorer servers page
        if self.window.explorer.servers_page in self.window.navigationview.get_navigation_stack():
            self.window.explorer.servers_page.populate()

    def populate(self, *args):
        settings = self.settings.servers_settings
        languages = self.settings.servers_languages

        self.clear()

        servers = get_servers_list(order_by=('name', 'lang'))
        self.window.application.logger.info('{0} servers found'.format(len(servers)))

        servers_data = {}
        for server_data in servers:
            main_id = get_server_main_id_by_id(server_data['id'])

            if main_id not in servers_data:
                servers_data[main_id] = dict(
                    main_id=main_id,
                    name=server_data['name'],
                    description=server_data['description'],
                    module=server_data['module'],
                    base_url=server_data['base_url'],
                    has_login=server_data['has_login'],
                    is_nsfw=server_data['is_nsfw'],
                    is_nsfw_only=server_data['is_nsfw_only'],
                    filters=server_data['filters'],
                    params=server_data['params'],
                    langs=[],
                    langs_enabled=[],
                )

            if server_data['lang']:
                servers_data[main_id]['langs'].append(server_data['lang'])
                if not languages or server_data['lang'] in languages:
                    servers_data[main_id]['langs_enabled'].append(server_data['lang'])

        for server_main_id, server_data in servers_data.items():
            if server_data['langs'] and not server_data['langs_enabled']:
                continue

            server_settings = settings.get(server_main_id)

            server_allowed = not server_data['is_nsfw'] or (server_data['is_nsfw'] and self.settings.nsfw_content)
            server_allowed &= not server_data['is_nsfw_only'] or (server_data['is_nsfw_only'] and self.settings.nsfw_only_content)
            server_enabled = server_settings is None or server_settings.get('enabled', True)

            if len(server_data['langs_enabled']) > 1:
                vbox = Gtk.Box(
                    orientation=Gtk.Orientation.VERTICAL,
                    margin_start=12, margin_top=6, margin_end=12, margin_bottom=6,
                    spacing=12
                )

                row = Adw.ExpanderRow()
                row.set_title(html_escape(server_data['name']))
                if server_data['is_nsfw'] or server_data['is_nsfw_only']:
                    row.set_subtitle(_('18+'))
                row.set_enable_expansion(server_enabled)
                row.set_sensitive(server_allowed)
                row.connect('notify::enable-expansion', self.on_server_activated, server_main_id)
                row.add_row(vbox)

                for lang in server_data['langs_enabled']:
                    lang_enabled = server_settings is None or server_settings.get('langs', {}).get(lang, True)

                    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, margin_top=6, margin_bottom=6, spacing=12)

                    label = Gtk.Label(label=LANGUAGES[lang], xalign=0, hexpand=True)
                    hbox.append(label)

                    switch = Gtk.Switch.new()
                    switch.set_active(lang_enabled)
                    switch.connect('notify::active', self.on_server_language_activated, server_main_id, lang)
                    hbox.append(switch)

                    vbox.append(hbox)

                if server_data['params'] or server_data['has_login']:
                    params_btn = Gtk.Button(icon_name='settings-symbolic', valign=Gtk.Align.CENTER)
                    params_btn.add_css_class('circular')
                    params_btn.props.margin_end = 33
                    params_btn.connect('clicked', self.push_server_params_subpage, server_data)
                    row.add_suffix(params_btn)

                self.group.add(row)
            else:
                if not server_data['langs_enabled']:
                    # Server has no languages (Local for ex.)
                    # Display it only if it has login or parameters
                    if not server_data['params'] and not server_data['has_login']:
                        continue

                    lang = None
                    lang_enabled = True
                else:
                    lang = server_data['langs_enabled'][0]
                    lang_enabled = server_settings is None or server_settings.get('langs', {}).get(lang, True)

                row = Adw.ActionRow()
                row.set_sensitive(server_allowed)
                row.set_title(html_escape(server_data['name']))
                if lang:
                    subtitle = [LANGUAGES[lang]]
                elif server_data['description']:
                    subtitle = [server_data['description']]
                else:
                    subtitle = []
                if server_data['is_nsfw'] or server_data['is_nsfw_only']:
                    subtitle.append(_('18+'))
                if subtitle:
                    row.set_subtitle(' · '.join(subtitle))

                if server_data['params'] or server_data['has_login']:
                    params_btn = Gtk.Button(icon_name='settings-symbolic', valign=Gtk.Align.CENTER)
                    params_btn.add_css_class('circular')
                    params_btn.props.margin_end = 6
                    params_btn.connect('clicked', self.push_server_params_subpage, server_data)
                    row.add_suffix(params_btn)

                switch = Gtk.Switch(valign=Gtk.Align.CENTER)
                switch.set_active(server_enabled and server_allowed and lang_enabled)
                row.add_suffix(switch)
                row.set_activatable_widget(switch)

                if len(server_data['langs']) > 1:
                    switch.connect('notify::active', self.on_server_language_activated, server_main_id, lang)
                else:
                    switch.connect('notify::active', self.on_server_activated, server_main_id)

                self.group.add(row)

        self.parent.push_subpage(self)

    def push_server_params_subpage(self, _btn, data):
        self.parent.push_subpage(PreferencesServerParamsSupPage(data))


def get_server_default_params(data):
    params = {}

    if not data['params'] and not data['filters']:
        return params

    for param in data['params']:
        if param['type'] == 'select' and param['value_type'] == 'multiple':
            params[param['key']] = [option['key'] for option in param['options'] if option['default']]
        else:
            params[param['key']] = param['default']

    # Add default values of filters that are included in server settings
    for param in data['filters']:
        if not param.get('include_in_settings'):
            continue

        if param['type'] == 'select' and param['value_type'] == 'multiple':
            params[param['key']] = [option['key'] for option in param['options'] if option['default']]
        else:
            params[param['key']] = param['default']

    return params
