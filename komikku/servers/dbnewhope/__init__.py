# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
from bs4 import BeautifulSoup
import requests

from komikku.consts import USER_AGENT
from komikku.servers import Server
from komikku.servers.utils import get_soup_element_inner_text
from komikku.utils import get_buffer_mime_type
from komikku.utils import ServerContent

# Conversion ISO_639-1 codes => server codes
LANGUAGES_CODES = dict(
    en='english',
    es='espanol',
    fr='francais',
    ru='ru',
    zh_Hans='zh',  # diff
)


class Dbnewhope(Server):
    id = 'dbnewhope'
    name = 'DB New Hope'
    lang = 'fr'
    content = ServerContent(
        type=[_('Doujinshi'), _('Fan Webcomic')]
    )
    true_search = False

    base_url = 'https://dbnewhope.com'
    donate_url = base_url + '/#patreon'
    logo_url = base_url + '/assets/favicon.ico'
    manga_url = base_url + '/{0}/chapitres.php'
    page_url = base_url + '/{0}/{1}/01.php?page={2}'
    cover_url = base_url + '/francais/1/fe07eee1f0268775c646e844b05bff2d.png?ezimgfmt=rs%3Adevice%2Frscb1-1'

    synopsis = """
Au lendemain de sa victoire écrasante contre Gohan lors du Cell Game, Cell s'est éclipsé de la Terre, laissant Krilin indemne mais marqué par le souvenir de sa propre misère. Sept années se sont écoulées, le monde s'est reconstruit, mais la menace persiste dans l'ombre. Krilin, se charge de former le dernier guerrier survivant de la planète, en prévision d'un éventuel retour du monstre créé par le machiavélique Dr. Gero.

Le dernier espoir de la Z-Team se révèle être un individu au caractère bien trempé, à la fierté débordante. Entre les leçons de combat et les entraînements intensifs, une relation complexe se tisse, mêlant respect, apprentissage et compréhension mutuelle. Les pages de ce manga se dévoilent comme un nouvel épisode palpitant de l'univers épique de DBZ, où le passé douloureux et les défis du présent convergent vers un avenir incertain.

Dans ce récit inédit, découvrez une aventure trépidante où les liens entre maître et apprenti se forgent au fil des combats, où l'héritage des guerriers Z se perpétue face à une menace insidieuse. Sera-t-il possible pour le dernier défenseur de la Terre d'apprivoiser la force intérieure de son protégé et de prévenir le retour redouté de Cell? Plongez-vous dans cette épopée captivante, où l'esprit de DBZ demeure plus vibrant que jamais.
    """

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})

    @property
    def lang_code(self):
        return LANGUAGES_CODES[self.lang]

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content
        """
        r = self.session_get(self.manga_url.format(self.lang_code))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update(dict(
            authors=['Burichan ブリちゃん', ],
            scanlators=[],
            genres=['Shōnen', 'Dōjinshi'],
            status='ongoing',
            synopsis=self.synopsis.strip(),
            chapters=[],
            server_id=self.id,
            cover=self.cover_url,
        ))

        # Chapters
        for element in soup.select('.card'):
            slug = element.a.get('href').split('/')[0]
            data['chapters'].append(dict(
                slug=slug,
                title=get_soup_element_inner_text(element.select_one('.card-title'), recursive=False),
                num=slug,
                date=None,
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga data by scraping manga HTML page content
        """
        r = self.session_get(self.page_url.format(self.lang_code, chapter_slug, 1))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )
        for element in soup.select('.nav select option'):
            data['pages'].append(dict(
                slug=element.get('value').split('=')[-1],
                image=None,
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        r = self.session_get(self.page_url.format(self.lang_code, chapter_slug, page['slug']))
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        url = None
        if img_element := soup.select_one('.image-wrapper img'):
            url = img_element.get('data-ezsrc')
            if not url:
                url = img_element.get('src')

        if not url:
            return None

        r = self.session_get(
            self.base_url + url,
            headers={
                'Referer': self.page_url.format(self.lang_code, chapter_slug, page['slug']),
            }
        )
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name='{0}.{1}'.format(page['slug'], mime_type.split('/')[-1]),
        )

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(self.lang_code)

    def get_most_populars(self):
        return [dict(
            slug=f'{self.lang_code}readdbnh',
            name=self.name,
            cover=self.cover_url,
        )]

    def search(self, term=None):
        # This server does not have a true search
        # but a search method is needed for `Global Search` in `Explorer`
        # In order not to be offered in `Explorer`, class attribute `true_search` must be set to False

        results = []
        for item in self.get_most_populars():
            if term and term.lower() in item['name'].lower():
                results.append(item)

        return results


class Dbnewhope_en(Dbnewhope):
    id = 'dbnewhope_en'
    lang = 'en'

    base_url = 'https://dbnewhope.com'
    manga_url = base_url + '/{0}/chapters.php'

    synopsis = """
The day after his crushing victory over Gohan in the Cell Game, Cell vanished from Earth, leaving Krilin unharmed but scarred by the memory of his own misery. Seven years have passed, the world has been rebuilt, but the threat persists in the shadows. Krilin takes it upon himself to train the planet's last surviving warrior, in anticipation of the possible return of the monster created by the Machiavellian Dr. Gero.

The last hope of the Z-Team turns out to be a strong-willed individual with an overflowing sense of pride. Between combat lessons and intensive training, a complex relationship develops, combining respect, learning and mutual understanding. The pages of this manga reveal themselves as a thrilling new episode in the epic DBZ universe, where the painful past and the challenges of the present converge towards an uncertain future.

In this all-new story, discover a thrilling adventure where the bonds between master and apprentice are forged in battle, where the legacy of the Z warriors lives on in the face of an insidious threat. Can Earth's last defender tame his protégé's inner strength and prevent Cell's dreaded return? Immerse yourself in this captivating epic, where the spirit of DBZ remains as vibrant as ever.
    """


class Dbnewhope_es(Dbnewhope):
    id = 'dbnewhope_es'
    lang = 'es'

    base_url = 'https://dbnewhope.com'
    manga_url = base_url + '/{0}/capitulos.php'

    synopsis = """
Al día siguiente de su aplastante victoria sobre Gohan en el Cell Game, Célula desapareció de la Tierra, dejando a Krilin ileso pero marcado por el recuerdo de su propia miseria. Han pasado siete años, el mundo ha sido reconstruido, pero la amenaza persiste en las sombras. Krilin se encarga de entrenar al último guerrero superviviente del planeta, en previsión del posible regreso del monstruo creado por el maquiavélico Dr. Gero.

La última esperanza del Equipo Z resulta ser un individuo de carácter fuerte y orgullo desbordante. Entre lecciones de combate y entrenamientos intensivos, se desarrolla una compleja relación que combina respeto, aprendizaje y comprensión mutua. Las páginas de este manga se revelan como un nuevo y emocionante episodio del épico universo DBZ, donde el doloroso pasado y los retos del presente convergen hacia un futuro incierto.

En esta historia totalmente nueva, descubre una emocionante aventura en la que los lazos entre maestro y aprendiz se forjan en la batalla, donde el legado de los guerreros Z sigue vivo frente a una insidiosa amenaza. ¿Será capaz el último defensor de la Tierra de domar la fuerza interior de su protegido y evitar el temido regreso de Célula? Sumérgete en esta cautivadora epopeya, donde el espíritu de DBZ sigue tan vivo como siempre.
    """


class Dbnewhope_ru(Dbnewhope):
    id = 'dbnewhope_ru'
    lang = 'ru'
    status = 'disabled'

    synopsis = """
На следующий день после сокрушительной победы над Гоханом в Игре Клеток, Клетка исчез с Земли, оставив Крилина невредимым, но с шрамами от воспоминаний о собственных страданиях. Прошло семь лет, мир был восстановлен, но угроза продолжает оставаться в тени. Крилин берется обучить последнего выжившего воина планеты в ожидании возможного возвращения монстра, созданного макиавеллистским доктором Геро.

Последняя надежда команды Z-Team оказывается волевым человеком с переполненным чувством гордости. Между боевыми уроками и интенсивными тренировками складываются сложные отношения, сочетающие в себе уважение, обучение и взаимопонимание. Страницы этой манги открываются как новый захватывающий эпизод в эпической вселенной DBZ, где болезненное прошлое и вызовы настоящего сходятся в неопределенном будущем.

В этой новой истории вас ждет захватывающее приключение, где узы между мастером и учеником скрепляются в бою, где наследие воинов Z продолжает жить перед лицом коварной угрозы. Сможет ли последний защитник Земли укротить внутреннюю силу своего протеже и предотвратить страшное возвращение Клетки? Погрузитесь в эту захватывающую эпопею, где дух DBZ остается таким же ярким, как и прежде.
    """


class Dbnewhope_zh_hans(Dbnewhope):
    id = 'dbnewhope_zh_hans'
    lang = 'zh_Hans'
    status = 'disabled'

    synopsis = """
细胞在 "细胞游戏 "中战胜悟饭后的第二天，就从地球上消失了，克里林毫发无损，但却留下了痛苦的回忆。七年过去了，世界已经重建，但威胁依然存在。克里林开始训练地球上最后一名幸存的战士，以防那个由马基雅维利斯-吉罗博士创造的怪物可能卷土重来。

Z 战队最后的希望竟然是一个意志坚强、自尊心极强的人。在战斗课程和强化训练之间，他们建立起了一种复杂的关系，将尊重、学习和相互理解融为一体。在这部漫画中，我们将看到史诗般的 DBZ 宇宙中惊心动魄的新篇章，痛苦的过去和现在的挑战交织在一起，走向不确定的未来。

在这个全新的故事中，您将发现一场惊心动魄的冒险，师徒之间的羁绊在战斗中铸就，Z 战士的传奇在阴险的威胁面前得以延续。地球最后的捍卫者能否驯服他的徒弟的内在力量，阻止可怕的细胞卷土重来？请沉浸在这部引人入胜的史诗中，DBZ 的精神将一如既往地充满活力。
    """
