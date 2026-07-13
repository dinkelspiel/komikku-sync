# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.peachscan import Peachscan


class Rfdragonscan(Peachscan):
    id = 'rfdragonscan'
    name = 'RF Dragon Scan'
    lang = 'pt_BR'
    status = 'disabled'

    has_cf = True

    base_url = 'https://rfdragonscan.net'
