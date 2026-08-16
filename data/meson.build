# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

i18n = import('i18n')
gnome = import('gnome')

#
# .desktop file
#
desktop_conf = configuration_data()
desktop_conf.set('bindir', join_paths(prefix, bindir))
desktop_conf.set('prettyname', prettyname)
# .desktop comment now hardcoded for better i18n support
desktop_conf.set('description', description)
desktop_conf.set('appid', app_id)
desktop_conf.set('projectname', meson.project_name())

desktop_file = configure_file(
    input: base_id + '.desktop.in',
    output: base_id + '.desktop.i18n.in',
    configuration: desktop_conf
)

# Merges translations
i18n.merge_file(
    input: desktop_file,
    output: app_id + '.desktop',
    po_dir: '../po',
    type: 'desktop',
    install: true,
    install_dir: join_paths(datadir, 'applications')
)

# Validating the .desktop file
desktop_file_validate = find_program('desktop-file-validate', required:false)
if desktop_file_validate.found()
test (
    'Validate desktop file',
    desktop_file_validate,
    args: join_paths(meson.current_build_dir (), app_id + '.desktop')
)
endif

#
# Dependencies
#
dependency('gobject-introspection-1.0')
dependency('glib-2.0')
dependency('gdk-pixbuf-2.0', version: '>=2.44.3')
dependency('gtk4', version: '>=4.18')
dependency('gtksourceview-5', version: '>=5.20')
dependency('libadwaita-1', version: '>=1.8')

#
# gschema XML file
#
gschema_conf = configuration_data()
gschema_conf.set('apppath', app_id_aspath)
gschema_conf.set('appid', app_id)
gschema_conf.set('projectname', meson.project_name())

configure_file(
    input: base_id + '.gschema.xml.in',
    output: app_id + '.gschema.xml',
    configuration: gschema_conf,
    install: true,
    install_dir: join_paths(datadir, 'glib-2.0/schemas'),
)

# Validating schemas
compile_schemas = find_program('glib-compile-schemas', required: false)
if compile_schemas.found()
    test('Validate schema file', compile_schemas,
        args: ['--strict', '--dry-run', meson.current_source_dir()]
    )
endif

subdir('ui')
subdir('icons')

#
# metainfo XML file
#
message('Merge translations of metainfo XML file')
conf = configuration_data()
conf.set('app_id', app_id)
conf.set('projectname', meson.project_name())
conf.set('prettyname', prettyname)
conf.set('authorfullname', authorfullname)
conf.set('authoremail', authoremail)
conf.set('license', meson.project_license())
conf.set('website', website)
conf.set('gitrepo', gitrepo)
metainfo_file = i18n.merge_file(
  input: configure_file(
    input: '@0@.metainfo.xml.in.in'.format(base_id),
    output: '@0@.metainfo.xml.in'.format(base_id),
    configuration: conf
  ),
  output: '@0@.metainfo.xml'.format(app_id),
  po_dir: '../po',
  install: true,
  install_dir: join_paths(datadir, 'metainfo')
)

appstreamcli = find_program('appstreamcli', required: false)
if appstreamcli.found()
    test (
        'Validate metainfo file',
        appstreamcli,
        args: ['validate', '--no-net', '--explain', metainfo_file],
        workdir: meson.current_build_dir()
    )
endif

#
# Convert Blueprint templates files
#
message('Convert Blueprint templates into XML')
blueprints = custom_target('blueprints',
    input: files(
        'ui/application_window.blp',
        'ui/card.blp',
        'ui/card_chapters_list_row.blp',
        'ui/card_tracking.blp',
        'ui/card_tracking_search.blp',
        'ui/categories_editor.blp',
        'ui/download_manager.blp',
        'ui/explorer_search.blp',
        'ui/explorer_servers.blp',
        'ui/history.blp',
        'ui/library.blp',
        'ui/library_compact_flowbox_child.blp',
        'ui/library_flowbox_child.blp',
        'ui/preferences.blp',
        'ui/preferences_server_params.blp',
        'ui/preferences_servers_languages.blp',
        'ui/preferences_servers_settings.blp',
        'ui/reader.blp',
        'ui/reader_settings.blp',
        'ui/shortcuts.blp',
        'ui/support.blp',
        'ui/webview.blp',
    ),
    output: '.',
    command: [find_program('blueprint-compiler'), 'batch-compile', '--minify', '@OUTPUT@', '@CURRENT_SOURCE_DIR@', '@INPUT@'],
)

#
# gresource XML file
#
message('Compile gresource XML file')
conf = configuration_data()
conf.set('app_id', app_id)
app_resources = gnome.compile_resources(app_id,
    configure_file(
        input: base_id + '.gresource.xml.in',
        output: base_id + '.gresource.xml',
        configuration: conf
    ),
    gresource_bundle: true,
    dependencies: blueprints,
    install: true,
    install_dir: pkgdatadir
)

#
# D-Bus service file
#
service_conf = configuration_data()
service_conf.set('appid', app_id)
service_conf.set('projectname', meson.project_name())
service_conf.set('bindir', join_paths(prefix, bindir))
configure_file(
    input: base_id + '.service.in',
    output: app_id + '.service',
    configuration: service_conf,
    install: true,
    install_dir: join_paths(datadir, 'dbus-1/services'),
)
