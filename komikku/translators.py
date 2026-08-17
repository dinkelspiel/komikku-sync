# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import json
import urllib.parse

import requests

from komikku.servers.exceptions import ServerException

# https://translate.google.com/translate_a/l?client=t&alpha=true
LANGUAGES = {'ab': 'Abkhaz', 'ace': 'Acehnese', 'ach': 'Acholi', 'aa': 'Afar', 'af': 'Afrikaans', 'sq': 'Albanian', 'alz': 'Alur', 'am': 'Amharic', 'ar': 'Arabic', 'hy': 'Armenian', 'as': 'Assamese', 'av': 'Avar', 'awa': 'Awadhi', 'ay': 'Aymara', 'az': 'Azerbaijani', 'ban': 'Balinese', 'bal': 'Baluchi', 'bm': 'Bambara', 'bci': 'Baoulé', 'ba': 'Bashkir', 'eu': 'Basque', 'btx': 'Batak Karo', 'bts': 'Batak Simalungun', 'bbc': 'Batak Toba', 'be': 'Belarusian', 'bem': 'Bemba', 'bn': 'Bengali', 'bew': 'Betawi', 'bho': 'Bhojpuri', 'bik': 'Bikol', 'bs': 'Bosnian', 'br': 'Breton', 'bg': 'Bulgarian', 'bua': 'Buryat', 'yue': 'Cantonese', 'ca': 'Catalan', 'ceb': 'Cebuano', 'ch': 'Chamorro', 'ce': 'Chechen', 'ny': 'Chichewa', 'zh-CN': 'Chinese (Simplified)', 'zh-TW': 'Chinese (Traditional)', 'chk': 'Chuukese', 'cv': 'Chuvash', 'co': 'Corsican', 'crh': 'Crimean Tatar (Cyrillic)', 'crh-Latn': 'Crimean Tatar (Latin)', 'hr': 'Croatian', 'cs': 'Czech', 'da': 'Danish', 'fa-AF': 'Dari', 'dv': 'Dhivehi', 'din': 'Dinka', 'doi': 'Dogri', 'dov': 'Dombe', 'nl': 'Dutch', 'dyu': 'Dyula', 'dz': 'Dzongkha', 'en': 'English', 'eo': 'Esperanto', 'et': 'Estonian', 'ee': 'Ewe', 'fo': 'Faroese', 'fj': 'Fijian', 'tl': 'Filipino', 'fi': 'Finnish', 'fon': 'Fon', 'fr': 'French', 'fr-CA': 'French (Canada)', 'fy': 'Frisian', 'fur': 'Friulian', 'ff': 'Fulani', 'gaa': 'Ga', 'gl': 'Galician', 'ka': 'Georgian', 'de': 'German', 'el': 'Greek', 'gn': 'Guarani', 'gu': 'Gujarati', 'ht': 'Haitian Creole', 'cnh': 'Hakha Chin', 'ha': 'Hausa', 'haw': 'Hawaiian', 'iw': 'Hebrew', 'hil': 'Hiligaynon', 'hi': 'Hindi', 'hmn': 'Hmong', 'hu': 'Hungarian', 'hrx': 'Hunsrik', 'iba': 'Iban', 'is': 'Icelandic', 'ig': 'Igbo', 'ilo': 'Ilocano', 'id': 'Indonesian', 'iu-Latn': 'Inuktut (Latin)', 'iu': 'Inuktut (Syllabics)', 'ga': 'Irish', 'it': 'Italian', 'jam': 'Jamaican Patois', 'ja': 'Japanese', 'jw': 'Javanese', 'kac': 'Jingpo', 'kl': 'Kalaallisut', 'kn': 'Kannada', 'kr': 'Kanuri', 'pam': 'Kapampangan', 'kk': 'Kazakh', 'kha': 'Khasi', 'km': 'Khmer', 'cgg': 'Kiga', 'kg': 'Kikongo', 'rw': 'Kinyarwanda', 'ktu': 'Kituba', 'trp': 'Kokborok', 'kv': 'Komi', 'gom': 'Konkani', 'ko': 'Korean', 'kri': 'Krio', 'ku': 'Kurdish (Kurmanji)', 'ckb': 'Kurdish (Sorani)', 'ky': 'Kyrgyz', 'lo': 'Lao', 'ltg': 'Latgalian', 'la': 'Latin', 'lv': 'Latvian', 'lij': 'Ligurian', 'li': 'Limburgish', 'ln': 'Lingala', 'lt': 'Lithuanian', 'lmo': 'Lombard', 'lg': 'Luganda', 'luo': 'Luo', 'lb': 'Luxembourgish', 'mk': 'Macedonian', 'mad': 'Madurese', 'mai': 'Maithili', 'mak': 'Makassar', 'mg': 'Malagasy', 'ms': 'Malay', 'ms-Arab': 'Malay (Jawi)', 'ml': 'Malayalam', 'mt': 'Maltese', 'mam': 'Mam', 'gv': 'Manx', 'mi': 'Maori', 'mr': 'Marathi', 'mh': 'Marshallese', 'mwr': 'Marwadi', 'mfe': 'Mauritian Creole', 'chm': 'Meadow Mari', 'mni-Mtei': 'Meiteilon (Manipuri)', 'min': 'Minang', 'lus': 'Mizo', 'mn': 'Mongolian', 'my': 'Myanmar (Burmese)', 'nhe': 'Nahuatl (Eastern Huasteca)', 'ndc-ZW': 'Ndau', 'nr': 'Ndebele (South)', 'new': 'Nepalbhasa (Newari)', 'ne': 'Nepali', 'bm-Nkoo': 'NKo', 'no': 'Norwegian', 'nus': 'Nuer', 'oc': 'Occitan', 'or': 'Odia (Oriya)', 'om': 'Oromo', 'os': 'Ossetian', 'pag': 'Pangasinan', 'pap': 'Papiamento', 'ps': 'Pashto', 'fa': 'Persian', 'pl': 'Polish', 'pt': 'Portuguese (Brazil)', 'pt-PT': 'Portuguese (Portugal)', 'pa': 'Punjabi (Gurmukhi)', 'pa-Arab': 'Punjabi (Shahmukhi)', 'qu': 'Quechua', 'kek': 'Qʼeqchiʼ', 'rom': 'Romani', 'ro': 'Romanian', 'rn': 'Rundi', 'ru': 'Russian', 'se': 'Sami (North)', 'sm': 'Samoan', 'sg': 'Sango', 'sa': 'Sanskrit', 'sat-Latn': 'Santali (Latin)', 'sat': 'Santali (Ol Chiki)', 'gd': 'Scots Gaelic', 'nso': 'Sepedi', 'sr': 'Serbian', 'st': 'Sesotho', 'crs': 'Seychellois Creole', 'shn': 'Shan', 'sn': 'Shona', 'scn': 'Sicilian', 'szl': 'Silesian', 'sd': 'Sindhi', 'si': 'Sinhala', 'sk': 'Slovak', 'sl': 'Slovenian', 'so': 'Somali', 'es': 'Spanish', 'su': 'Sundanese', 'sus': 'Susu', 'sw': 'Swahili', 'ss': 'Swati', 'sv': 'Swedish', 'ty': 'Tahitian', 'tg': 'Tajik', 'ber-Latn': 'Tamazight', 'ber': 'Tamazight (Tifinagh)', 'ta': 'Tamil', 'tt': 'Tatar', 'te': 'Telugu', 'tet': 'Tetum', 'th': 'Thai', 'bo': 'Tibetan', 'ti': 'Tigrinya', 'tiv': 'Tiv', 'tpi': 'Tok Pisin', 'to': 'Tongan', 'lua': 'Tshiluba', 'ts': 'Tsonga', 'tn': 'Tswana', 'tcy': 'Tulu', 'tum': 'Tumbuka', 'tr': 'Turkish', 'tk': 'Turkmen', 'tyv': 'Tuvan', 'ak': 'Twi', 'udm': 'Udmurt', 'uk': 'Ukrainian', 'ur': 'Urdu', 'ug': 'Uyghur', 'uz': 'Uzbek', 've': 'Venda', 'vec': 'Venetian', 'vi': 'Vietnamese', 'war': 'Waray', 'cy': 'Welsh', 'wo': 'Wolof', 'xh': 'Xhosa', 'sah': 'Yakut', 'yi': 'Yiddish', 'yo': 'Yoruba', 'yua': 'Yucatec Maya', 'zap': 'Zapotec', 'zu': 'Zulu'}


