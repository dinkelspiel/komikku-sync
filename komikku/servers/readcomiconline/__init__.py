# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import base64
from bs4 import BeautifulSoup
import logging
import re
from urllib.parse import unquote

try:
    # This server requires JA3/TLS and HTTP2 fingerprints impersonation
    from curl_cffi import requests
except Exception:
    # Server will be disabled
    requests = None

from komikku.servers import Server
from komikku.servers.utils import convert_date_string
from komikku.utils import get_buffer_mime_type
from komikku.utils import is_number
from komikku.webview import CompleteChallenge

logger = logging.getLogger('komikku.servers.readcomiconline')


class Readcomiconline(Server):
    id = 'readcomiconline'
    name = 'Read Comic Online'
    lang = 'en'
    is_nsfw = True
    status = 'enabled' if requests is not None else 'disabled'

    has_cf = True
    has_captcha = True  # Custom captcha AreYouHuman2
    http_client = 'curl_cffi'

    base_url = 'https://rcostation.xyz'
    latest_updates_url = base_url + '/ComicList/LatestUpdate'
    most_populars_url = base_url + '/ComicList/MostPopular'
    search_url = base_url + '/AdvanceSearch'
    manga_url = base_url + '/Comic/{0}'
    chapter_url = base_url + '/Comic/{0}/{1}?s=&quality=hq#1'
    bypass_cf_url = base_url + '/Comic/Invincible/Issue-1#1'

    def __init__(self):
        self.session = None

    @CompleteChallenge()
    def get_manga_data(self, initial_data):
        """
        Returns comic data by scraping manga HTML page content

        Initial data should contain at least comic's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug'], 1))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],  # not available
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        soup = BeautifulSoup(r.text, 'lxml')

        info_element = soup.select_one('#leftside .barContent')

        data['name'] = info_element.select_one('.bigChar').text.strip()
        cover_path = soup.select_one('#rightside img').get('src')
        if cover_path.startswith('http'):
            data['cover'] = cover_path
        else:
            data['cover'] = '{0}{1}'.format(self.base_url, cover_path)

        for p_element in info_element.select('p'):
            if not p_element.span:
                if not data['synopsis']:
                    data['synopsis'] = p_element.text.strip()
                continue

            span_element = p_element.span.extract()
            label = span_element.text.strip()

            if label.startswith('Genres'):
                data['genres'] = [a_element.text.strip() for a_element in p_element.select('a')]

            elif label.startswith(('Writer', 'Artist')):
                for a_element in p_element.select('a'):
                    value = a_element.text.strip()
                    if value not in data['authors']:
                        data['authors'].append(value)

            elif label.startswith('Status'):
                value = p_element.text.strip()
                if 'Completed' in value:
                    data['status'] = 'complete'
                elif 'Ongoing' in value:
                    data['status'] = 'ongoing'

        # Chapters (Issues)
        for tr_element in reversed(soup.select('.listing tr')):
            td_elements = tr_element.select('td')
            if not td_elements:
                continue

            slug = td_elements[0].a.get('href').split('?')[0].split('/')[-1]
            num = slug.split('-')[-1] if slug.startswith('Issue-') else None

            data['chapters'].append(dict(
                slug=slug,
                title=td_elements[0].a.text.strip(),
                num=num if is_number(num) else None,
                date=convert_date_string(td_elements[1].text.strip(), format='%m/%d/%Y'),
            ))

        return data

    @CompleteChallenge()
    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns comic chapter data
        """
        def decode_url(url, substitutions, base_url):
            # In `Scripts/rguard.min.js?v=1.5.8`
            if not url.startswith('https'):
                for substitution in substitutions:
                    url = url.replace(substitution[0], substitution[1])

                if '?' in url:
                    url, qs = url.split('?')
                else:
                    qs = None

                if '=s0' in url:
                    url = url.replace('=s0', '')
                    s = '=s0'
                elif '=s1600' in url:
                    url = url.replace('=s1600', '')
                    s = '=s1600'

                url = url[15:33] + url[50:]
                url = url[0:len(url) - 11] + url[len(url) - 2] + url[len(url) - 1]
                url = unquote(unquote(base64.b64decode(url)))
                url = 'https://2.bp.blogspot.com/' + url[0:13] + url[17:-2] + s
                if qs:
                    url += '?' + qs

            if base_url and base_url != '' and url.find('ip=') > 0:
                url = url.replace('https://2.bp.blogspot.com', base_url)

            return url

        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        var_rnd_name = None
        encoded_urls = []
        substitutions = []
        media_server = None
        for script_element in soup.select('script'):
            script = script_element.string
            if not script or ('var pth' not in script and 'replace(' not in script):
                continue

            for line in script.split('\n'):
                line = line.strip()

                # URLs (encoded) are stored in a variable with a random name
                if var_rnd_name is None:
                    # Search for a line of the form:
                    # var _1oXikvMxnz = '';
                    if matches := re.search(r"var\s+_([0-9a-zA-Z]+)\s+=\s+''", line):
                        var_rnd_name = '_' + matches.group(1)

                if var_rnd_name and line.startswith(var_rnd_name):
                    encoded_urls.append(line.split()[2][1:-2])

                elif 'replace(' in line:
                    if matches := re.search(r"replace\(/([a-zA-Z0-9_]+)/g, '([a-z])'\);", line):
                        substitutions.append((matches.group(1), matches.group(2)))

        data = dict(
            pages=[],
        )

        for index, url in enumerate(encoded_urls):
            data['pages'].append(dict(
                image=decode_url(url, substitutions, media_server),
                slug=None,
                index=index + 1,
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(
            page['image'] + '&t=10',
            headers={
                'Alt-Used': '2.bp.blogspot.com',
            }
        )

        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=f"{page['index']}.{mime_type.split('/')[1]}",
        )

    def get_manga_url(self, slug, url):
        """
        Returns comic absolute URL
        """
        return self.manga_url.format(slug)

    def get_manga_list(self, term=None, orderby=None):
        results = []

        if term:
            r = self.session_get(
                self.search_url,
                params=dict(
                    comicName=term,
                    ig='',
                    eg='',
                    status='',
                    pubDate='',
                ),
                headers={
                    'Referer': self.search_url,
                }
            )
        elif orderby == 'populars':
            r = self.session_get(self.most_populars_url)
        elif orderby == 'latest':
            r = self.session_get(self.latest_updates_url)
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        for a_element in soup.select('.item > a:first-child'):
            if not a_element.get('href'):
                continue

            cover = a_element.img.get('src')
            if not cover.startswith('http'):
                cover = self.base_url + cover

            results.append(dict(
                name=a_element.span.text.strip(),
                slug=a_element.get('href').split('/')[-1],
                cover=cover,
            ))

        return results

    @CompleteChallenge()
    def get_latest_updates(self):
        """
        Returns latest updates
        """
        return self.get_manga_list(orderby='latest')

    @CompleteChallenge()
    def get_most_populars(self):
        """
        Returns most popular comics
        """
        return self.get_manga_list(orderby='populars')

    @CompleteChallenge()
    def search(self, term):
        return self.get_manga_list(term=term)
