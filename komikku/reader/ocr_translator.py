# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
from io import BytesIO
import threading

from PIL import Image
try:
    import pytesseract
except Exception:
    pytesseract = None

from gi.repository import Adw
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import GtkSource

from komikku.models.settings import Settings
from komikku.translators import Google
from komikku.translators import LANGUAGES


class LangCodeNamePair(GObject.Object):
    code = GObject.Property(type=str, flags=GObject.ParamFlags.READWRITE, default='')
    name = GObject.Property(type=str, nick='Name', blurb='Name', flags=GObject.ParamFlags.READWRITE, default='')


class OCRTranslator(GObject.GObject):
    def __init__(self, reader):
        super().__init__()

        self.__active = False
        self.enabled = True

        self.reader = reader
        self.window = reader.window

        self.togglebutton = self.reader.ocr_translator_togglebutton
        self.bottomsheet = self.reader.ocr_translator_bottomsheet
        self.box = self.reader.ocr_translator_box
        self.src_dropdown = self.reader.ocr_translator_src_dropdown
        self.src_scrolledwindow = self.reader.ocr_translator_src_scrolledwindow
        self.dst_dropdown = self.reader.ocr_translator_dst_dropdown
        self.dst_scrolledwindow = self.reader.ocr_translator_dst_scrolledwindow
        self.clear_button = self.reader.ocr_translator_clear_button
        self.chars_counter_label = self.reader.ocr_translator_chars_counter_label
        self.translate_button = self.reader.ocr_translator_translate_button
        self.translate_spinner = self.reader.ocr_translator_translate_spinner
        self.copy_button = self.reader.ocr_translator_copy_button

        if pytesseract is None or not self.ocr_languages:
            self.enabled = False
            self.togglebutton.set_visible(False)
        else:
            self.reader.window.breakpoint.add_setter(self.box, 'orientation', Gtk.Orientation.VERTICAL)

            self.togglebutton.connect('toggled', self.toggle)

            list_store_expression = Gtk.PropertyExpression.new(LangCodeNamePair, None, 'name')
            items = [LangCodeNamePair(code='auto', name='Auto')]
            items += [LangCodeNamePair(code=k, name=v) for k, v in LANGUAGES.items()]

            # Source
            model = Gio.ListStore(item_type=LangCodeNamePair)
            model.splice(0, 0, items)
            self.src_dropdown.set_expression(list_store_expression)
            self.src_dropdown.set_model(model)

            self.src_text = TextView(editable=True, bottom_margin=9, left_margin=9, right_margin=9, top_margin=9)
            self.src_text.buffer.connect('changed', self.on_src_text_changed)
            self.src_scrolledwindow.set_child(self.src_text)

            # Destination
            model = Gio.ListStore(item_type=LangCodeNamePair)
            model.splice(0, 0, items[1:])
            self.dst_dropdown.set_expression(list_store_expression)
            self.dst_dropdown.set_model(model)
            self.dst_dropdown.set_selected(list(LANGUAGES.keys()).index('en'))

            self.dst_text = TextView(editable=False, bottom_margin=9, left_margin=9, right_margin=9, top_margin=9)
            self.dst_scrolledwindow.set_child(self.dst_text)

            # Buttons
            self.clear_button.connect('clicked', self.src_text.clear_text)
            self.translate_button.connect('clicked', self.translate)
            self.copy_button.connect('clicked', self.copy_dst)

    @GObject.Property(type=bool, default=False)
    def active(self):
        return self.__active

    @active.setter
    def active(self, active):
        if not self.enabled:
            return
        if active and self.reader.window.page != self.reader.props.tag:
            # Avoid activation outside of reader page
            return

        self.__active = active

        self.reader.pager.interactive = not active
        self.bottomsheet.props.reveal_bottom_bar = active
        self.togglebutton.props.active = active
        if not active:
            self.bottomsheet.props.open = False
            self.togglebutton.remove_css_class('accent')
        else:
            self.togglebutton.add_css_class('accent')

    @property
    def ocr_lang(self):
        lang = self.reader.manga.ocr_lang
        if lang and lang in self.ocr_languages:
            return lang

        lang = Settings.get_default().ocr_lang
        if lang and lang in self.ocr_languages:
            return lang

        return self.ocr_languages[0]

    @property
    def ocr_languages(self):
        if pytesseract is None:
            return None

        languages = pytesseract.get_languages()
        for lang in ('osd', 'equ'):
            if lang in languages:
                languages.remove(lang)

        return languages

    def copy_dst(self, _btn):
        if display := Gdk.Display.get_default():
            display.get_clipboard().set(self.dst_text.get_text())
            self.reader.window.add_notification(_('Copied to clipboard'))

    def on_src_text_changed(self, _buffer):
        text = self.src_text.get_text()
        self.chars_counter_label.set_text(f'{len(text)}/2000')
        self.translate_button.set_sensitive(text and not text.isspace())

    def open_sheet(self, text):
        self.dst_text.clear_text()
        if text:
            self.src_text.set_text(text)
            self.translate_button.set_sensitive(True)
            self.bottomsheet.props.open = True

    def recognize(self, image, x, y, w, h):
        def complete(text):
            self.open_sheet(text)

        def run():
            with Image.open(image.path or BytesIO(image.data)) as full_img:
                img = full_img.crop((x, y, w, h))
                text = pytesseract.image_to_string(img, lang=self.ocr_lang, config='--psm 12 --oem 1')
                img.close()

            text = text.strip().replace('\n\n', '\n')

            GLib.idle_add(complete, text)

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()

    def set_active(self, active):
        self.active = active

    def toggle(self, _button):
        active = self.togglebutton.get_active()
        if active == self.active:
            return

        self.active = active

    def translate(self, _btn):
        def on_complete(result):
            self.translate_spinner.set_visible(False)
            self.dst_text.set_text(result['translated'])

        def on_error(message):
            self.translate_spinner.set_visible(False)
            self.window.add_notification(message)

        def run(text):
            try:
                result = Google().translate(
                    text,
                    src=self.src_dropdown.get_selected_item().code,
                    dst=self.dst_dropdown.get_selected_item().code
                )
            except Exception as e:
                GLib.idle_add(on_error, e.message)
                return

            GLib.idle_add(on_complete, result)

        text = self.src_text.get_text().strip()
        self.translate_spinner.set_visible(True)
        self.dst_text.clear_text()

        thread = threading.Thread(target=run, args=(text, ))
        thread.daemon = True
        thread.start()


class TextView(GtkSource.View):
    __gtype_name__ = 'TextView'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.buffer = self.props.buffer
        scheme = 'adwaita-dark' if Adw.StyleManager.get_default().get_dark() else 'adwaita-light'
        self.buffer.set_style_scheme(GtkSource.StyleSchemeManager.get_default().get_scheme(scheme))

    def clear_text(self, *args):
        self.set_text('')

    def get_text(self):
        return self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True)

    def set_text(self, text):
        self.buffer.set_text(text)
