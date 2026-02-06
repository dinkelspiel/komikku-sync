#! /usr/bin/env python

# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import os
import re

LANGUAGES = {
    'ar': 'Arabic',
    'as': 'Assamese',
    'pt_BR': 'Brazilian Portuguese',
    'bg': 'Bulgarian',
    'ca': 'Catalan',
    'cs': 'Czech',
    'eo': 'Esperanto',
    'zh_CN': 'Simplified Chinese',
    'zh_Hant': 'Traditional Chinese',
    'nl': 'Dutch',
    'fa': 'Persian',
    'fi': 'Finnish',
    'fr': 'French',
    'de': 'German',
    'hi': 'Hindi',
    'hu': 'Hungarian',
    'hr': 'Croatian',
    'id': 'Indonesian',
    'it': 'Italian',
    'kk': 'Kazakh',
    'ko': 'Korean',
    'kw': 'Cornish',
    'ml': 'Malayalam',
    'ms': 'Malay',
    'oc': 'Occitan',
    'lt': 'Lithuanian',
    'pl': 'Polish',
    'pt': 'Portuguese',
    'ru': 'Russian',
    'es': 'Spanish',
    'sv': 'Swedish',
    'ta': 'Tamil',
    'tr': 'Turkish',
    'uk': 'Ukrainian',
    'vi': 'Vietnamese',
}

dirpath = 'po'
re_email = r'[\w\-\.]+@([\w-]+\.)+[\w-]{2,}'

translators = {}
for lang in LANGUAGES:
    translators[lang] = []

# Add missing translators not declared in PO files
translators['zh_CN'].append('Dingzhong Chen')


# Walk in PO folder
for name in sorted(os.listdir(dirpath)):
    if not name.endswith('.po'):
        # Ignore non-.po files
        continue

    lang = name.split('.')[0]
    path = os.path.join(dirpath, name)

    with open(path) as fd:
        for line in fd.readlines():
            if not line.startswith('# '):
                continue

            match = re.search(re_email, line)
            if match is None:
                continue

            # Extract translator name
            translator = line.split('<')[0][2:].replace('"', '').strip()
            if translator not in translators[lang]:
                translators[lang].append(translator)

# Print code chunk
for lang, translators in translators.items():
    for translator in translators:
        print(f"        '{translator} ({LANGUAGES[lang]})',")  # noqa: E231
