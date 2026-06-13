# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.iken import Iken


class Nightscans(Iken):
    id = 'nightscans'
    name = 'Qi Scans (Night scans)'
    lang = 'en'

    base_url = 'https://qimanga.com'
    logo_url = base_url + '/qiscans.ico'
    api_url = 'https://api.qimanga.com/api/v1'
