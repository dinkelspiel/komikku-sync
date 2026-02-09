# SPDX-FileCopyrightText: 2025 Seth Falco
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Seth Falco <seth@falco.fun>

from gettext import gettext as _

from bs4 import BeautifulSoup

from komikku.servers.multi.hiveworks import Hiveworks
from komikku.utils import ServerContent


class Threepanelsoul(Hiveworks):
    id = 'threepanelsoul'
    name = 'Three Panel Soul'
    lang = 'en'
    content = ServerContent(
        type=[_('Webcomic'), _('Self-publishing')]
    )

    base_url = 'https://www.threepanelsoul.com'
    logo_url = base_url + '/favicon.ico'
    cover_url = None

    def get_metadata(self, soup: BeautifulSoup):
        return {
            'authors': [
                'Ian McConville',
                'Matthew Boyd',
            ],
            'synopsis': "It's a pretty rigid format but we keep the content loose, you know?",
        }
