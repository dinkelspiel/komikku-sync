# SPDX-FileCopyrightText: 2019-2026 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import datetime
from gettext import gettext as _

BORDERS_CROP_THRESHOLD_MIN = 100
BORDERS_CROP_THRESHOLD_MAX = 240
BORDERS_CROP_THRESHOLD_STEP = 10
BORDERS_CROP_THRESHOLDS = range(
    BORDERS_CROP_THRESHOLD_MIN,
    BORDERS_CROP_THRESHOLD_MAX + BORDERS_CROP_THRESHOLD_STEP,
    BORDERS_CROP_THRESHOLD_STEP
)
COVER_WIDTH = 180
COVER_HEIGHT = 256
LOGO_SIZE = 32
MISSING_IMG_RESOURCE_PATH = '/info/febvre/Komikku/images/missing_file.png'
PROGRESSBAR_THEMES = {
    'accent-color': {
        'name': _('Accent Color'),
        'colors': None,
    },
    # https://en.wikipedia.org/wiki/Pride_flag
    'pride-rainbow': {
        'name': _('Pride Colors'),
        'colors': ['#E40303', '#FF8C00', '#FFED00', '#008026', '#24408E', '#732982'],
    },
    'lesbian-pride': {
        'name': _('Lesbian Pride Colors'),
        'colors': ['#D62800', '#EF7627', '#FF9B56', '#FFFFFF', '#D162A4', '#B55690', '#A30262'],
    },
    'gay-pride': {
        'name': _('Male Homosexual Pride Colors'),
        'colors': ['#018E71', '#21CFAC', '#9AE9C3', '#FFFFFF', '#7CAFE4', '#4F47CC', '#3C1379'],
    },
    'transgender': {
        'name': _('Transgender Pride Colors'),
        'colors': ['#5BCEFA', '#F5A9B8', '#FFFFFF', '#F5A9B8', '#5BCEFA'],
    },
    'nonbinary': {
        'name': _('Nonbinary Pride Colors'),
        'colors': ['#FCF434', '#FFFFFF', '#9C59D1', '#2C2C2C'],
    },
    'bisexual': {
        'name': _('Bisexual Pride Colors'),
        'colors': ['#D60270', '#D60270', '#9B4F96', '#0038A8', '#0038A8'],
    },
    'asexual': {
        'name': _('Asexual Pride Colors'),
        'colors': ['#000000', '#A3A3A3', '#FFFFFF', '#810081'],
    },
    'pansexual': {
        'name': _('Pansexual Pride Colors'),
        'colors': ['#FF218C', '#FFD800', '#21B1FF'],
    },
    'aromantic': {
        'name': _('Aromantic Pride Colors'),
        'colors': ['#3DA542', '#A7D379', '#FFFFFF', '#A9A9A9', '#000000'],
    },
    'genderfluid': {
        'name': _('Genderfluid Pride Colors'),
        'colors': ['#FF76A4', '#FFFFFF', '#C011D7', '#000000', '#2F3CBE'],
    },
    'polysexual': {
        'name': _('Polysexual Pride Colors'),
        'colors': ['#F61CB9', '#07D569', '#1C92F6'],
    },
    'omnisexual': {
        'name': _('Omnisexual Pride Colors'),
        'colors': ['#FF9CCE', '#FF52BF', '#200044', '#675FFF', '#8DA7FF'],
    },
    'aroace': {
        'name': _('Aroace Pride Colors'),
        'colors': ['#E28C00', '#ECCD00', '#FFFFFF', '#62AEDC', '#203856'],
    },
    'agender': {
        'name': _('Agender Pride Colors'),
        'colors': ['#000000', '#BCC4C7', '#FFFFFF', '#B7F684', '#FFFFFF', '#BCC4C7', '#000000'],
    },
    'genderqueer': {
        'name': _('Genderqueer Pride Colors'),
        'colors': ['#B57EDC', '#FFFFFF', '#4A8123'],
    },
    'intersex': {
        'name': _('Intersex Pride Colors'),
        'colors': ['#FFD800', '#FFD800', '#7902AA', '#FFD800', '#FFD800'],
    },
    'demigender': {
        'name': _('Demigender Pride Colors'),
        'colors': ['#7F7F7F', '#C3C3C3', '#FBFF74', '#FFFFFF', '#FBFF74', '#C3C3C3', '#7F7F7F'],
    },
    'biromantic': {
        'name': _('Biromantic Pride Colors'),
        'colors': ['#8869A5', '#D8A7D8', '#FFFFFF', '#FDB18D', '#151638'],
    },
    'disability': {
        'name': _('Disability Pride Colors'),
        'colors': ['#595959', '#CF7280', '#EEDE77', '#E8E8E8', '#7BC2E0', '#3BB07D', '#595959'],
    },
    'femboy': {
        'name': _('Femboy Pride Colors'),
        'colors': ['#D460A7', '#E4ADCD', '#FFFFFF', '#57CEF8', '#FFFFFF', '#E4ADCD', '#D460A7'],
    },
    'neutrois': {
        'name': _('Neutrois Pride Colors'),
        'colors': ['#FFFFFF', '#1F9F00', '#000000'],
    },
    'random': {
        'name': _('Random Colors'),
        'lenght': 16,
        'colors': None,
    },
}

