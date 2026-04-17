# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import logging
from urllib.parse import parse_qs
from urllib.parse import urlparse

import requests

from komikku.consts import USER_AGENT
from komikku.trackers import authenticated
from komikku.trackers import Tracker
from komikku.webview import get_tracker_access_token

logger = logging.getLogger(__name__)

# https://docs.anilist.co/guide/graphql/
# https://studio.apollographql.com/sandbox/schema/reference


class Anilist(Tracker):
    id = 'anilist'
    name = 'AniList'
    client_id = '21273'

    base_url = 'https://anilist.co'
    logo_url = base_url + '/img/icons/favicon-32x32.png'
    authorize_url = f'{base_url}/api/v2/oauth/authorize?client_id={client_id}&response_type=token'
    api_url = 'https://graphql.anilist.co'
    manga_url = base_url + '/manga/{0}'

    RELEASE_STATUSES = {
        'CANCELLED': 'Cancelled',
        'FINISHED': 'Finished',
        'HIATUS': 'Hiatus',
        'NOT_YET_RELEASED': 'Not Yet Released',
        'RELEASING': 'Releasing',
    }

    STATUSES_MAPPING = {
        # tracker status => internal status
        'CURRENT': 'reading',
        'COMPLETED': 'completed',
        'PAUSED': 'on_hold',
        'DROPPED': 'dropped',
        'PLANNING': 'plan_to_read',
        'REPEATING': 'rereading',
    }

    USER_SCORES_FORMATS = {
        'POINT_100': {
            'min': 0,
            'max': 100,
            'step': 1,
            'raw_factor': 1,
        },
        'POINT_10_DECIMAL': {
            'min': 0,
            'max': 10,
            'step': .1,
            'raw_factor': 10,
        },
        'POINT_10': {
            'min': 0,
            'max': 10,
            'step': 1,
            'raw_factor': 10,
        },
        'POINT_5': {
            'min': 0,
            'max': 5,
            'step': 1,
            'raw_factor': 20,
        },
        'POINT_3': {
            'min': 0,
            'max': 3,
            'step': 1,
            'raw_factor': 100 / 3,
        },
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT})

    @authenticated
    def get_user(self, access_token=None):
        query = """
            query {
                Viewer {
                    id
                    mediaListOptions {
                        scoreFormat
                    }
                }
            }
        """
        r = self.session_post(
            self.api_url,
            json={
                'query': query,
            },
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
        )
        if r.status_code != 200:
            data = r.json()
            if errors := data.get('errors'):
                for error in errors:
                    logger.error(error['message'])
            return None

        data = r.json()['data']['Viewer']

        return {
            'id': data['id'],
            'score_format': data['mediaListOptions']['scoreFormat'],
        }

    def get_manga_url(self, id):
        return self.manga_url.format(id)

    @authenticated
    def get_tracker_manga_data(self, id, access_token=None):
        query = """
            query ($id: Int) {
                Media (id: $id) {
                    id
                    title {
                        userPreferred
                    }
                    chapters
                }
                Viewer {
                    id
                    mediaListOptions {
                        scoreFormat
                    }
                }
            }
        """
        r = self.session_post(
            self.api_url,
            json={
                'query': query,
                'variables': {
                    'id': id,
                },
            },
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
        )
        if r.status_code != 200:
            data = r.json()
            if errors := data.get('errors'):
                for error in errors:
                    logger.error(error['message'])
            return None

        data = r.json()['data']

        return {
            'id': data['Media']['id'],
            'name': data['Media']['title']['userPreferred'],
            'chapters': data['Media']['chapters'],
            'score_format': data['Viewer']['mediaListOptions']['scoreFormat'],
        }

    def get_user_score_format(self, format):
        return self.USER_SCORES_FORMATS[format]

    @authenticated
    def get_user_manga_data(self, id, access_token=None):
        user = self.get_user()

        query = """
            query ($id: Int, $mediaId: Int, $userId: Int) {
                MediaList(id: $id, mediaId: $mediaId, userId: $userId) {
                    id
                    progress
                    score
                    status
                    media {
                        id
                        title {
                            userPreferred
                        }
                        chapters
                    }
                }
            }
        """
        r = self.session_post(
            self.api_url,
            json={
                'query': query,
                'variables': {
                    'userId': user['id'],
                    'mediaId': id,
                },
            },
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
        )
        if r.status_code != 200:
            data = r.json()
            if errors := data.get('errors'):
                for error in errors:
                    logger.error(error['message'])
            return None

        data = r.json()['data']['MediaList']

        return {
            'id': data['media']['id'],
            'name': data['media']['title']['userPreferred'],
            'chapters': data['media']['chapters'],
            'chapters_progress': data['progress'],
            'score': data['score'],
            'score_format': user['score_format'],
            'status': self.STATUSES_MAPPING[data['status']],
        }

    def refresh_access_token(self):
        # Access token can't be refreshed
        # Tracker server don't store the access token
        return None

    def request_access_token(self):
        redirect_url, error = get_tracker_access_token(self.authorize_url, self.app_redirect_url)

        if redirect_url:
            # Access token is in fragment, convert fragment into query string
            qs = parse_qs(urlparse(redirect_url.replace('#', '?')).query)

            self.data = {
                'access_token': qs['access_token'][0],
                'refresh_token': None,
            }

            return True, None

        return False, error

    def search(self, term):
        query = """
            query($id: Int, $search: String, $page: Int=1, $per_page: Int=10) {
                Page(page: $page, perPage: $per_page) {
                    pageInfo {
                        total
                        currentPage
                        lastPage
                    }
                    media(id: $id, search: $search, type: MANGA, format_not_in: [NOVEL]) {
                        id
                        title {
                            userPreferred
                        }
                        status
                        coverImage {
                            medium
                        }
                        startDate {
                            year
                        }
                        meanScore
                        description
                    }
                }
            }
        """
        r = self.session_post(
            self.api_url,
            json={
                'query': query,
                'variables': {
                    'search': term,
                    'page': 1,
                    'per_page': 10,
                },
            },
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
        )
        if r.status_code != 200:
            data = r.json()
            if errors := data.get('errors'):
                for error in errors:
                    logger.error(error['message'])
            return None

        results = []
        for item in r.json()['data']['Page']['media']:
            results.append({
                'id': item['id'],
                'cover': item['coverImage']['medium'],
                'name': item['title']['userPreferred'],
                'score': item['meanScore'] / 10 if item.get('meanScore') else None,
                'start_date': str(item['startDate']['year']),
                'status': self.RELEASE_STATUSES.get(item['status']),
                'synopsis': item['description'],
            })

        return results

    @authenticated
    def update_user_manga_data(self, id, data, access_token=None):
        user = self.get_user()
        if user is None:
            return False

        # Convert score: RAW to user format
        score = int(data['score'] / self.get_user_score_format(user['score_format'])['raw_factor'])

        # Convert status: internal to tracker naming
        status = self.convert_internal_status(data['status'])

        progress = int(data['chapters_progress'])

        query = f"""
            mutation {{
                SaveMediaListEntry(mediaId: {id}, score: {score}, status: {status}, progress: {progress}) {{
                    id
                    mediaId
                    score
                    status
                    progress
                }}
            }}
        """  # noqa: E202
        r = self.session_post(
            self.api_url,
            json={
                'query': query,
            },
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
        )
        if r.status_code != 200:
            data = r.json()
            if errors := data.get('errors'):
                for error in errors:
                    logger.error(error['message'])
            return False

        return True
