# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import base64
import os
import re
from urllib.parse import parse_qs
from urllib.parse import urlparse

import requests

from komikku.consts import USER_AGENT
from komikku.trackers import authenticated
from komikku.trackers import Tracker
from komikku.webview import get_tracker_access_token

# https://myanimelist.net/apiconfig/references/api/v2


class Myanimelist(Tracker):
    id = 'myanimelist'
    name = 'MyAnimeList'
    client_id = '4d0e78e295a090211517bded6ebdaa49'

    base_url = 'https://myanimelist.net'
    logo_url = base_url + '/images/favicon.ico'
    auth_url = base_url + '/v1/oauth2'
    authorize_url = auth_url + '/authorize?response_type=code&client_id={0}&state={1}&code_challenge={2}&code_challenge_method=plain'
    access_token_url = auth_url + '/token'

    api_url = 'https://api.myanimelist.net/v2'
    api_search_url = api_url + '/manga'
    api_manga_url = api_url + '/manga/{0}'
    api_manga_update_url = api_manga_url + '/my_list_status'
    api_user_mangalist_url = api_url + '/users/@me/mangalist'
    manga_url = base_url + '/manga/{0}'

    RELEASE_STATUSES = {
        'discontinued': 'Cancelled',
        'finished': 'Finished',
        'on_hiatus': 'Hiatus',
        'not_yet_published': 'Not Yet Released',
        'currently_publishing': 'Releasing',
    }

    STATUSES_MAPPING = {
        # tracker status => internal status
        'reading': 'reading',
        'completed': 'completed',
        'on_hold': 'on_hold',
        'dropped': 'dropped',
        'plan_to_read': 'plan_to_read',
        'rereading': 'rereading',  # Do not exists
    }

    USER_SCORE_FORMAT = {
        'min': 0,
        'max': 10,
        'step': 1,
        'raw_factor': 1,
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT})

    def get_manga_url(self, id):
        return self.manga_url.format(id)

    @authenticated
    def get_tracker_manga_data(self, id, access_token=None):
        r = self.session.get(
            self.api_manga_url.format(id),
            params={
                'fields': 'id,num_chapters,title',
            },
            headers={
                'Authorization': f'Bearer {access_token}',
            }
        )
        if r.status_code == 401:
            if self.refresh_access_token():
                return self.get_tracker_manga_data(id)

        elif r.status_code != 200:
            return None

        data = r.json()

        return {
            'id': data['id'],
            'name': data['title'],
            'chapters': data['num_chapters'],
            'score_format': None,
        }

    def get_user_score_format(self, format):
        return self.USER_SCORE_FORMAT

    @authenticated
    def get_user_manga_data(self, id, access_token=None):
        r = self.session_get(
            self.api_user_mangalist_url,
            params={
                'limit': 1000,
                'fields': 'id,my_list_status,num_chapters,title',
            },
            headers={
                'Authorization': f'Bearer {access_token}',
            }
        )
        if r.status_code == 401:
            if self.refresh_access_token():
                return self.get_user_manga_data(id)

        elif r.status_code != 200:
            return None

        data = None
        for item in r.json()['data']:
            if item['node']['id'] != id:
                continue

            if status := item['node']['my_list_status'].get('status'):
                status = self.STATUSES_MAPPING[status]
            else:
                status = 'reading'
            if status == 'reading' and item['node']['my_list_status']['is_rereading']:
                status = 'rereading'

            data = {
                'id': item['node']['id'],
                'name': item['node']['title'],
                'chapters': item['node']['num_chapters'],
                'chapters_progress': item['node']['my_list_status']['num_chapters_read'],
                'score': item['node']['my_list_status']['score'],
                'score_format': None,
                'status': status,
            }

        return data

    def refresh_access_token(self):
        r = self.session.post(
            self.access_token_url,
            auth=(self.client_id, ''),
            data={
                'grant_type': 'refresh_token',
                'refresh_token': self.data['refresh_token'],
            },
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
            }
        )

        if r.status_code != 200:
            return None

        data = r.json()

        self.data = {
            'access_token': data['access_token'],
            'refresh_token': data['refresh_token'],
        }

        return data['access_token']

    def request_access_token(self):
        code_verifier = base64.urlsafe_b64encode(os.urandom(40)).decode('utf-8')
        code_verifier = re.sub('[^a-zA-Z0-9]+', '', code_verifier)
        state = 'komikku'

        authorize_url = self.authorize_url.format(self.client_id, state, code_verifier)

        redirect_url, error = get_tracker_access_token(authorize_url, self.app_redirect_url)

        if error:
            return False, error

        qs = parse_qs(urlparse(redirect_url).query)
        if qs['state'][0] != state:
            return False, 'failed'

        code = qs['code'][0]

        r = self.session.post(
            self.access_token_url,
            data={
                'client_id': self.client_id,
                'grant_type': 'authorization_code',
                'code': code,
                'code_verifier': code_verifier,
            },
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
            }
        )

        if r.status_code != 200:
            return False, 'failed'

        data = r.json()
        self.data = {
            'access_token': data['access_token'],
            'refresh_token': data['refresh_token'],
        }

        return True, None

    @authenticated
    def search(self, term, access_token=None):
        r = self.session.get(
            self.api_search_url,
            params={
                'q': term,
                'limit': 100,
                'fields': 'id,title,main_picture,status,synopsis,genres,authors{first_name,last_name},mean,start_date',
            },
            headers={
                'Authorization': f'Bearer {access_token}',
            }
        )
        if r.status_code == 401:
            if self.refresh_access_token():
                return self.search(term)

        elif r.status_code != 200:
            return None

        results = []
        for item in r.json()['data']:
            authors = []
            if item['node'].get('authors'):
                for author in item['node']['authors']:
                    full = f'{author["node"]["first_name"]} {author["node"]["last_name"]}'.strip()
                    if author['role']:
                        full = f'{full} ({author["role"]})'
                    authors.append(full)

            results.append({
                'id': item['node']['id'],
                'authors': ', '.join(authors),
                'cover': item['node']['main_picture']['medium'] if item['node'].get('main_picture') else None,
                'name': item['node']['title'],
                'score': item['node']['mean'] if item['node'].get('mean') else None,
                'start_date': item['node']['start_date'][:4] if item['node'].get('start_date') else None,
                'status': self.RELEASE_STATUSES.get(item['node']['status']),
                'synopsis': item['node']['synopsis'],
            })

        return results

    @authenticated
    def update_user_manga_data(self, id, data, access_token=None):
        update_data = data.copy()

        # chapters_progress => num_chapters_read
        num_chapters_read = update_data.pop('chapters_progress', None)
        if num_chapters_read is not None:
            update_data['num_chapters_read'] = num_chapters_read

        if update_data.get('status') == 'rereading':
            update_data['status'] = 'reading'
            update_data['is_rereading'] = True

        update_data['status'] = self.convert_internal_status(update_data['status'])

        r = self.session_put(
            self.api_manga_update_url.format(id),
            data=update_data,
            headers={
                'Authorization': f'Bearer {access_token}',
            }
        )
        if r.status_code == 401:
            if self.refresh_access_token():
                return self.update_user_manga_data(id, data)

        elif r.status_code != 200:
            return False

        return True
