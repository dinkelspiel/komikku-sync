# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from collections import deque
from gettext import gettext as _
import logging
import os
import platform
import threading
import time
import tzlocal
from urllib.parse import urlsplit

try:
    from curl_cffi import requests as crequests
except Exception:
    crequests = None
import gi
import requests

gi.require_version('Adw', '1')
gi.require_version('WebKit', '6.0')

from gi.repository import Adw
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import WebKit

from komikku.consts import REQUESTS_TIMEOUT
from komikku.models import create_db_connection
from komikku.models.database import execute_sql
from komikku.servers.exceptions import ChallengerError
from komikku.servers.utils import get_session_cookies
from komikku.utils import get_webview_data_dir

CF_RELOAD_MAX = 3
DEBUG = False

logger = logging.getLogger('komikku.webview')


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/webview.ui')
class WebviewPage(Adw.NavigationPage):
    __gtype_name__ = 'WebviewPage'
    __gsignals__ = {
        'cancelled': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    toolbarview = Gtk.Template.Child('toolbarview')
    title = Gtk.Template.Child('title')

    challenger = None  # Current challenger
    challengers = deque()  # List of pending challengers
    concurrent_lock = threading.RLock()
    exited = True  # Whether webview has been exited (page has been popped)
    exited_auto = False  # Whether webview has been automatically left (no user interaction)
    handlers_ids = []  # List of handlers IDs (connected events)
    handlers_webview_ids = []  # List of hendlers IDs (connected events to WebKit.WebView)
    lock = False  # Whether webview is locked (in use)

    def __init__(self, window):
        Adw.NavigationPage.__init__(self)

        self.window = window

        self.connect('hidden', self.on_hidden)

        # User agent: Gnome Web like
        cpu_arch = platform.machine()
        session_type = GLib.getenv('XDG_SESSION_TYPE')
        session_type = session_type.capitalize() if session_type else 'Wayland'
        custom_part = f'{session_type}; Linux {cpu_arch}'  # noqa: E702
        self.user_agent = f'Mozilla/5.0 ({custom_part}) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/60.5 Safari/605.1.15'

        # Settings
        self.settings = WebKit.Settings.new()
        self.settings.set_enable_developer_extras(DEBUG)
        self.settings.set_enable_write_console_messages_to_stdout(DEBUG)

        # Enable extra features
        all_feature_list = self.settings.get_all_features()
        if DEBUG:
            experimental_feature_list = self.settings.get_experimental_features()
            development_feature_list = self.settings.get_development_features()
            experimental_features = [
                experimental_feature_list.get(index).get_identifier() for index in range(experimental_feature_list.get_length())
            ]
            development_features = [
                development_feature_list.get(index).get_identifier() for index in range(development_feature_list.get_length())
            ]

            # Categories: Security, Animation, JavaScript, HTML, Other, DOM, Privacy, Media, Network, CSS
            for index in range(all_feature_list.get_length()):
                feature = all_feature_list.get(index)
                if feature.get_identifier() in experimental_features:
                    type = 'Experimental'
                elif feature.get_identifier() in development_features:
                    type = 'Development'
                else:
                    type = 'Stable'
                if feature.get_category() == 'Other' and not feature.get_default_value():
                    print('ID: {0}, Default: {1}, Category: {2}, Details: {3}, type: {4}'.format(
                        feature.get_identifier(),
                        feature.get_default_value(),
                        feature.get_category(),
                        feature.get_details(),
                        type
                    ))

        extra_features_enabled = (
            'AllowDisplayOfInsecureContent',
            'AllowRunningOfInsecureContent',
            'JavaScriptCanAccessClipboard',
        )
        for index in range(all_feature_list.get_length()):
            feature = all_feature_list.get(index)
            if feature.get_identifier() in extra_features_enabled and not feature.get_default_value():
                self.settings.set_feature_enabled(feature, True)

        # Context
        self.web_context = WebKit.WebContext(time_zone_override=tzlocal.get_localzone_name())
        self.web_context.set_cache_model(WebKit.CacheModel.DOCUMENT_VIEWER)
        self.web_context.set_preferred_languages(['en-US', 'en'])

        # Network session
        self.network_session = WebKit.NetworkSession.new(
            os.path.join(get_webview_data_dir(), 'data'),
            os.path.join(get_webview_data_dir(), 'cache')
        )
        self.network_session.get_website_data_manager().set_favicons_enabled(True)
        self.network_session.set_itp_enabled(False)
        self.network_session.get_cookie_manager().set_accept_policy(WebKit.CookieAcceptPolicy.ALWAYS)
        self.network_session.get_cookie_manager().set_persistent_storage(
            os.path.join(get_webview_data_dir(), 'cookies.sqlite'),
            WebKit.CookiePersistentStorage.SQLITE
        )

        # Create Webview
        self.webkit_webview = WebKit.WebView(
            web_context=self.web_context,
            network_session=self.network_session,
            settings=self.settings
        )

        self.toolbarview.set_content(self.webkit_webview)
        self.window.navigationview.add(self)

    def cancel_challengers(self, server_ids, context=None):
        # Cancel pendings
        if self.challengers:
            with self.concurrent_lock:
                for challenger in self.challengers.copy():
                    if context and challenger.context != context:
                        continue

                    if challenger.server.id not in server_ids or self.challenger.server.id == challenger.server.id:
                        continue

                    challenger.cancel()
                    self.challengers.remove(challenger)

        # Cancel current
        if self.challenger and self.challenger.server.id in server_ids:
            self.challenger.cancel()
            self.exit()
            self.close_page()

    def clear_data(self, on_finish_callback):
        def on_finish(data_manager, result):
            # Clear cookies in SQLite DB
            if con := create_db_connection(os.path.join(get_webview_data_dir(), 'cookies.sqlite')):
                execute_sql(con, 'DELETE FROM moz_cookies;')

            on_finish_callback(data_manager.clear_finish(result))

        self.network_session.get_website_data_manager().clear(WebKit.WebsiteDataTypes.ALL, 0, None, on_finish)

    def close_page(self, blank=True):
        self.disconnect_all_signals()

        if blank:
            self.webkit_webview.stop_loading()
            GLib.idle_add(self.webkit_webview.load_uri, 'about:blank')

        def do_next():
            if not self.exited:
                return GLib.SOURCE_CONTINUE

            self.lock = False
            self.pop_challenger()

            return GLib.SOURCE_REMOVE

        if self.challenger:
            # Wait page is exited to unlock and load next pending challenger (if exists)
            GLib.idle_add(do_next)
        else:
            self.exited = True
            self.lock = False

        logger.debug('Page closed')

    def connect_signal(self, *args):
        handler_id = self.connect(*args)
        self.handlers_ids.append(handler_id)

    def connect_webview_signal(self, *args):
        handler_id = self.webkit_webview.connect(*args)
        self.handlers_webview_ids.append(handler_id)

    def disconnect_all_signals(self):
        for handler_id in self.handlers_ids:
            self.disconnect(handler_id)

        self.handlers_ids = []

        for handler_id in self.handlers_webview_ids:
            self.webkit_webview.disconnect(handler_id)

        self.handlers_webview_ids = []

    def exit(self):
        if self.window.page != self.props.tag:
            # Page has already been popped or has never been pushed (no challenge)
            # No need to wait `hidden` event to flag it as exited
            self.exited = True
            return

        self.exited_auto = True
        self.window.navigationview.pop()

    def load_page(self, uri=None, challenger=None, user_agent=None, auto_load_images=True):
        if self.lock or not self.exited:
            # Already in use or page exiting is not ended (pop animation not ended)
            return False

        self.lock = True
        self.exited = False
        self.exited_auto = False

        self.webkit_webview.get_settings().set_user_agent(user_agent or self.user_agent)
        self.webkit_webview.get_settings().set_auto_load_images(auto_load_images)

        self.challenger = challenger
        if self.challenger:
            self.connect_webview_signal('load-changed', self.challenger.on_load_changed)
            self.connect_webview_signal('load-failed', self.challenger.on_load_failed)
            self.connect_webview_signal('notify::title', self.challenger.on_title_changed)
            uri = self.challenger.url

        logger.debug('Load page %s', uri)

        GLib.idle_add(self.webkit_webview.load_uri, uri)

        return True

    def on_hidden(self, _page):
        self.exited = True

        if self.challenger and self.challenger.error:
            # Cancel all pending challengers with same URL if challenge was not completed
            for challenger in self.challengers.copy():
                if challenger.url == self.challenger.url:
                    self.challengers.remove(challenger)
                    challenger.cancel()
                    break

        if not self.exited_auto:
            if self.challenger:
                # Webview has been left via a user interaction (back button, <ESC> key)
                self.challenger.cancel()
            else:
                self.emit('cancelled')

        if not self.exited_auto:
            self.close_page()

    def pop_challenger(self):
        if not self.challengers:
            return

        with self.concurrent_lock:
            if self.load_page(challenger=self.challengers[0]):
                self.challengers.popleft()

    def push_challenger(self, challenger):
        with self.concurrent_lock:
            self.challengers.append(challenger)

        self.pop_challenger()

    def show(self):
        self.window.navigationview.push(self)


class CompleteChallenge:
    """Allows user to complete a browser challenge using the Webview

    Several calls to this decorator can be concurrent. But only one will be honored at a time.
    """

    ALLOWED_METHODS = (
        'get_manga_data',
        'get_manga_chapter_data',
        'get_manga_chapter_page_image',
        'get_latest_updates',
        'get_most_populars',
        'search',
    )

    def __call__(self, func):
        assert func.__name__ in self.ALLOWED_METHODS, f'@{self.__class__.__name__} decorator is not allowed on method `{func.__name__}`'

        def wrapper(*args, **kwargs):
            if func.__name__ not in self.ALLOWED_METHODS:
                logger.error('@%s decorator is not allowed on method `%s`', self.__class__.__name__, func.__name__)
                return func(*args, **kwargs)

            server = args[0]
            url = server.bypass_cf_url or server.base_url

            if not server.has_cf and not server.has_captcha:
                return func(*args, **kwargs)

            # Test CF challenge cookie
            if server.has_cf and not server.has_captcha:
                if server.session is None:
                    # Try loading a previous session
                    server.load_session()

                if server.session:
                    logger.debug(f'{server.id}: Previous session found')

                    # Locate CF challenge cookie
                    cf_cookie_found = False
                    for cookie in get_session_cookies(server.session):
                        if cookie.name == 'cf_clearance':
                            logger.debug(f'{server.id}: Session has CF challenge cookie')
                            cf_cookie_found = True
                            break

                    if cf_cookie_found:
                        # Check session validity
                        logger.debug(f'{server.id}: Checking session...')
                        r = server.session_get(url)
                        if r.ok:
                            logger.debug(f'{server.id}: Session OK')
                            return func(*args, **kwargs)

                        logger.debug(f'{server.id}: Session KO ({r.status_code})')
                    else:
                        logger.debug(f'{server.id}: Session has no CF challenge cookie')

            webview = Gio.Application.get_default().window.webview
            challenger = Challenger(server, webview, func.__name__)
            webview.push_challenger(challenger)

            while not challenger.done and challenger.error is None:
                time.sleep(1)

            if challenger.error:
                logger.info(challenger.error)
                raise ChallengerError()
            else:
                return func(*args, **kwargs)

        return wrapper


class Challenger:
    def __init__(self, server, webview, context):
        self.server = server
        self.webview = webview
        self.context = context
        self.url = self.server.bypass_cf_url or self.server.base_url

        self.cf_reload_count = 0
        self.done = False
        self.error = None
        self.last_load_event = None

    def cancel(self):
        self.error = f'Challenge completion aborted: {self.server.id}'

    def monitor_challenge(self):
        # Detect captcha via JavaScript in current page
        # - Cloudflare challenge
        # - DDoS-Guard
        # - Google ReCAPTCHA
        # - AreYouHuman2 (2/3 images to identify)
        # - Challange (browser identification, no user interaction)
        #
        # - A captcha is detected: change title to 'cf_captcha', 're_captcha',...
        # - No challenge found: change title to 'ready'
        # - An error occurs during challenge: change title to 'error'
        js = """
            let intervalID = setInterval(() => {
                if (document.readyState === 'loading') {
                    return;
                }

                if (document.getElementById('challenge-error-title')) {
                    // CF error: Browser is outdated?
                    document.title = 'error';
                    clearInterval(intervalID);
                }
                else if (document.querySelector('.main-wrapper[role="main"] .main-content') || document.querySelector('.ray-id')) {
                    document.title = 'cf_captcha';
                }
                else if (document.querySelector('#request-info')) {
                    document.title = 'ddg_captcha';
                }
                else if (document.querySelector('.g-recaptcha') && !document.querySelector('form .g-recaptcha')) {
                    // Google reCAPTCHA
                    // Not in a form to avoid false positives (login form for ex.)
                    document.title = 're_captcha';
                }
                else if (document.querySelector('#formVerify')) {
                    document.title = 'ayh2_captcha';
                }
                else if (document.querySelector('script[src*="challange"]')) {
                    document.title = 'challange_captcha';
                }
                else {
                    document.title = 'ready';
                    clearInterval(intervalID);
                }
            }, 100);
        """
        self.webview.webkit_webview.evaluate_javascript(js, -1)

    def on_load_changed(self, _webkit_webview, event):
        logger.debug(f'Load changed: {event} {self.webview.webkit_webview.get_uri()}')

        if event != WebKit.LoadEvent.REDIRECTED and '__cf_chl_tk' in self.webview.webkit_webview.get_uri():
            # Challenge has been passed
            self.webview.title.set_title(_('Please wait…'))

            # Disable images auto-load
            logger.debug('Disable images automatic loading')
            self.webview.webkit_webview.get_settings().set_auto_load_images(False)

        elif event == WebKit.LoadEvent.COMMITTED or \
                (event == WebKit.LoadEvent.FINISHED and self.last_load_event != WebKit.LoadEvent.COMMITTED):
            # Normally, COMMITTED (2) event is received and then FINISHED (3) event.
            # The challenge can be monitored as soon as COMMITTED event is emitted,
            # but sometimes it isn't, so we have to wait for FINISHED event.
            self.monitor_challenge()

        self.last_load_event = event

    def on_load_failed(self, _webkit_webview, _event, uri, _gerror):
        self.error = f'Challenge completion error: failed to load URI {uri}'

        self.webview.exit()
        self.webview.close_page()

    def on_title_changed(self, _webkit_webview, _title):
        title = self.webview.webkit_webview.props.title
        logger.debug(f'Title changed: {title}')

        if title == 'error':
            # CF error message detected
            # settings or a features related?
            self.error = 'CF challenge completion error'
            self.webview.exit()
            self.webview.close_page()
            return

        if title.endswith('_captcha'):
            if title == 'cf_captcha':
                self.cf_reload_count += 1
            if self.cf_reload_count > CF_RELOAD_MAX:
                self.error = 'CF challenge completion error: max reload exceeded'
                self.webview.exit()
                self.webview.close_page()
                return

            if title == 'cf_captcha':
                logger.debug(f'{self.server.id}: CF captcha detected, try #{self.cf_reload_count}')
            elif title == 'ddg_captcha':
                logger.debug(f'{self.server.id}: DDoS-Guard detected')
            elif title == 're_captcha':
                logger.debug(f'{self.server.id}: ReCAPTCHA detected')
            elif title == 'ayh2_captcha':
                logger.debug(f'{self.server.id}: AreYouHuman2 detected')
            elif title == 'challange_captcha':
                logger.debug(f'{self.server.id}: Challange detected')

            # Show webview, user must complete a CAPTCHA
            if self.webview.window.page != self.webview.props.tag:
                self.webview.title.set_title(_('Please complete CAPTCHA'))
                self.webview.title.set_subtitle(self.server.name)
                self.webview.show()

        if title != 'ready':
            return

        # Challenge has been passed and page is loaded
        # Webview should not be closed, we need to store cookies first
        self.webview.exit()

        logger.debug(f'{self.server.id}: Page loaded, getting cookies...')
        self.webview.network_session.get_cookie_manager().get_cookies(
            self.url, None, self.on_get_cookies_finished, None
        )

    def on_get_cookies_finished(self, cookie_manager, result, _user_data):
        if self.server.http_client == 'requests':
            self.server.session = requests.Session()

        elif crequests is not None and self.server.http_client == 'curl_cffi':
            self.server.session = crequests.Session(
                allow_redirects=True,
                impersonate='chrome',
                timeout=(REQUESTS_TIMEOUT, REQUESTS_TIMEOUT * 2)
            )

        else:
            self.error = f'{self.server.id}: Failed to copy Webview cookies in session (no HTTP client found)'
            self.webview.close_page()
            return

        # Set default headers
        self.server.session.headers.update(self.server.headers or {'User-Agent': self.webview.user_agent})

        # Copy libsoup cookies in session cookies jar
        cf_cookie_found = False
        rcookies = []
        for cookie in cookie_manager.get_cookies_finish(result):
            rcookies.append(requests.cookies.create_cookie(
                name=cookie.get_name(),
                value=cookie.get_value(),
                domain=cookie.get_domain(),
                path=cookie.get_path(),
                expires=cookie.get_expires().to_unix() if cookie.get_expires() else None,
                rest={'HttpOnly': cookie.get_http_only()},
                secure=cookie.get_secure(),
            ))
            if cookie.get_name() == 'cf_clearance':
                cf_cookie_found = True

        if not cf_cookie_found:
            # Server don't used Cloudflare (temporarily or not at all)
            # Create a fake `cf_clearance` cookie, so as not to try to detect the challenge next time
            rcookies.append(requests.cookies.create_cookie(
                name='cf_clearance',
                value='74k3',
                domain=urlsplit(self.url).netloc,
                path='/',
            ))

        for rcookie in rcookies:
            if self.server.http_client == 'requests':
                self.server.session.cookies.set_cookie(rcookie)

            elif self.server.http_client == 'curl_cffi':
                self.server.session.cookies.jar.set_cookie(rcookie)

        logger.debug(f'{self.server.id}: Webview cookies successfully copied in session')
        self.server.save_session()

        self.done = True
        self.webview.close_page()


def eval_js(code):
    error = None
    res = None
    webview = Gio.Application.get_default().window.webview

    def load_page():
        if not webview.load_page(uri='about:blank'):
            return True

        webview.connect_webview_signal('load-changed', on_load_changed)

    def on_evaluate_javascript_finish(_webkit_webview, result, _user_data=None):
        nonlocal error
        nonlocal res

        try:
            js_result = webview.webkit_webview.evaluate_javascript_finish(result)
        except GLib.GError:
            error = 'Failed to eval JS code'
        else:
            if js_result.is_string():
                res = js_result.to_string()

            if res is None:
                error = 'Failed to eval JS code'

        webview.close_page()

    def on_load_changed(_webkit_webview, event):
        if event != WebKit.LoadEvent.FINISHED:
            return

        webview.webkit_webview.evaluate_javascript(code, -1, None, None, None, on_evaluate_javascript_finish)

    GLib.timeout_add(100, load_page)

    while res is None and error is None:
        time.sleep(1)

    if error:
        logger.warning(error)
        raise requests.exceptions.RequestException()

    return res


def get_page_html(url, user_agent=None, wait_js_code=None, with_cookies=False):
    cookies = None
    error = None
    html = None
    webview = Gio.Application.get_default().window.webview

    def load_page():
        if not webview.load_page(uri=url, user_agent=user_agent, auto_load_images=False):
            return True

        webview.connect_webview_signal('load-changed', on_load_changed)
        webview.connect_webview_signal('load-failed', on_load_failed)
        webview.connect_webview_signal('notify::title', on_title_changed)

    def on_get_cookies_finished(cookie_manager, result, _user_data):
        nonlocal cookies

        rcookies = []
        # Get libsoup cookies
        for cookie in cookie_manager.get_cookies_finish(result):
            rcookie = requests.cookies.create_cookie(
                name=cookie.get_name(),
                value=cookie.get_value(),
                domain=cookie.get_domain(),
                path=cookie.get_path(),
                expires=cookie.get_expires().to_unix() if cookie.get_expires() else None,
                rest={'HttpOnly': cookie.get_http_only()},
                secure=cookie.get_secure(),
            )
            rcookies.append(rcookie)

        cookies = rcookies

        webview.close_page()

    def on_get_html_finish(_webkit_webview, result, _user_data=None):
        nonlocal error
        nonlocal html

        js_result = webview.webkit_webview.evaluate_javascript_finish(result)
        if js_result:
            html = js_result.to_string()

        if html is not None:
            if with_cookies:
                logger.debug('Page loaded, getting cookies...')
                webview.network_session.get_cookie_manager().get_cookies(url, None, on_get_cookies_finished, None)
            else:
                webview.close_page()
        else:
            error = f'Failed to get page html: {url}'
            webview.close_page()

    def on_load_changed(_webkit_webview, event):
        if event != WebKit.LoadEvent.FINISHED:
            return

        if wait_js_code:
            # Wait that everything needed has been loaded
            webview.webkit_webview.evaluate_javascript(wait_js_code, -1)
        else:
            webview.webkit_webview.evaluate_javascript('document.documentElement.outerHTML', -1, None, None, None, on_get_html_finish)

    def on_load_failed(_webkit_webview, _event, _uri, _gerror):
        nonlocal error

        error = f'Failed to load page: {url}'
        webview.close_page()

    def on_title_changed(_webkit_webview, _title):
        nonlocal error

        if webview.webkit_webview.props.title == 'ready':
            # Everything we need has been loaded, we can retrieve page HTML
            webview.webkit_webview.evaluate_javascript('document.documentElement.outerHTML', -1, None, None, None, on_get_html_finish)

        elif webview.webkit_webview.props.title == 'abort':
            error = f'Failed to get page html: {url}'
            webview.close_page()

    GLib.timeout_add(100, load_page)

    while (html is None or (with_cookies and cookies is None)) and error is None:
        time.sleep(1)

    if error:
        logger.warning(error)
        raise requests.exceptions.RequestException()

    return html if not with_cookies else (html, cookies)


def get_page_resources(url, paths, timeout=20, user_agent=None):
    """
    Returns all resources loaded by a page

    :param url: Page URL
    :param paths: List of paths to which resource URIs must match
    :param timeout: Timeout in seconds (optional)
    :param user_agent: User agent (optional)
    """

    data = None
    error = None
    resources = {}
    ts_start = None
    webview = Gio.Application.get_default().window.webview

    def load_page():
        nonlocal ts_start

        if not webview.load_page(uri=url, user_agent=user_agent, auto_load_images=False):
            return True

        ts_start = time.time()

        webview.connect_webview_signal('resource-load-started', on_resource_load_started)
        webview.connect_webview_signal('load-changed', on_load_changed)
        webview.connect_webview_signal('load-failed', on_load_failed)

    def on_load_changed(_webkit_webview, event):
        nonlocal data
        if event == WebKit.LoadEvent.FINISHED:
            data = resources

    def on_resource_load_started(_webkit_webview, resource, request):
        nonlocal resources

        uri = request.get_uri()
        if uri in resources:
            return

        found = False
        for path in paths:
            if path in uri:
                found = True
                break

        if not found:
            return

        resources[uri] = dict(
            uri=uri,
            resource=resource,
            request=request
        )

    def on_load_failed(_webkit_webview, _event, _uri, _gerror):
        nonlocal error

        error = f'Failed to load page: {url}'

    GLib.timeout_add(100, load_page)

    while (not ts_start or time.time() - ts_start < timeout) and data is None and error is None:
        time.sleep(1)

    if time.time() - ts_start > timeout:
        error = f'Failed to load page (timeout): {url}'

    webview.close_page()

    if error:
        logger.warning(error)
        raise requests.exceptions.RequestException()

    return list(data.values())


def get_tracker_access_token(url, app_redirect_url, user_agent=None):
    """Use webview to request a client access token to a tracker

    User will be asked to approve client permission.
    If user is not logged in, it will first be taken to the standard login page.

    :param url: Authorization request URL
    :param app_redirect_url: App redirection URL
    :param user_agent: User agent (optional)
    """

    error = None
    redirect_url = None
    webview = Gio.Application.get_default().window.webview

    def load_page():
        if not webview.load_page(uri=url, user_agent=user_agent):
            return False

        webview.connect_signal('cancelled', on_cancelled)
        webview.connect_webview_signal('load-changed', on_load_changed)
        webview.connect_webview_signal('load-failed', on_load_failed)

        # We assume that this function is always called from preferences
        # Preferences dialog must be closed before opening webview page
        webview.window.preferences.close()
        webview.show()

        return True

    def on_cancelled(self):
        nonlocal error
        error = 'cancelled'

    def on_load_changed(_webkit_webview, event):
        nonlocal redirect_url

        uri = _webkit_webview.get_uri()
        if event == WebKit.LoadEvent.REDIRECTED and uri.startswith(app_redirect_url):
            redirect_url = uri
            webview.exit()
            webview.close_page()

    def on_load_failed(_webkit_webview, _event, _uri, _gerror):
        nonlocal error
        error = 'failed'
        webview.exit()
        webview.close_page()

    if not load_page():
        error = 'locked'

    while redirect_url is None and error is None:
        time.sleep(1)

    if error != 'locked':
        # We assume that this function is always called from preferences
        # Preferences dialog must be re-opened after closing webview page
        webview.window.preferences.present(webview.window)

    return redirect_url, error
