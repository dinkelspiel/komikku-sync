# SPDX-FileCopyrightText: 2025 Seth Falco
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Seth Falco <seth@falco.fun>

from gettext import gettext as _

from komikku.servers.multi.hiveworks import Hiveworks
from komikku.utils import ServerContent


class Wildlife(Hiveworks):
    id = 'wildlife'
    name = 'Wild Life'
    lang = 'en'
    content = ServerContent(
        type=[_('Webcomic'), _('Self-publishing')]
    )

    base_url = 'https://www.wildelifecomic.com'
    logo_url = base_url + '/favicon.ico'
    cover_url = base_url + '/image/patreon(2).jpg'
