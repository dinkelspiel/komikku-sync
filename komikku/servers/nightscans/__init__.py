# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.heancms import HeanCMS


class Nightscans(HeanCMS):
    id = 'nightscans'
    name = 'Qi Scans (Night scans)'
    lang = 'en'

    base_url = 'https://qimanhwa.com'
    api_url = 'https://api.qimanhwa.com/api'
