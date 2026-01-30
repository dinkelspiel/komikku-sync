# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from abc import ABC
from abc import abstractmethod
import hashlib
from io import BytesIO
import json
import logging
import os
import pickle
import zipfile

from bs4 import BeautifulSoup
try:
    from curl_cffi import requests as crequests
except Exception:
    crequests = None
from http.cookiejar import CookieJar
import requests

from komikku.consts import LOGO_SIZE
from komikku.consts import REQUESTS_TIMEOUT
from komikku.consts import USER_AGENT
from komikku.models.keyring import KeyringHelper
from komikku.models.settings import Settings
from komikku.servers.exceptions import ServerException
from komikku.servers.loader import ServerFinder
from komikku.servers.loader import ServerFinderPriority
from komikku.servers.utils import get_server_main_id_by_id
from komikku.utils import BaseServer
from komikku.utils import get_cache_dir
from komikku.utils import get_cached_logos_dir
from komikku.utils import retry_session

APP_MIN_VERSION = '1.102.0'  # Minimum app version required to use `Up-to-date servers modules`

# https://www.localeplanet.com/icu/
LANGUAGES = dict(
    ar='العربية',
    cs='Čeština',
    de='Deutsch',
    en='English',
    eo='Espéranto',
    es='Español',
    es_419='Español (Latinoamérica)',
    fa='فارسی',
    fr='Français',
    id='Bahasa Indonesia',
    it='Italiano',
    ja='日本語',
    ko='한국어',
    nb='Norsk Bokmål',
    nl='Nederlands',
    pl='Polski',
    pt='Português',
    pt_BR='Português (Brasil)',
    ru='Русский',
    th='ไทย',
    tr='Türkçe',
    uk='Українська',
    vi='Tiếng Việt',
    zh_Hans='中文 (简体)',
    zh_Hant='中文 (繁體)',
)

VERSION = 1

logger = logging.getLogger('komikku.servers')


