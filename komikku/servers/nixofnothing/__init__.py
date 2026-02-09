# SPDX-FileCopyrightText: 2025 Seth Falco
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Seth Falco <seth@falco.fun>

from gettext import gettext as _
import json

from bs4 import BeautifulSoup

from komikku.servers.multi.hiveworks import Hiveworks
from komikku.utils import ServerContent


class Nixofnothing(Hiveworks):
    id = 'nixofnothing'
    name = 'Nix of Nothing'
    lang = 'en'
    content = ServerContent(
        type=[_('Webcomic'), _('Self-publishing')]
    )

    base_url = 'https://www.nixofnothing.com'
    logo_url = base_url + '/favicon.ico'
    donate_url = base_url
    cover_url = base_url + '/templates/nix2024/images/logo.png'

    def get_metadata(self, soup: BeautifulSoup):
        linked_data_str = soup.find('script', attrs={'type': 'application/ld+json'}).contents[0]
        linked_data = json.loads(linked_data_str)

        return {
            'authors': ['M. Lee Lunsford'],
            'synopsis': linked_data['about'],
        }
