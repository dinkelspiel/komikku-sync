# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.heancms import HeanCMS


class Rezoscans(HeanCMS):
    id = 'rezoscans'
    name = 'Rezo Scans'
    lang = 'en'
    status = 'disabled'  # merge with Qi Scans

    base_url = 'https://rezoscan.org'
    logo_url = 'https://storage.rezoscan.org/upload/2025/06/24/%D8%A7%D9%84%D9%84%D9%88%D8%BA%D9%88-9f96b7a917940f61.webp'
    api_url = 'https://api.rezoscan.org/api'