class Server(BaseServer, ABC):
    id: str
    name: str
    lang: str
    content = None
    true_search = True  # If False, hide search in Explorer search page (XKCD, DBM, pepper&carotte…)

    base_url = None
    donate_url = None
    logo_url = None

    bypass_cf_url = None  # To be used when challenge is not present at base_url
    filters = None  # List of search filters (genre, rating, status…)
    has_captcha = False
    has_cf = False
    has_login = False
    is_nsfw = False
    is_nsfw_only = False
    logged_in = False
    long_strip_genres = []
    manga_title_css_selector = None  # Used to extract manga title in a manga URL
    params = None  # List of parameters (images quality for ex.)
    sync = False

    @classmethod
    def get_manga_initial_data_from_url(cls, url):
        if cls.manga_title_css_selector:
            c = cls()
            r = c.session_get(url)
            if r.status_code != 200:
                return None

            soup = BeautifulSoup(r.text, 'html.parser')

            title_element = soup.select_one(cls.manga_title_css_selector)
            if not title_element:
                return None

            results = c.search(title_element.text.strip())
            if not results:
                return None

            slug = results[0]['slug']
        else:
            slug = url.split('?')[0].split('/')[-1]

        return dict(slug=slug)

    @property
    def logo_path(self):
        path = os.path.join(get_cached_logos_dir(), 'servers', f'{get_server_main_id_by_id(self.id)}.png')
        if not os.path.exists(path):
            return None

        return path

    def clear_session(self, all=False):
        main_id = get_server_main_id_by_id(self.id)

        # Remove session from disk
        file_path = os.path.join(self.sessions_dir, '{0}.pickle'.format(main_id))
        if os.path.exists(file_path):
            os.unlink(file_path)

        if all:
            for id_ in self._BaseServer__sessions.keys():
                if id_.startswith(main_id):
                    del self._BaseServer__sessions[id_]
        elif self.id in self._BaseServer__sessions:
            del self._BaseServer__sessions[self.id]

    def do_login(self, username=None, password=None):
        if username and password:
            # Username and password are provided only when user defines the credentials in the settings
            self.clear_session()

        credential = self.get_credential()
        if self.base_url is None and credential:
            self.base_url = credential.address

        if self.base_url is None:
            logger.warning('Server %s base_url is not defined. Please check server address in Settings', self.name)
            return

        if self.session is None:
            if self.load_session():
                self.logged_in = True
            else:
                self.session = requests.Session()
                if self.headers:
                    self.session.headers = self.headers

                if username is None and password is None:
                    if credential.username and credential.password:
                        self.logged_in = self.login(credential.username, credential.password)
                else:
                    self.logged_in = self.login(username, password)
        else:
            self.logged_in = True

    def get_credential(self):
        return KeyringHelper().get(get_server_main_id_by_id(self.id))

    @abstractmethod
    def get_manga_data(self, initial_data):
        """This method must return a dictionary.

        Data are usually obtained:
        - by scrapping an HTML page
        - or by parsing the response of a request to an API.

        In most cases, the URL of the HTML page or the URL of the API endpoint
        are forged using a slug provided by method `search` and available in `initial_data` argument.

        By convention, returned dict MUST contain the following keys:
        - name: Name of the manga
        - authors: List of authors (str) [optional]
        - scanlators: List of scanlators (str) [optional]
        - genres: List of genres (str) [optional]
        - status: Status of the manga (See database.Manga.STATUSES) [optional]
        - synopsis: Synopsis of the manga [optional]
        - chapters: List of chapters (See description below)
        - server_id: The server ID
        - cover: Absolute URL of the cover

        By convention, a chapter is a dictionary which MUST contain the following keys:
        - slug: A slug (str) allowing to forge HTML page URL of the chapter
          (usually in conjunction with the manga slug)
        - url: URL of chapter HTML page if `slug` is not usable
        - title: Title of the chapter
        - date: Publish date of the chapter [optional]
        - scanlators: List of scanlators (str) [optional]
        """

    @abstractmethod
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """This method must return a list of pages.

        Data are usually obtained:
        - by scrapping an HTML page
        - or by parsing the response of a request to an API.

        The URL of the HTML page or the URL of the API endpoint are forged using 4 provided arguments.

        By convention, each page is a dictionary which MUST contain one of the 3 keys `slug`, `image` or `url`:
        - slug : A slug (str) allowing to forge image URL of the page
                 (usually in conjunction with the manga slug and the chapter slug)
        - image: Absolute or relative URL of the page image
        - url: URL of the HTML page to scrape to get the URL of the page image

        It's of course possible to add any other information if necessary
        (an index for example to compute a better image filename).

        The page data are passed to `get_manga_chapter_page_image` method.
        """

    @abstractmethod
    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """This method must return a dictionary with the following keys:

        - buffer: Image buffer
        - mime_type: Image MIME type
        - name: Filename of the image

        Depending on the server, we have:
        - the slug or the URL of the image
        - or the URL of the HTML page containing the image.

        In the first case, we have the URL (or can forge it) so we can directly retrieve the image with a GET request.

        In the second case, we must first retrieve the URL of the image by scraping the HTML page containing the image.
        """

    @abstractmethod
    def get_manga_url(self, slug, url):
        """This method must return absolute URL of the manga"""

    def get_param(self, key):
        """Returns param value if defined in server settings else returns param default value"""

        # Check param exists
        if self.params is None:
            logger.error('[%s] Unknown server param key `%s`', self.id, key)
            raise ServerException('Unknown server param key {0}'.format(key))

        param = None
        for param_ in self.params:
            if param_['key'] == key:
                param = param_
                break

        if param is None:
            logger.error('[%s] Unknown server param key `%s`', self.id, key)
            raise ServerException('Unknown server param key {0}'.format(key))

        # Search for param in server settings
        if settings := Settings.get_default():
            main_id = get_server_main_id_by_id(self.id)
            if server_settings := settings.servers_settings.get(main_id):
                if 'params' in server_settings and key in server_settings['params']:
                    return server_settings['params'][key]

        # Return default value
        if param['type'] == 'select' and param['value_type'] == 'multiple':
            return [option['key'] for option in param['options'] if option['default']]
        else:
            return param['default']

    def is_long_strip(self, data):
        """
        Returns True if the manga is a long strip, False otherwise.

        The server shall not modify `data` to form the return value.
        """
        if not self.long_strip_genres:
            return False

        for genre in data['genres']:
            if genre in self.long_strip_genres:
                return True

        return False

    def is_up(self):
        if self.id == 'local':
            return True

        if self.base_url is None:
            # base_url is customizable in settings and stored in keyring
            if credential := self.get_credential():
                self.base_url = credential.address
            else:
                return False

        try:
            requests.get(self.base_url, headers={'User-Agent': USER_AGENT})
        except Exception:
            return False

        return True

    def load_session(self):
        """ Load previous session from disk """

        file_path = os.path.join(self.sessions_dir, '{0}.pickle'.format(get_server_main_id_by_id(self.id)))
        if not os.path.exists(file_path):
            return False

        with open(file_path, 'rb') as f:
            unpickled_session = pickle.load(f)
            if self.http_client == 'requests' and isinstance(unpickled_session, requests.sessions.Session):
                # Pickle data is a `requests` session
                self.session = unpickled_session

            elif self.http_client == 'curl_cffi' and isinstance(unpickled_session, dict):
                # Pickle data is `dict` object containing cookies and headers
                cookie_jar = CookieJar()
                for _domain, dcookies in unpickled_session['cookies'].items():
                    for _path, pcookies in dcookies.items():
                        for _name, cookie in pcookies.items():
                            cookie_jar.set_cookie(cookie)

                self.session = crequests.Session(
                    allow_redirects=True,
                    impersonate='chrome',
                    timeout=(REQUESTS_TIMEOUT, REQUESTS_TIMEOUT * 2),
                    cookies=cookie_jar,
                    headers=unpickled_session['headers']
                )

            else:
                return False

        return True

    def login(self, _username, _password):
        return False

    def save_logo(self):
        return self.save_image(
            self.logo_url, os.path.join(get_cached_logos_dir(), 'servers'), get_server_main_id_by_id(self.id),
            LOGO_SIZE, LOGO_SIZE, keep_aspect_ratio=False, format='PNG'
        )

    def save_session(self):
        """ Save session to disk (cache) """

        file_path = os.path.join(self.sessions_dir, '{0}.pickle'.format(get_server_main_id_by_id(self.id)))
        with open(file_path, 'wb') as f:
            if self.http_client == 'requests':
                pickle.dump(self.session, f)

            elif self.http_client == 'curl_cffi':
                pickle.dump({'cookies': self.session.cookies.jar._cookies, 'headers': self.session.headers}, f)

    @abstractmethod
    def search(self, term=None):
        """This method must return a dictionary.

        Data are usually obtained:
        - by scrapping an HTML page
        - or by parsing the response of a request to an API.

        By convention, returned dict MUST contain the following keys:
        - slug: A slug (str) allowing to forge URL of the HTML page of the manga
        - url: URL of manga HTML page if `slug` is not usable
        - name: Name of the manga
        - cover: Absolute URL of the manga cover [optional]
        - last_chapter: last chapter available [optional]
        - nb_chapters: number of chapters available [optional]

        The data are passed to `get_manga_data` method.

        .. note:: It's of course possible to add any other information/keys if necessary
        .. warning:: but these must not be present in the return value of `get_manga_data`.
        """

    def update_chapter_read_progress(self, data, manga_slug, manga_name, chapter_slug, chapter_url):
        return NotImplemented


