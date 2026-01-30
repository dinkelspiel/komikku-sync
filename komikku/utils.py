# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from dataclasses import dataclass
import datetime
from functools import cache
from functools import cached_property
from functools import wraps
from gettext import gettext as _
import html
from io import BytesIO
import logging
import os
import re
import subprocess
import traceback

import gi
from PIL import Image
import magic
import requests
from requests.adapters import HTTPAdapter
from requests.adapters import TimeoutSauce
from urllib3.util.retry import Retry

gi.require_version('Gdk', '4.0')
gi.require_version('Graphene', '1.0')
gi.require_version('Gtk', '4.0')

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Graphene
from gi.repository import Gtk
from gi.repository.GdkPixbuf import Pixbuf
from gi.repository.GdkPixbuf import PixbufAnimation

from komikku.consts import REQUESTS_TIMEOUT

logger = logging.getLogger('komikku')
logging.getLogger('PIL.Image').propagate = False
logging.getLogger('PIL.PngImagePlugin').propagate = False
logging.getLogger('PIL.TiffImagePlugin').propagate = False


def check_cmdline_tool(cmd):
    try:
        p = subprocess.Popen(cmd, bufsize=0, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        out, _ = p.communicate()
    except Exception:
        return False, None
    else:
        return p.returncode == 0, out.decode('utf-8').strip()


def concat_images_vertically(*args: Image):
    """
    Concat vertically a list of PIL images (same width)
    """
    h = 0
    for img in args:
        h += img.height

    dst = Image.new('RGB', (args[0].width, h))

    position = 0
    for img in args:
        dst.paste(img, (0, position))
        position += img.height

    return dst


def convert_and_resize_image(buffer, width, height, keep_aspect_ratio=True, dominant_color=True, format='JPEG'):
    """Convert and resize an image (except animated images)

    :param keep_aspect_ratio: Force to keep aspect ratio of the image
    :type keep_aspect_ratio: bool

    :param dominant_color: If scaling is not allowed, use image dominant color as background color of added borders
    :type dominant_color: bool

    :return: Converted image data
    :rtype: bytes
    """

    def get_dominant_color(img):
        # Resize image to reduce number of colors
        colors = img.resize((150, 150), resample=0).getcolors(150 * 150)
        sorted_colors = sorted(colors, key=lambda t: t[0])

        return sorted_colors[-1][1]

    def remove_alpha(img):
        if img.mode not in ('P', 'RGBA'):
            return img

        img = img.convert('RGBA')
        background = Image.new('RGBA', img.size, (255, 255, 255))

        return Image.alpha_composite(background, img)

    try:
        img = Image.open(BytesIO(buffer))
    except Exception as exc:
        logger.error('Failed to open image (Pillow)', exc_info=exc)
        return None

    if img.format in ('GIF', 'WEBP') and img.is_animated:
        return buffer

    old_width, old_height = img.size
    if keep_aspect_ratio and old_width >= old_height:
        img = remove_alpha(img)

        new_ratio = height / width

        new_img = Image.new(img.mode, (old_width, int(old_width * new_ratio)), get_dominant_color(img))
        new_img.paste(img, (0, (int(old_width * new_ratio) - old_height) // 2))
        new_img.thumbnail((width, height), Image.LANCZOS)
    else:
        new_img = img.resize((width, height), Image.LANCZOS)

    new_buffer = BytesIO()
    if format == 'JPEG':
        new_img.convert('RGB').save(new_buffer, 'JPEG', quality=90)
    else:
        # Assume format supports alpha channel (transparency)
        new_img.convert('RGBA').save(new_buffer, format)
    new_img.close()

    return new_buffer.getvalue()


def folder_size(path, exclude=None):
    if not os.path.exists(path):
        return None

    cmd = ['du', '-sh', path]
    if exclude is not None:
        cmd += [f'--exclude={exclude}']
    res = subprocess.run(cmd, stdout=subprocess.PIPE, check=False)
    size = res.stdout.split()[0].decode()

    return f'{size[:-1]} {size[-1]}iB'


def get_buffer_mime_type(buffer):
    """
    Returns the MIME type of a buffer

    :param buffer: A binary string
    :type buffer: bytes

    :return: The detected MIME type, empty string otherwise
    :rtype: str
    """
    try:
        if hasattr(magic, 'detect_from_content'):
            # Using file-magic module: https://github.com/file/file
            return magic.detect_from_content(buffer[:128]).mime_type  # noqa: TC300

        # Using python-magic module: https://github.com/ahupp/python-magic
        return magic.from_buffer(buffer[:128], mime=True)  # noqa: TC300
    except Exception:
        return ''


@cache
def get_cache_dir():
    cache_dir_path = GLib.get_user_cache_dir()

    # Check if inside flatpak sandbox
    if is_flatpak():
        return cache_dir_path

    cache_dir_path = os.path.join(cache_dir_path, 'komikku')
    if not os.path.exists(cache_dir_path):
        os.mkdir(cache_dir_path)

    return cache_dir_path


@cache
def get_cached_data_dir():
    dir_path = os.path.join(get_cache_dir(), 'tmp')
    if not os.path.exists(dir_path):
        os.mkdir(dir_path)

    return dir_path


@cache
def get_cached_logos_dir():
    dir_path = os.path.join(get_cache_dir(), 'logos')
    if not os.path.exists(dir_path):
        os.mkdir(dir_path)

    return dir_path


@cache
def get_data_dir():
    data_dir_path = GLib.get_user_data_dir()
    app_profile = Gio.Application.get_default().profile

    if not is_flatpak():
        base_path = data_dir_path
        data_dir_path = os.path.join(base_path, 'komikku')
        if app_profile == 'development':
            data_dir_path += '-devel'
        elif app_profile == 'beta':
            data_dir_path += '-beta'

        if not os.path.exists(data_dir_path):
            os.mkdir(data_dir_path)

    # Create folder for 'local' server
    data_local_dir_path = os.path.join(data_dir_path, 'local')
    if not os.path.exists(data_local_dir_path):
        os.mkdir(data_local_dir_path)

    return data_dir_path


def get_file_mime_type(path):
    """
    Returns the MIME type of a file

    :param path: A file path
    :type path: str

    :return: The detected MIME type, empty string otherwise
    :rtype: str
    """
    try:
        if hasattr(magic, 'detect_from_filename'):
            # Using file-magic module: https://github.com/file/file
            return magic.detect_from_filename(path).mime_type  # noqa: TC300

        # Using python-magic module: https://github.com/ahupp/python-magic
        return magic.from_file(path, mime=True)  # noqa: TC300
    except Exception:
        return ''


def get_image_info(path_or_bytes):
    try:
        if isinstance(path_or_bytes, str):
            img = Image.open(path_or_bytes)
        else:
            img = Image.open(BytesIO(path_or_bytes))
    except Exception as exc:
        # Pillow doesn´t support SVG images
        # Get content type to identify an image
        if isinstance(path_or_bytes, str):
            gfile = Gio.File.new_for_path(path_or_bytes)
            content_type = gfile.query_info('standard::content-type', Gio.FileQueryInfoFlags.NONE, None).get_content_type()
        else:
            content_type, _result_uncertain = Gio.content_type_guess(None, path_or_bytes)

        if content_type in ('image/svg+xml',):
            info = {
                'width': -1,
                'height': -1,
                'is_animated': False,
            }
        else:
            logger.warning('Failed to open or identify image', exc_info=exc)
            info = None
    else:
        info = {
            'width': img.width,
            'height': img.height,
            'is_animated': hasattr(img, 'is_animated') and img.is_animated,
        }

        img.close()

    return info


def get_response_elapsed(r):
    """
    Returns the response time (in seconds) of a request
    regardless of the request type (requests, curl_cffi)

    :param r: A response
    :type r: requests.models.Response or curl_cffi.requests.models.Response

    :return: How many seconds the request cost
    :rtype: float
    """
    elapsed = r.elapsed
    if isinstance(elapsed, datetime.timedelta):
        # requests HTTP client
        return elapsed.total_seconds()

    # curl_cffi HTTP client
    return elapsed


@cache
def get_webview_data_dir():
    return os.path.join(get_cache_dir(), 'webview')


def html_escape(s):
    return html.escape(html.unescape(s), quote=False)


def if_network_available(func_=None, only_notify=False):
    """Decorator to disable an action when network is not avaibable"""

    def _decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            window = args[0].parent if hasattr(args[0], 'parent') else args[0].window
            if not window.network_available:
                window.add_notification(_('You are currently offline'), timeout=3, priority=1)
                if not only_notify:
                    return None

            return func(*args, **kwargs)
        return wrapper

    if callable(func_):
        return _decorator(func_)
    elif func_ is None:
        return _decorator
    else:
        raise RuntimeWarning('Positional arguments are not supported')


def is_flatpak():
    return os.path.exists(os.path.join(GLib.get_user_runtime_dir(), 'flatpak-info'))


def is_number(s):
    return s is not None and str(s).replace('.', '', 1).isdigit()


def log_error_traceback(e):
    from komikku.servers.exceptions import ServerException

    if isinstance(e, requests.exceptions.RequestException):
        return _('No Internet connection, timeout or server down')
    if isinstance(e, ServerException):
        return e.message

    logger.info(traceback.format_exc())

    return None


def markdown_to_markup(s):
    # Escape HTML
    s = html_escape(s)

    # Convert links into <a> tags
    return re.sub(
        r'\[(.*?)\]\((\S*?)\s*("(.*?)")?\)',  # 1. text, 2. url, 4. title
        r'<a href="\g<2>">\g<1></a>',
        s,
        flags=re.M
    )


def remove_number_leading_zero(str_num):
    """Remove leading zero in a number string

    '00123' => '123' (int)
    '00123.45' => '123.45' (float)
    """
    return str(int(float(str_num))) if int(float(str_num)) == float(str_num) else str(float(str_num))


def retry_session(session=None, retries=3, allowed_methods=['GET'], backoff_factor=0.3, status_forcelist=None):
    if session is None:
        session = requests.Session()
    elif not getattr(session, 'adapters', None) or session.adapters['https://'].max_retries.total == retries:
        # Retry adapter is already modified or session is not a `requests (HTTP client)` session
        return session

    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        allowed_methods=allowed_methods,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)

    session.mount('http://', adapter)
    session.mount('https://', adapter)

    return session


def skip_past(haystack, needle):
    if (idx := haystack.find(needle)) >= 0:
        return idx + len(needle)

    return None


def trunc_filename(filename):
    """Reduce filename length to 255 (common FS limit) if it's too long"""
    return filename.encode('utf-8')[:255].decode().strip()


class BaseServer:
    id: str
    name: str

    description = None
    headers = None
    headers_images = None
    http_client = 'requests'  # HTTP client
    status = 'enabled'

    __sessions = {}  # to cache all existing sessions

    @property
    def session(self):
        return BaseServer.__sessions.get(self.id)

    @session.setter
    def session(self, value):
        BaseServer.__sessions[self.id] = value

    @cached_property
    def sessions_dir(self):
        dir_path = os.path.join(get_cache_dir(), 'sessions')
        if not os.path.exists(dir_path):
            os.mkdir(dir_path)

        return dir_path

    def get_image(self, url, etag=None):
        """
        Get an image

        :param url: The image URL
        :type url: str

        :param etag: The current image ETag
        :type etag: str or None

        :return: The image content, the image ETag if exists, the request time (seconds)
        :rtype: tuple
        """
        if url is None:
            return None, None, None

        if self.headers_images is not None:
            headers = self.headers_images
        else:
            headers = {
                'Accept': 'image/avif,image/webp,*/*',
                'Referer': f'{self.base_url}/',
            }
        if etag:
            headers['If-None-Match'] = etag

        if self.session:
            r = self.session.get(url, headers=headers)
        else:
            # Session object has not yet been instantiated (servers with login or using webview to complete challenge)
            r = requests.get(url, headers=headers)
        if not r.ok:
            return None, None, get_response_elapsed(r)

        buffer = r.content
        mime_type = get_buffer_mime_type(buffer)
        if not mime_type.startswith('image'):
            return None, None, get_response_elapsed(r)

        return buffer, r.headers.get('ETag'), get_response_elapsed(r)

    def save_image(self, url, dir_path, name, width, height, keep_aspect_ratio=True, dominant_color=True, format='JPEG'):
        if url is None:
            return False

        # If image has already been retrieved
        # Check first if it has changed using ETag
        current_etag = None
        etag_fs_path = os.path.join(dir_path, f'{name}.etag')
        if os.path.exists(etag_fs_path):
            with open(etag_fs_path, 'r') as fp:
                current_etag = fp.read()

        # Save image file
        try:
            data, etag, _rtime = self.get_image(url, current_etag)
        except Exception:
            return False
        if data is None:
            return False

        data = convert_and_resize_image(
            data, width, height, keep_aspect_ratio=keep_aspect_ratio, dominant_color=dominant_color, format=format
        )
        if data is None:
            return False

        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        fs_path = os.path.join(dir_path, f'{name}.{"jpg" if format == "JPEG" else format.lower()}')
        with open(fs_path, 'wb') as fp:
            fp.write(data)

        if etag:
            with open(etag_fs_path, 'w') as fp:
                fp.write(etag)
        elif os.path.exists(etag_fs_path):
            os.remove(etag_fs_path)

        return True

    def session_get(self, *args, **kwargs):
        try:
            r = retry_session(session=self.session).get(*args, **kwargs)
        except Exception as error:
            logger.debug(error)
            raise

        return r

    def session_patch(self, *args, **kwargs):
        try:
            r = self.session.patch(*args, **kwargs)
        except Exception as error:
            logger.debug(error)
            raise

        return r

    def session_post(self, *args, **kwargs):
        try:
            r = self.session.post(*args, **kwargs)
        except Exception as error:
            logger.debug(error)
            raise

        return r

    def session_put(self, *args, **kwargs):
        try:
            r = self.session.put(*args, **kwargs)
        except Exception as error:
            logger.debug(error)
            raise

        return r


class CustomTimeout(TimeoutSauce):
    def __init__(self, *args, **kwargs):
        if kwargs['connect'] is None:
            kwargs['connect'] = REQUESTS_TIMEOUT
        if kwargs['read'] is None:
            kwargs['read'] = REQUESTS_TIMEOUT * 2
        super().__init__(*args, **kwargs)


# Set requests timeout globally, instead of specifying ``timeout=..`` kwarg on each call
requests.adapters.TimeoutSauce = CustomTimeout


class CoverLoader(GObject.GObject):
    __gtype_name__ = 'CoverLoader'

    def __init__(self, path, pixbuf, texture, width=None, height=None, static_animation=False):
        super().__init__()

        self.path = path
        self.pixbuf = pixbuf
        self.texture = texture

        if self.pixbuf:
            self.orig_width = self.pixbuf.get_width()
            self.orig_height = self.pixbuf.get_height()
        else:
            self.orig_width = self.texture.get_width()
            self.orig_height = self.texture.get_height()

        # Compute size
        if width is None and height is None:
            self.width = self.orig_width
            self.height = self.orig_height

        elif width is None or height is None:
            ratio = self.orig_width / self.orig_height
            if width is None:
                self.width = int(height * ratio)
                self.height = height
            else:
                self.width = width
                self.height = int(width / ratio)

        else:
            self.width = width
            self.height = height

    @classmethod
    def new_from_data(cls, data, width=None, height=None, static_animation=False):
        info = get_image_info(data)
        if not info:
            return None

        try:
            stream = Gio.MemoryInputStream.new_from_data(data, None)
            if info['is_animated'] and not static_animation:
                pixbuf = PixbufAnimation.new_from_stream(stream)
            else:
                pixbuf = Pixbuf.new_from_stream(stream)

            stream.close()
        except Exception:
            # Invalid image, corrupted image, unsupported image format,...
            return None

        return cls(None, pixbuf, None, width, height, static_animation)

    @classmethod
    def new_from_file(cls, path, width=None, height=None, static_animation=False):
        info = get_image_info(path)
        if not info:
            return None

        try:
            if info['is_animated'] and not static_animation:
                pixbuf = PixbufAnimation.new_from_file(path)
            else:
                pixbuf = Pixbuf.new_from_file(path)
        except Exception:
            # Invalid image, corrupted image, unsupported image format,...
            return None

        return cls(path, pixbuf, None, width, height, static_animation)

    @classmethod
    def new_from_resource(cls, path, width=None, height=None):
        try:
            texture = Gdk.Texture.new_from_resource(path)
        except Exception:
            # Invalid image, corrupted image, unsupported image format,...
            return None

        return cls(None, None, texture, width, height, True)

    def dispose(self):
        self.pixbuf = None
        self.texture = None


class CoverPaintable(CoverLoader, Gdk.Paintable):
    __gtype_name__ = 'CoverPaintable'

    def __init__(self, path, image, texture, width=None, height=None, static_animation=False):
        CoverLoader.__init__(self, path, image, texture, width, height, static_animation)

        self.rect = Graphene.Rect().alloc()

        if isinstance(self.pixbuf, PixbufAnimation):
            self.animation_iter = self.pixbuf.get_iter(None)
            self.animation_timeout_id = None
        else:
            self.animation_iter = None
            self.animation_timeout_id = None

    def _start_animation(self):
        if not self.animation_iter or self.animation_timeout_id:
            return

        self.animation_timeout_id = GLib.timeout_add(self.animation_iter.get_delay_time(), self.on_delay)

    def _stop_animation(self):
        if not self.animation_iter or self.animation_timeout_id is None:
            return

        GLib.source_remove(self.animation_timeout_id)
        self.animation_timeout_id = None

    def dispose(self):
        self.animation_iter = None
        CoverLoader.dispose(self)

    def do_get_intrinsic_height(self):
        return self.height

    def do_get_intrinsic_width(self):
        return self.width

    def do_snapshot(self, snapshot, width, height):
        self.rect.init(0, 0, width, height)

        if self.pixbuf:
            if self.animation_iter:
                self.texture = Gdk.Texture.new_for_pixbuf(self.animation_iter.get_pixbuf())
            else:
                self.texture = Gdk.Texture.new_for_pixbuf(self.pixbuf)

        snapshot.append_texture(self.texture, self.rect)

    def on_delay(self):
        if self.animation_iter.get_delay_time() == -1:
            return GLib.SOURCE_REMOVE

        # Check if it's time to show the next frame
        if self.animation_iter.advance(None):
            self.invalidate_contents()

        return GLib.SOURCE_CONTINUE


class CoverPicture(Gtk.Picture):
    def __init__(self, paintable):
        super().__init__()
        self.set_paintable(paintable)

        if self.is_animated:
            self.connect('map', self.on_map)
            self.connect('unmap', self.on_unmap)

        self.connect('unrealize', self.on_unrealize)

    @classmethod
    def new_from_data(cls, data, width=None, height=None, static_animation=False):
        if paintable := CoverPaintable.new_from_data(data, width, height, static_animation):
            return cls(paintable)

        return None

    @classmethod
    def new_from_file(cls, path, width=None, height=None, static_animation=False):
        if paintable := CoverPaintable.new_from_file(path, width, height, static_animation):
            return cls(paintable)

        return None

    @classmethod
    def new_from_resource(cls, path, width=None, height=None):
        if paintable := CoverPaintable.new_from_resource(path, width, height):
            return cls(paintable)

        return None

    @cached_property
    def is_animated(self):
        return self.get_paintable().animation_iter is not None

    def on_map(self, _self):
        self.get_paintable()._start_animation()

    def on_unmap(self, _self):
        self.get_paintable()._stop_animation()

    def on_unrealize(self, _self):
        if self.is_animated:
            self.disconnect_by_func(self.on_map)
            self.disconnect_by_func(self.on_unmap)
            self.get_paintable()._stop_animation()

        self.disconnect_by_func(self.on_unrealize)

        self.get_paintable().dispose()


@dataclass
class ServerContent:
    """Class for describing the content available in a server (legal only)"""
    type: str = None
    license: str = None
    public_domain: bool = False  # 100% of content is in public domain
