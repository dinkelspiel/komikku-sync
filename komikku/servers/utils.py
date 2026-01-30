# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import datetime
from functools import wraps
import glob
import importlib
import inspect
from io import BytesIO
import itertools
import json
import logging
import math
from operator import itemgetter
import os
from pkgutil import iter_modules
import re
import struct
import sys
import time

from bs4 import BeautifulSoup
from bs4 import NavigableString
import dateparser
import emoji
from gi.repository import Gio
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
import requests

from komikku.consts import USER_AGENT
from komikku.servers.loader import ServerFinder
from komikku.utils import get_cached_logos_dir

logger = logging.getLogger(__name__)


class TextImage:
    def __init__(self, text, width=1500, height=2126, bg_color='#fff', fg_color='#000', font_size=64, format='webp'):
        self.format = format
        self.image = Image.new('RGB', (width, height), bg_color)

        if text is None:
            text = ''

        rfont = Gio.resources_lookup_data('/info/febvre/Komikku/text-image.otf', Gio.ResourceLookupFlags.NONE)
        font = ImageFont.truetype(BytesIO(rfont.get_data()), font_size)

        draw = ImageDraw.Draw(self.image)
        if '\n' in text:
            left, top, right, bottom = draw.multiline_textbbox((0, 0), text, font, font_size=font_size)
        else:
            left, top, right, bottom = draw.textbbox((0, 0), text, font, font_size=font_size)

        text_width = right - left
        text_height = bottom - top
        text_coord = ((width - text_width) // 2, (height - text_height) // 2)

        draw.multiline_text(text_coord, text, fill=fg_color, font=font, align='center')
        del draw

    @property
    def content(self):
        buf = BytesIO()
        self.image.save(buf, self.format.upper())

        return buf.getvalue()

    @property
    def mime_type(self):
        return f'image/{self.format}'


def convert_date_string(date_string, format=None, languages=None):
    """
    Convert a date string into a date object

    :param date_string: A string representing date in a recognizably valid format
    :type date_string: str

    :param format: A format string using directives as given `here <https://docs.python.org/3/library/datetime.html#strftime-and-strptime-behavior>`_
    :type format: str

    :param languages: A list of language codes, e.g. ['en', 'es', 'pt_BR']
    :type languages: list

    :return: A date object representing parsed date string if successful, `None` otherwise
    :rtype: datetime.date
    """

    # Check if languages are supported by dateparser
    # And detect whether a language code should be treated as a locale code
    if languages:
        language_locale = dateparser.data.language_locale_dict
        supported_languages = set()
        supported_locales = set()

        for code in languages:
            # Some codes should not be treated as locales
            if code.startswith(('zh_',)):
                code = code.replace('_', '-', 1)

            if '_' in code:
                lang, country = code.split('_')
            else:
                lang, country = code, None

            if lang not in language_locale:
                # Not supported
                continue

            if country and f'{lang}-{country}' in language_locale[lang]:
                # Code is a locale code
                supported_locales.add(f'{lang}-{country}')

            supported_languages.add(lang)

        languages = list(supported_languages)
        locales = list(supported_locales)
    else:
        locales = None

    if format is not None:
        try:
            d = datetime.datetime.strptime(date_string, format)
        except Exception:
            d = dateparser.parse(date_string, languages=languages, locales=locales)
    else:
        d = dateparser.parse(date_string, languages=languages, locales=locales)

    return d.date() if d else None


# https://github.com/italomaia/mangarock.py/blob/master/mangarock/mri_to_webp.py
def convert_mri_data_to_webp_buffer(data):
    size_list = [0] * 4
    size = len(data)
    header_size = size + 7

    # little endian byte representation
    # zeros to the right don't change the value
    for i, byte in enumerate(struct.pack('<I', header_size)):
        size_list[i] = byte

    buffer = [
        82,  # R
        73,  # I
        70,  # F
        70,  # F
        size_list[0],
        size_list[1],
        size_list[2],
        size_list[3],
        87,  # W
        69,  # E
        66,  # B
        80,  # P
        86,  # V
        80,  # P
        56,  # 8
    ]

    for bit in data:
        buffer.append(101 ^ bit)

    return bytes(buffer)


def do_login(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        server = args[0]
        if not server.logged_in:
            server.do_login()

        if server.logged_in:
            return func(*args, **kwargs)

        logger.warning('Server %s is not logged in. Please check credential in Settings', server.name)
        return None

    return wrapper


def get_allowed_servers_list(settings):
    servers_settings = settings.servers_settings
    servers_languages = settings.servers_languages

    servers = []
    for server_data in get_servers_list():
        if servers_languages and server_data['lang'] and server_data['lang'] not in servers_languages:
            continue

        server_settings = servers_settings.get(get_server_main_id_by_id(server_data['id']))
        if server_settings is not None:
            if not server_settings.get('enabled', True):
                # Server is disabled
                continue
            if len(servers_languages) > 0:
                if server_data['lang'] and server_data['lang'] not in servers_languages:
                    # Server language is not in list of enabled server languages
                    continue
                if not server_settings.get('langs', {}).get(server_data['lang'], True):
                    # Server is disabled for this language
                    continue

        if settings.nsfw_content is False and server_data['is_nsfw']:
            continue
        if settings.nsfw_only_content is False and server_data['is_nsfw_only']:
            continue

        servers.append(server_data)

    return servers


def get_server_class_name_by_id(id):
    """
    Returns a server class name from its ID

    `id` must respect the following format: `name[_lang][_whatever][:module_name]`

    + `name` is the name of the server.
    + `lang` is the language of the server (optional).
        Only useful when server belongs to a multi-languages server.
    + `whatever` is any string (optional).
        Only useful when a server must be backed up because it's dead.
        Beware, if `whatever` is defined, `lang` must be present even if it's empty.
        Example of value: old, bak, dead,...
    + `module_name` is the name of the module in which the server is defined (optional).
        Only useful if `module_name` is different from `name`.

    Parameters
    ----------
    :param id: A server ID
    :type id: str

    :return: The server class name corresponding to ID
    :rtype: str
    """
    return id.split(':')[0].capitalize()


def get_server_dir_name_by_id(id):
    name = id.split(':')[0]
    # Remove _whatever
    name = '_'.join(filter(None, name.split('_')[:2]))

    return name


def get_server_main_id_by_id(id):
    return id.split(':')[0].split('_')[0]


def get_server_module_name_by_id(id):
    return id.split(':')[-1].split('_')[0]


def get_servers_list(include_disabled=False, order_by=('lang', 'name')):
    servers = []
    for module in get_servers_modules():
        for _name, obj in dict(inspect.getmembers(module)).items():
            if not hasattr(obj, 'id') or not hasattr(obj, 'name') or not hasattr(obj, 'lang'):
                continue
            if NotImplemented in (obj.id, obj.name, obj.lang):
                continue

            if not include_disabled and obj.status == 'disabled':
                continue

            if inspect.isclass(obj):
                logo_path = os.path.join(get_cached_logos_dir(), 'servers', get_server_main_id_by_id(obj.id) + '.png')

                servers.append(dict(
                    id=obj.id,
                    name=obj.name,
                    content=obj.content,
                    description=obj.description,
                    lang=obj.lang,
                    base_url=obj.base_url,
                    has_login=obj.has_login,
                    is_nsfw=obj.is_nsfw,
                    is_nsfw_only=obj.is_nsfw_only,
                    logo_path=logo_path if os.path.exists(logo_path) else None,
                    logo_url=obj.logo_url,
                    module=module,
                    params=obj.params,
                    class_name=get_server_class_name_by_id(obj.id),
                ))

    return sorted(servers, key=itemgetter(*order_by))


def get_servers_modules():
    def import_external_modules(servers_path, modules, modules_names, multi=False):
        if multi:
            servers_path = os.path.join(servers_path, 'multi')

        count = 0
        for path in glob.glob(os.path.join(servers_path, '*')):
            if not multi and os.path.isfile(path):
                continue

            name = os.path.basename(path)
            module_name = f'komikku.servers.multi.{name}' if multi else f'komikku.servers.{name}'
            if module_name in modules_names:
                continue

            if name == 'multi':
                continue

            module = importlib.import_module(f'.{name}', package='komikku.servers.multi' if multi else 'komikku.servers')
            modules.append(module)
            modules_names.append(module_name)
            count += 1

        if count > 0:
            logger.info('Import {0} servers modules from external folder: {1}'.format(count, servers_path))

        return count

    def import_internal_modules(namespace, modules, modules_names):
        count = 0
        for _finder, module_name, ispkg in iter_namespace(namespace):
            if module_name in modules_names or not ispkg or module_name.endswith('.multi'):
                continue

            module = importlib.import_module(module_name)
            modules.append(module)
            modules_names.append(module_name)
            count += 1

        if count > 0:
            logger.info('Import {0} servers modules from internal folder'.format(count))

        return count

    def iter_namespace(ns_pkg):
        # Specifying the second argument (prefix) to iter_modules makes the
        # returned name an absolute name instead of a relative one. This allows
        # import_module to work without having to do additional modification to
        # the name.
        return iter_modules(ns_pkg.__path__, ns_pkg.__name__ + '.')

    internal_done = False
    modules = []
    modules_names = []
    for finder in sys.meta_path:
        if isinstance(finder, ServerFinder):
            # Import servers from external folders
            for servers_path in finder.paths:
                if not os.path.exists(servers_path):
                    # Not very likely
                    continue

                import_external_modules(servers_path, modules, modules_names, multi=False)

        elif not internal_done:
            # Import internal servers
            import komikku.servers

            count = import_internal_modules(komikku.servers, modules, modules_names)

            if count > 0:
                internal_done = True

    return modules


def get_session_cookies(s):
    """
    Returns the cookies of a session
    regardless of the HTTP client (requests, curl_cffi)

    :param s: A session
    :type s: requests.sessions.Session or curl_cffi.requests.session.Session

    :return: a cookies Jar
    :rtype: requests.cookies.RequestsCookieJar or http.cookiejar.CookieJar
    """
    return s.cookies.jar if hasattr(s.cookies, 'jar') else s.cookies


def get_soup_element_inner_text(tag, text=None, sep=' ', recursive=True):
    """
    Returns inner text of a tag

    :param tag: A Tag
    :type tag: bs4.element.Tag

    :param text: A optional list of text strings to prepend
    :type text: list of str

    :param recursive: Recursively walk in children or not
    :type recursive: bool

    :return: The inner text of tag
    :rtype: str
    """
    if text is None:
        text = []

    for el in tag:
        if isinstance(el, NavigableString):
            text.append(el.strip())
        elif recursive:
            get_soup_element_inner_text(el, text)

    return sep.join(text).strip()


def parse_nextjs_hydration(soup, keyword, key=None):
    """
    Goes through all scripts in `soup`

    If a Next.js hydration containing `keyword` is found, it's deserialized and returned

    :param keyword: A string to identify the script being searched for
    :type text: str

    :param key: A key to retrieve a specific value rather than all data (optional)
    :type text: str
    """

    data = None

    for script_element in soup.select('script'):
        script = script_element.string
        if not script or not script.startswith('self.__next_f.push([1,') or f'\\"{keyword}\\":' not in script:  # noqa: E231, E701
            continue

        line = script.strip().replace('self.__next_f.push([1,', '')

        start = 0
        for c in line:
            if c in ('{', '['):
                break
            start += 1

        line = line[start:-3]

        try:
            data = json.loads(json.loads(f'"{line}"'))
        except Exception as e:
            logger.debug(f'ERROR: {line}')
            logger.debug(e)
        break

    if key:
        key_value = None

        def get_key(data):
            nonlocal key_value

            if isinstance(data, list):
                for value in data:
                    get_key(value)

            elif isinstance(data, dict):
                for key, value in data.items():
                    if key != keyword:
                        get_key(value)
                        continue

                    key_value = value
                    break

        get_key(data)

        return key_value

    return data


def sojson4_decode(s):
    """
    Decodes a Sojson v4 string

    :param s: A string
    :type s: str

    :return: The decoded string
    :rtype: str
    """
    ss = re.split(r'[a-zA-Z]{1,}', s[240:-58])
    sss = ''
    for c in ss:
        sss += chr(int(c))

    return sss


def remove_emoji_from_string(text):
    """
    Removes Emojis from text (use emoji package)

    :param text: A text string
    :type text: str

    :return: The text string freed from Emojis
    :rtype: str
    """
    return emoji.replace_emoji(text, replace='').strip()


def search_duckduckgo(site, term, nb_pages=1):
    """
    Searches DuckDuckGo lite

    :param site: the site URL
    :type site: str

    :param term: the term to search for
    :type term: str

    :param nb_pages: the number of results pages to parse
    :type nb_pages: int

    :return: A list of dictionaries (name, url)
    :rtype: list of dict
    """
    base_url = 'https://lite.duckduckgo.com'

    session = requests.Session()
    session.headers.update({
        'Content-Type': 'application/x-www-form-urlencoded',
        'Origin': base_url,
        'Referer': f'{base_url}/',
        'User-Agent': USER_AGENT,
    })

    def extract_params(soup):
        """Extract vqd, s, dc params from HTML results page"""
        params = {}
        if input := soup.select_one('input[name="vqd"]'):
            params['vqd'] = input.get('value')
        if input := soup.select_one('input[name="s"]'):
            params['s'] = input.get('value')
        if input := soup.select_one('input[name="dc"]'):
            params['dc'] = input.get('value')

        return params

    def get_page(q, next_params):
        """Get and parse HTML results page"""
        params = {
            'q': q,
            'kl': '',
        }
        if next_params:
            params.update(next_params)
            params.update({
                'nextParams': '',
                'v': 'l',
                'o': 'json',
                'api': 'd.js',
                'kl': 'wt-wt',
            })
        else:
            params.update({
                'df': '',
            })

        r = session.post(base_url + '/lite/', data=params)
        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for a_element in soup.select('.result-link'):
            url = a_element.get('href')
            if 'duckduckgo.com' in url:
                # Sponsored link
                continue

            results.append({
                'name': a_element.text.strip(),
                'url': a_element.get('href'),
            })

        return results, extract_params(soup)

    data = []
    next_params = None
    q = f'site:{site} {term}'  # noqa: E231
    for _index in range(nb_pages):
        results, next_params = get_page(q, next_params)
        data += results
        if not next_params:
            break
        time.sleep(1)

    return data


# https://github.com/Harkame/JapScanDownloader
def unscramble_image(image):
    """
    Unscrambles an image

    :param image: An image object
    :type image: PIL.Image.Image, bytes

    :return: A new unscrambled image
    :rtype: PIL.Image.Image
    """
    if not isinstance(image, Image.Image):
        image = Image.open(BytesIO(image))

    temp = Image.new('RGB', image.size)
    output_image = Image.new('RGB', image.size)

    for x in range(0, image.width, 200):
        col1 = image.crop((x, 0, x + 100, image.height))

        if x + 200 <= image.width:
            col2 = image.crop((x + 100, 0, x + 200, image.height))
            temp.paste(col1, (x + 100, 0))
            temp.paste(col2, (x, 0))
        else:
            col2 = image.crop((x + 100, 0, image.width, image.height))
            temp.paste(col1, (x, 0))
            temp.paste(col2, (x + 100, 0))

    for y in range(0, temp.height, 200):
        row1 = temp.crop((0, y, temp.width, y + 100))

        if y + 200 <= temp.height:
            row2 = temp.crop((0, y + 100, temp.width, y + 200))
            output_image.paste(row1, (0, y + 100))
            output_image.paste(row2, (0, y))
        else:
            row2 = temp.crop((0, y + 100, temp.width, temp.height))
            output_image.paste(row1, (0, y))
            output_image.paste(row2, (0, y + 100))

    return output_image


class RC4:
    """ RC4 (Rivest Cipher 4) stream cipher"""

    def __init__(self, key):
        self.key = key.encode()
        self.keystream = self.PRGA(self.KSA())

        # RC4-drop[256]
        for _i in range(256):
            next(self.keystream)

    def KSA(self):
        # Initialize S as a list of integers from 0 to 255
        S = list(range(256))
        j = 0

        for i in range(256):
            j = (j + S[i] + self.key[i % len(self.key)]) % 256
            # Swap values
            S[i], S[j] = S[j], S[i]

        return S

    def PRGA(self, S):
        i = j = 0

        while True:
            i = (i + 1) % 256
            j = (j + S[i]) % 256
            # Swap values
            S[i], S[j] = S[j], S[i]
            K = S[(S[i] + S[j]) % 256]
            yield K


class RC4SeedRandom:
    def __init__(self, key):
        self.key = key
        self.pos = 256

    def get_next(self):
        if self.pos == 256:
            self.keystream = RC4(self.key).keystream
            self.pos = 0
        self.pos += 1

        return next(self.keystream)


def unscramble_image_rc4(image, key, piece_size):
    """
    Unscrambles an image shuffled with RC4 stream cipher

    :param image: An image object
    :type image: PIL.Image.Image, bytes

    :param key: The key
    :type key: str

    :param piece_size: The pieces size
    :type piece_size: int

    :return: A new unscrambled image
    :rtype: PIL.Image.Image
    """
    if not isinstance(image, Image.Image):
        image = Image.open(BytesIO(image))

    output_image = Image.new('RGB', image.size)

    pieces = []
    for j in range(math.ceil(image.height / piece_size)):
        for i in range(math.ceil(image.width / piece_size)):
            pieces.append(dict(
                x=piece_size * i,
                y=piece_size * j,
                w=min(piece_size, image.width - piece_size * i),
                h=min(piece_size, image.height - piece_size * j)
            ))

    groups = {}
    for k, v in itertools.groupby(pieces, key=lambda x: x['w'] << 16 | x['h']):
        if k not in groups:
            groups[k] = []
        groups[k] += list(v)

    for _w, group in groups.items():
        size = len(group)

        permutation = []
        indexes = list(range(size))
        random = RC4SeedRandom(key)
        for i in range(size):
            num = random.get_next()
            exp = 8
            while num < (1 << 52):
                num = num << 8 | random.get_next()
                exp += 8
            while num >= (1 << 53):
                num = num >> 1
                exp -= 1

            permutation.append(indexes.pop(int(num * (2 ** -exp) * len(indexes))))

        for i, original in enumerate(permutation):
            src = group[i]
            dst = group[original]

            src_piece = image.crop((src['x'], src['y'], src['x'] + src['w'], src['y'] + src['h']))
            output_image.paste(src_piece, (dst['x'], dst['y']))

    return output_image