class ServerDummy(Server):
    """
    Used as fallback in case the server for a comic in the library has been removed
    """

    def __init__(self, id):
        self.id = id
        self.name = id
        self.lang = None

    def get_manga_data(self, initial_data):
        return None

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        return None

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        return None

    def get_manga_url(self, slug, url):
        return None

    def search(self, term=None):
        return None


def init_servers_modules(use_external_servers_modules, reload_modules=False):
    # Add a first Finder with HIGH priority
    server_finder = ServerFinder(priority=ServerFinderPriority.HIGH)
    server_finder.add_path(os.environ.get('KOMIKKU_SERVERS_PATH'))

    if use_external_servers_modules:
        # A single Finder is sufficient
        server_finder.add_path(os.path.join(get_cache_dir(), 'servers/repo'))
        server_finder.install()
    else:
        # Install first Finder
        server_finder.install()

        # Add a second Finder with LOW priority
        # Once installed, external servers modules must still be accessible, as one or more new servers modules
        # (not present in the application servers modules) may potentially have been used
        # (i.e. comics from these servers modules have been added to the library).
        server_finder = ServerFinder(ServerFinderPriority.LOW)
        server_finder.add_path(os.path.join(get_cache_dir(), 'servers/repo'))
        server_finder.install()


def install_servers_modules_from_repo(app_version):
    """
    Installs (or updates) a alternative version of servers modules from the source code repository.

    The intention is to be able to use the most up-to-date versions of servers modules,
    including new servers, without waiting for a new version of the application.

    Can only work if the application version is greater than or equal to the minimum version
    required in the index.json file.
    """
    repo_url = 'https://febvre.info'
    dest_path = os.path.join(get_cache_dir(), 'servers/repo')
    index_path = os.path.join(dest_path, 'index.json')

    session = retry_session()
    session.headers.update({'User-Agent': f'komikku-{app_version}'})

    def install_zip(current_hash=None):
        # Get remote index.json
        url = repo_url + '/komikku/index.json'
        try:
            r = session.get(url)
        except Exception:
            return None, None

        if r.status_code != 200:
            return None, None

        try:
            app_min_version = json.loads(r.content)['app_min_version']
        except Exception:
            return None, None

        if app_min_version and app_version < app_min_version:
            return False, 'forbidden'

        if current_hash:
            remote_hash = hashlib.sha256(r.content).hexdigest()
            if current_hash == remote_hash:
                return False, 'unchanged'

        url = repo_url + '/komikku/servers.zip'
        try:
            r = session.get(url)
        except Exception:
            return None, None

        if r.status_code != 200:
            return None, None

        with zipfile.ZipFile(BytesIO(r.content)) as zip:
            for zip_info in zip.infolist():
                if zip_info.is_dir():
                    continue

                zip.extract(zip_info, dest_path)

        return True, 'updated' if current_hash else 'created'

    if not os.path.exists(dest_path) or not os.path.exists(index_path):
        os.makedirs(dest_path, exist_ok=True)

        return install_zip()

    # Compute current index.json hash
    with open(index_path, 'rb') as fp:
        current_hash = hashlib.sha256(fp.read()).hexdigest()

    return install_zip(current_hash)
