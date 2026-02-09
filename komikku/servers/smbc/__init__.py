# SPDX-FileCopyrightText: 2025 Seth Falco
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Seth Falco <seth@falco.fun>

from gettext import gettext as _
import json

from bs4 import BeautifulSoup

from komikku.servers.multi.hiveworks import Hiveworks
from komikku.utils import ServerContent


class Smbc(Hiveworks):
    id = 'smbc'
    name = 'SMBC'
    lang = 'en'
    content = ServerContent(
        type=[_('Webcomic'), _('Self-publishing')]
    )

    base_url = 'https://www.smbc-comics.com'
    donate_url = 'https://www.patreon.com/ZachWeinersmith?ty=h'
    logo_url = base_url + '/favicon.ico'
    cover_url = base_url + '/images/moblogo.png'

    def get_metadata(self, soup: BeautifulSoup):
        linked_data_str = soup.find('script', attrs={'type': 'application/ld+json'}).contents[0]
        linked_data = json.loads(linked_data_str)

        return {
            'authors': [linked_data['author'], ],
            'synopsis': soup.find_all('meta', {'name': 'description'})[-1].get('content'),
        }
