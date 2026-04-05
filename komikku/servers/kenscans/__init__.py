# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.heancms import HeanCMS


class Kenscans(HeanCMS):
    id = 'kenscans'
    name = 'Kenscans'
    lang = 'en'

    base_url = 'https://kencomics.com'
    logo_url = base_url + '/favicon-32x32.png'
    api_url = 'https://api.kencomics.com/api'
