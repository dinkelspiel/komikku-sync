# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _

from gi.repository import Adw
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GObject
from gi.repository import Gtk

from komikku.consts import BORDERS_CROP_THRESHOLDS
from komikku.models import Settings


class KeyLabelPair(GObject.Object):
    key = GObject.Property(type=str, flags=GObject.ParamFlags.READWRITE, default='')
    label = GObject.Property(type=str, nick='Label', blurb='Label', flags=GObject.ParamFlags.READWRITE, default='')


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/reader_settings.ui')
class ReaderSettingsDialog(Adw.PreferencesDialog):
    __gtype_name__ = 'ReaderSettingsDialog'

    page_filters_group = Gtk.Template.Child('page_filters_group')
    scaling_row = Gtk.Template.Child('scaling_row')
    scaling_filter_row = Gtk.Template.Child('scaling_filter_row')
    background_color_row = Gtk.Template.Child('background_color_row')
    landscape_zoom_switch = Gtk.Template.Child('landscape_zoom_switch')
    borders_crop_switch = Gtk.Template.Child('borders_crop_switch')
    borders_crop_threshold_row = Gtk.Template.Child('borders_crop_threshold_row')
    page_numbering_switch = Gtk.Template.Child('page_numbering_switch')
    ocr_lang_row = Gtk.Template.Child('ocr_lang_row')

    def __init__(self, reader):
        Adw.PreferencesDialog.__init__(self)

        self.reader = reader
        self.settings = Settings.get_default()

        self.css_provider = Gtk.CssProvider.new()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        #
        # Custom settings
        #
        list_store_expression = Gtk.PropertyExpression.new(KeyLabelPair, None, 'label')

        # Scaling
        self.scalings = {
            'screen': _('Adapt to Screen'),
            'width': _('Adapt to Width'),
            'height': _('Adapt to Height'),
            'original': _('Origin Size'),
        }

        model = Gio.ListStore(item_type=KeyLabelPair)
        items = [KeyLabelPair(key=key, label=label) for key, label in self.scalings.items()]
        model.splice(0, 0, items)
        self.scaling_row.set_expression(list_store_expression)
        self.scaling_row.set_model(model)

        # Scaling filter
        self.scaling_filters = {
            'linear': _('Linear'),
            'trilinear': _('Trilinear'),
        }

        model = Gio.ListStore(item_type=KeyLabelPair)
        items = [KeyLabelPair(key=key, label=label) for key, label in self.scaling_filters.items()]
        model.splice(0, 0, items)
        self.scaling_filter_row.set_expression(list_store_expression)
        self.scaling_filter_row.set_model(model)

        # Background color
        self.background_colors = {
            'white': _('White'),
            'gray': _('Gray'),
            'black': _('Black'),
            'system-style': _('System Style'),
        }

        model = Gio.ListStore(item_type=KeyLabelPair)
        items = [KeyLabelPair(key=key, label=label) for key, label in self.background_colors.items()]
        model.splice(0, 0, items)
        self.background_color_row.set_expression(list_store_expression)
        self.background_color_row.set_model(model)

        # Borders crop threshold
        model = Gio.ListStore(item_type=KeyLabelPair)
        items = [KeyLabelPair(key=str(value), label=str(value)) for value in BORDERS_CROP_THRESHOLDS]
        model.splice(0, 0, items)
        self.borders_crop_threshold_row.set_expression(list_store_expression)
        self.borders_crop_threshold_row.set_model(model)

        # OCR language
        if self.reader.ocr_translator.enabled:
            model = Gio.ListStore(item_type=KeyLabelPair)
            items = [KeyLabelPair(key=value, label=value) for value in self.reader.ocr_translator.ocr_languages]
            model.splice(0, 0, items)
            self.ocr_lang_row.set_expression(list_store_expression)
            self.ocr_lang_row.set_model(model)

        self.init_general()

    def init_custom(self):
        # Scaling
        self.scaling_row.set_selected(list(self.scalings.keys()).index(self.reader.scaling))
        self.scaling_row.connect('notify::selected', self.on_scaling_changed)

        # Scaling filter
        self.scaling_filter_row.set_selected(list(self.scaling_filters.keys()).index(self.reader.scaling_filter))
        self.scaling_filter_row.connect('notify::selected', self.on_scaling_filter_changed)

        # Background color
        self.background_color_row.set_selected(list(self.background_colors.keys()).index(self.reader.background_color))
        self.background_color_row.connect('notify::selected', self.on_background_color_changed)

        # Landscape zoom
        self.landscape_zoom_switch.set_active(self.reader.landscape_zoom)
        self.landscape_zoom_switch.connect('notify::active', self.on_landscape_zoom_changed)

        # Borders crop
        self.borders_crop_switch.set_active(self.reader.borders_crop)
        self.borders_crop_switch.connect('notify::active', self.on_borders_crop_changed)

        # Borders crop threshold
        self.borders_crop_threshold_row.set_selected(BORDERS_CROP_THRESHOLDS.index(self.reader.borders_crop_threshold))
        self.borders_crop_threshold_row.connect('notify::selected', self.on_borders_crop_threshold_changed)

        # Page numbering
        self.page_numbering_switch.set_active(not self.reader.page_numbering)
        self.page_numbering_switch.connect('notify::active', self.on_page_numbering_changed)

        # OCR language
        if self.reader.ocr_translator.enabled:
            self.ocr_lang_row.set_selected(self.reader.ocr_translator.ocr_languages.index(self.reader.ocr_translator.ocr_lang))
            self.ocr_lang_row.connect('notify::selected', self.on_ocr_lang_changed)
        else:
            self.ocr_lang_row.set_sensitive(False)

    def init_general(self):
        # Filters
        filters = {
            'brightness': {
                'title': _('Brightness'),
                'subtitle': _('Make pages brighter or darker'),
                'min': 0,
                'max': 200,
                'step': 1,
                'default': 100,
            },
            'contrast': {
                'title': _('Contrast'),
                'subtitle': _('Increase or decrease the contrast of pages'),
                'min': 0,
                'max': 200,
                'step': 1,
                'default': 100,
            },
            'grayscale': {
                'title': _('Grayscale'),
                'subtitle': _('Convert pages to grayscale'),
                'min': 0,
                'max': 100,
                'step': 1,
                'default': 0,
            },
            'sepia': {
                'title': _('Sepia'),
                'subtitle': _('Give a more yellow/brown appearance to pages'),
                'min': 0,
                'max': 100,
                'step': 1,
                'default': 0,
            },
            'saturate': {
                'title': _('Saturation'),
                'subtitle': _('Super-saturate or desaturate pages'),
                'min': 0,
                'max': 400,
                'step': 1,
                'default': 100,
            },
        }

        for name, data in filters.items():
            erow = Adw.ExpanderRow()
            erow.set_title(data['title'])
            erow.set_subtitle(data['subtitle'])
            erow.set_enable_expansion(self.settings.page_filters.get(f'{name}-state'))
            erow.set_show_enable_switch(True)
            erow.connect('notify::enable-expansion', self.toggle_page_filter_state, name)

            row = Adw.SpinRow.new_with_range(data['min'], data['max'], data['step'])
            row.set_title(data['title'])
            row.set_value(self.settings.page_filters.get(name, data['default']))
            row.connect('notify::value', self.on_page_filter_changed, name)

            erow.add_row(row)
            self.page_filters_group.add(erow)

        self.set_pages_filters()

    def on_background_color_changed(self, _row, _gparam):
        value = self.background_color_row.get_selected_item().key
        if value == self.reader.background_color:
            return

        self.reader.manga.update({
            'background_color': value if value != self.settings.background_color else None,
        })

        self.set_background_color()

    def on_borders_crop_changed(self, _row, _gparam):
        value = self.borders_crop_switch.props.active
        if value == self.reader.borders_crop:
            return

        self.reader.manga.update({
            'borders_crop': value if value != self.settings.borders_crop else None,
        })

        self.reader.pager.crop_pages_borders()

    def on_borders_crop_threshold_changed(self, _row, _gparam):
        value = int(self.borders_crop_threshold_row.get_selected_item().key)
        if value == self.reader.borders_crop_threshold:
            return

        self.reader.manga.update({
            'borders_crop_threshold': value if value != self.settings.borders_crop_threshold else None,
        })

        for page in self.reader.pager.pages:
            if page.image and page.error is None:
                page.image.crop_bbox = None
                page.image.textures_crop = None
                page.image.crop_threshold = value

    def on_landscape_zoom_changed(self, _row, _gparam):
        value = self.landscape_zoom_switch.props.active
        if value == self.reader.landscape_zoom:
            return

        self.reader.manga.update({
            'landscape_zoom': value if value != self.settings.landscape_zoom else None,
        })

        self.reader.pager.rescale_pages()

    def on_page_filter_changed(self, row, _gparam, name):
        filters = self.settings.page_filters
        filters[name] = row.get_value()
        self.settings.page_filters = filters

        self.set_pages_filters()

    def on_page_numbering_changed(self, _row, _gparam):
        value = not self.page_numbering_switch.props.active
        if value == self.reader.page_numbering:
            return

        self.reader.manga.update({
            'page_numbering': value if value != self.settings.page_numbering else None,
        })

        if value and self.reader.page_numbering_defined and not self.reader.controls.is_visible:
            self.reader.page_numbering_label.set_visible(True)
        else:
            self.reader.page_numbering_label.set_visible(False)

    def on_ocr_lang_changed(self, _row, _gparam):
        value = self.ocr_lang_row.get_selected_item().key
        if value == self.reader.ocr_translator.ocr_lang:
            return

        self.reader.manga.update({
            'ocr_lang': value if value != self.settings.ocr_lang else None,
        })

    def on_scaling_changed(self, _row, _gparam):
        value = self.scaling_row.get_selected_item().key
        if value == self.reader.scaling:
            return

        self.reader.manga.update({
            'scaling': value if value != self.settings.scaling else None,
        })

        # Landscape pages zoom is enabled in RTL/LTR/Vertical reading modes only and when scaling is 'screen'
        self.landscape_zoom_switch.set_sensitive(self.reader.reading_mode != 'webtoon' and self.reader.scaling == 'screen')

        self.reader.pager.rescale_pages()

    def on_scaling_filter_changed(self, _row, _gparam):
        value = self.scaling_filter_row.get_selected_item().key
        if value == self.reader.scaling_filter:
            return

        self.reader.manga.update({
            'scaling_filter': value if value != self.settings.scaling_filter else None,
        })

        self.reader.pager.rescale_pages()

    def set_background_color(self):
        if self.reader.background_color == 'white':
            self.reader.pager.set_css_classes(['background-white'])
        elif self.reader.background_color == 'gray':
            self.reader.pager.set_css_classes(['background-gray'])
        elif self.reader.background_color == 'black':
            self.reader.pager.set_css_classes(['background-black'])
        else:
            # System style
            self.reader.pager.set_css_classes([])

    def set_pages_filters(self):
        funcs = []
        for name, value in self.settings.page_filters.items():
            if name.endswith('-state'):
                # Ignore state key
                continue
            if not self.settings.page_filters.get(f'{name}-state'):
                # Filter is off
                continue

            funcs.append(f'{name}({value}%)')

        if funcs:
            self.css_provider.load_from_string(f'.page-filters {{filter: {" ".join(funcs)};}}')  # noqa
            self.reader.overlay.add_css_class('page-filters')
        else:
            self.css_provider.load_from_string('')
            self.reader.overlay.remove_css_class('page-filters')

    def show(self):
        self.init_custom()
        self.present(self.reader.window)

    def toggle_page_filter_state(self, row, _gparam, name):
        filters = self.settings.page_filters
        filters[f'{name}-state'] = row.get_enable_expansion()
        self.settings.page_filters = filters

        self.set_pages_filters()
