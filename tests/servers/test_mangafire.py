# SPDX-FileCopyrightText: 2019-2025 Contributors to Komikku
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import pytest
from pytest_steps import test_steps

from . import do_server_test
from komikku.utils import log_error_traceback

logging.basicConfig(level=logging.DEBUG)


@pytest.fixture
def mangafire_server():
    from komikku.servers.mangafire import Mangafire

    return Mangafire()


@do_server_test
@test_steps('get_latest_updates', 'get_most_popular', 'get_manga_data')
def test_mangafire(mangafire_server):
    # Get latest updates
    print('Get latest updates')
    try:
        response = mangafire_server.get_latest_updates()
    except Exception as e:
        response = None
        log_error_traceback(e)

    assert response is not None
    yield

    # Get most popular
    print('Get most popular')
    try:
        response = mangafire_server.get_most_populars()
    except Exception as e:
        response = None
        log_error_traceback(e)

    assert response is not None
    yield

    # Get manga data
    print('Get manga data')
    try:
        slug = response[0]['slug']
        response = mangafire_server.get_manga_data(dict(slug=slug))
        chapter_slug = response['chapters'][0]['slug']
    except Exception as e:
        chapter_slug = None
        log_error_traceback(e)

    assert chapter_slug is not None
    yield