DOWNLOAD_MAX_DELAY = 1  # in seconds
REQUESTS_TIMEOUT = 5
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64; rv:129.0) Gecko/20100101 Firefox/129.0'
USER_AGENT_MOBILE = 'Mozilla/5.0 (Linux; U; Android 4.1.1; en-gb; Build/KLP) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Safari/534.30'

TIMEZONE = datetime.datetime.now(tz=datetime.UTC).astimezone().tzinfo

CREDITS = dict(
    artists=(
        'Tobias Bernard (bertob)',
    ),
    designers=(
        'Tobias Bernard (bertob)',
        'Valéry Febvre (valos)',
    ),
    developers=(
        'Mufeed Ali (fushinari)',
        'Gerben Droogers (Tijder)',
        'Valéry Febvre (valos)',
        'Aurélien Hamy (aunetx)',
        'Amelia Joison (amnetrine)',
        'David Keller (BlobCodes)',
        'Oleg Kiryazov (CakesTwix)',
        'Lili Kurek',
        'Liliana Prikler',
        'Sabri Ünal',
        'Romain Vaudois',
        'Arthur Williams (TAAPArthur)',
        'GrownNed',
        'ISO-morphism',
        'jaskaranSM',
    ),
    translators=(
        'abidin toumi (Arabic)',
        'Rayen Ghanmi (Arabic)',
        'Mohamed Abdalah Noh (Arabic)',
        'Ahmed Najmawi (Arabic)',
        'Jsus “Jsux” (Bengali)',
        'Bhalet Chakma (Bengali)',
        'Rafael Fontenelle (Brazilian Portuguese)',
        'Infinitive Witch (Brazilian Portuguese)',
        'Unidealistic Raccoon (Brazilian Portuguese)',
        'Alex Carvalho (Brazilian Portuguese)',
        'Juliano de Souza Camargo (Brazilian Portuguese)',
        'Giovanne Menicheli (Brazilian Portuguese)',
        'Fúlvio Alves (Brazilian Portuguese)',
        'Felipe (Brazilian Portuguese)',
        'Matheus Santana (Brazilian Portuguese)',
        'Lucas Oliveira (Brazilian Portuguese)',
        'Lucas Loura (Brazilian Portuguese)',
        'Beruto666 (Brazilian Portuguese)',
        'twlvnn (Bulgarian)',
        'Roger VC (Catalan)',
        'Flynn (Cornish)'
        'Lukáš Linhart (Czech)',
        'Jakub Soukup (Czech)',
        'Petr Horník (Czech)',
        'Dingzhong Chen (Simplified Chinese)',
        'Eric-Song-Nop (Simplified Chinese)',
        'Inaha (Simplified Chinese)',
        'LS-Shandong (Simplified Chinese)',
        'randint (Traditional Chinese)',
        'Zhao Se (Traditional Chinese)',
        'happylittle7 (Traditional Chinese)',
        'Heimen Stoffels (Dutch)',
        'Philip Goto (Dutch)',
        'Koen Benne (Dutch)',
        'Mikachu (Dutch)',
        'Danial Behzadi (Persian)',
        'Muhammad Hussein Ammari (Persian)',
        'Jiri Grönroos (Finnish)',
        'Ricky Tigg (Finnish)',
        'Irénée THIRION (French)',
        'Valéry Febvre (French)',
        'Mathieu B. (French)',
        'rene-coty (French)',
        'paul verot (French)',
        'Temuri Doghonadze (Georgian)',
        'David Gogniashvili (Georgian)',
        'Sandor Odor (German)',
        'Liliana Prikler (German)',
        'gregorni (German)',
        'Liliana Marie Prikler (German)',
        'Tim (German)',
        'Sear Gasor (German)',
        'Vortex Acherontic (German)',
        'Dlurak (German)',
        'Mirko P. (German)',
        'Simon Barth (German)',
        'anon (German)',
        'Scrambled777 (Hindi)',
        'Milo Ivir (Croatian)',
        'Alifiyan Rosyidi (Indonesian)',
        'Alim Satria (Indonesian)',
        'Juan Manuel (Indonesian)',
        'srntskl-111 (Indonesian)',
        'Nataniel Dika Kurniawan (Indonesian)',
        'Mek101 (Italian)',
        'dedocc (Italian)',
        'Davide Mora (Italian)',
        'Andrea Scarano (Italian)',
        'pasquale ruotolo (Italian)',
        'Riccardo Luise (Italian)',
        'cas9 (Italian)',
        'Giulia (Italian)',
        'on9686 (Korean)',
        'Velyvis (Lithuanian)',
        'Lili Kurek (Polish)',
        'Aleksander Warzyniak (Polish)',
        'Kurai (Polish)',
        'Goraj (Polish)',
        'ssantos (Portuguese)',
        'Ademario Cunha (Portuguese)',
        'SpiralPack 527 (Portuguese)',
        'Lucas Silva Goulart (Portuguese)',
        'Manuela Silva (Portuguese)',
        'shima (Russian)',
        'Valentin Chernetsov (Russian)',
        'FIONover (Russian)',
        'Анна Алешкина #нетвойне (Russian)',
        'Сергей (Russian)',
        'Andrei Stepanov (Russian)',
        'Óscar Fernández Díaz (Spanish)',
        'gallegonovato (Spanish)',
        'Klauss (Spanish)',
        'Champiñon Traductor (Spanish)',
        'Libre (Spanish)',
        'Jesper (Swedish)',
        'PaneradFisk (Swedish)',
        'Willem Dinkelspiel (Swedish)',
        'Daniel Wiik (Swedish)',
        'தமிழ்நேரம் (Tamil)',
        'Ege Çelikçi (Turkish)',
        'Sabri Ünal (Turkish)',
        'Volkan Yıldırım (Turkish)',
        'Efe Akın (Turkish)',
        'Ahmet (Turkish)',
        'CakesTwix (Ukrainian)',
        'Kislotniy (Acela) (Ukrainian)',
        'mondstern (Ukrainian)',
        'DXCVII (Ukrainian)',
        'Bezruchenko Simon (Ukrainian)',
        'Максим Горпиніч (Ukrainian)',
        'Димко (Ukrainian)',
        'niyaki hayyashi (Vietnamese)',
        'Loc Huynh (Vietnamese)',
    ),
    supporters=(
        'gondolyr',
        'José',
    ),
)

RELEASE_NOTES = """
<p>This is a bugfix version.</p>
<ul>
    <li>[Reader] RTL/LTR/Vertical pager: Fixed keyboard/mouse navigation</li>
    <li>[Reader] OCR Translator: Improvements in Translator</li>
    <li>[L10n] Updated Russian and Ukrainian translations</li>
</ul>

<p>Changes in previous version 50.12.0</p>
<ul>
    <li>[Reader] Added an OCR translator</li>
    <li>[Reader] Moved settings from Menu to Settings dialog</li>
    <li>[Servers] Added MangaLivre (pt_BR)</li>
    <li>[Servers] Desu (RU): Update</li>
    <li>[Servers] JManga (JA): Update</li>
    <li>[Servers] MangaFire (EN/ES/FR/JA/PT/pt_BR): Update</li>
    <li>[Servers] Rncalation (ES): Update</li>
    <li>[Servers] Weeb Central (EN): Update</li>
    <li>[L10n] Updated Bengali, French, Korean, Polish, Russian and Ukrainian translations</li>
</ul>
<p>Happy reading.</p>
"""
