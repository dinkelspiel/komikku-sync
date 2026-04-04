# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.iken import Iken


class Ezmanga(Iken):
    id = 'ezmanga'
    name = 'EZmanga'
    lang = 'en'

    base_url = 'https://ezmanga.org'
    logo_url = base_url + '/ezmanga.ico'
    api_url = 'https://vapi.ezmanga.org/api/v1'