class Google:
    base_url = 'https://translate.google.com'
    translate_rpc_url = base_url + '/_/TranslateWebserverUi/data/batchexecute'

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Referer': f'{base_url}/',
    }
    rpc_id = 'MkEWBc'

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def translate(self, text, src='auto', dst='en'):
        params = {
            'rpcids': self.rpc_id,
            'bl': 'boq_translate-webserver_20201207.13_p0',
            'soc-app': '1',
            'soc-platform': '1',
            'soc-device': '1',
            'rt': 'c',
        }
        data = {
            'f.req': json.dumps(
                [[[
                    self.rpc_id,
                    json.dumps(
                        [[text, src, dst, 1, None, 1], [None]],
                        ensure_ascii=False,
                        separators=(',', ':')
                    ),
                    None,
                    'generic',
                ]]],
                ensure_ascii=False,
                separators=(',', ':'),
            )
        }

        r = self.session.post(
            self.translate_rpc_url + '?' + urllib.parse.urlencode(params),
            data=data,
            timeout=20,
            allow_redirects=False,
        )
        if not r.ok:
            raise ServerException(f'Google Translate returned HTTP {r.status_code}: {r.text[:128]}')

        data = r.content.decode('utf-8')

        json_data = None
        for line in data.split('\n'):
            if self.rpc_id in line:
                json_data = json.loads(line)
                break

        if not json_data:
            raise ServerException('RPC Id payload not found in Google Translate response')

        try:
            payload = json.loads(json_data[0][2])
        except json.JSONDecodeError:
            raise ServerException('Invalid JSON payload in Google Translate response')

        parts = payload[1][0][0][5]
        translated = []
        for index, part in enumerate(parts):
            if not part or not isinstance(part, list) or not isinstance(part[0], str):
                continue

            text = part[0]
            # If part[2] is True, a space (separator) must be added
            if index > 0 and len(part) > 2 and part[2] and text and not text[0].isspace():
                translated.append(' ')

            translated.append(text)

        if not translated:
            raise ServerException('No translated parts found in Google Translate response')

        translated = ''.join(translated)

        src_detected = None
        try:
            src_detected = payload[2]
        except (IndexError, TypeError):
            pass

        origin_pronunciation = None
        try:
            origin_pronunciation = payload[0][0]
        except (IndexError, TypeError):
            pass

        pronunciation = None
        try:
            pronunciation = payload[1][0][0][1]
        except (IndexError, TypeError):
            pass

        mistake = None
        try:
            mistake = payload[0][1][0][0][1]
            # Convert to pango markup
            mistake = mistake.replace('<em>', '<b>').replace('</em>', '</b>')
        except (IndexError, TypeError):
            pass

        return {
            'translated': translated,
            'src_detected': src_detected,
            'origin_pronunciation': origin_pronunciation,
            'pronunciation': pronunciation,
            'mistake': mistake,
        }
