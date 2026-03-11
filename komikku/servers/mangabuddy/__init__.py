# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import logging

from komikku.servers.multi.madtheme import Madtheme

logger = logging.getLogger(__name__)


class Mangabuddy(Madtheme):
    id = 'mangabuddy'
    name = 'MangaBuddy'
    lang = 'en'

    base_url = 'https://mangabuddy.com'
    logo_url = base_url + '/static/sites/mangabuddy/icons/favicon-32x32.png'
    api_base_url = 'https://mangabuddy.com/api'
