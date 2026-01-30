# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.madara import Madara2


class Mangabin(Madara2):
    id = 'mangabin'
    name = 'MangaBin'
    lang = 'en'
    is_nsfw = True
    status = 'disabled'

    base_url = 'https://mangabin.com'
    logo_url = base_url + '/wp-content/uploads/2024/12/cropped-coollogo_com-29007530-32x32.png'
    chapters_url = base_url + '/manga/{0}/ajax/chapters/'
