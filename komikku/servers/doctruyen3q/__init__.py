# SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.wpcomics import WPComics
from komikku.servers.utils import convert_date_string
from komikku.utils import is_number


class Doctruyen3q(WPComics):
    id = 'doctruyen3q'
    name = 'DocTruyen3Q'
    lang = 'vi'
    is_nsfw = True

    has_cf = True

    base_url = 'https://doctruyen3qhubx.com'
    search_url = base_url + '/tim-truyen'
    latest_updates_url = base_url + '/tim-truyen?sort=1'
    most_populars_url = base_url + '/tim-truyen?sort=2'
    manga_url = base_url + '/truyen-tranh/{0}'
    chapter_url = base_url + '/truyen-tranh/{0}/{1}'

    chapters_name = 'chapter'
    date_format = None
    image_src_attrs = ['data-original', 'data-src', 'src']
    slug_segments = 2

    details_name_selector = 'h1.title-manga'
    details_cover_selector = 'img.image-comic'
    details_status_selector = None
    details_authors_selector = None
    details_genres_selector = '.category a'
    details_synopsis_selector = '.detail-summary'

    results_selector = '.item-manga'
    results_latest_selector = '.item-manga'
    results_link_selector = '.image-item a'
    results_cover_img_selector = '.image-item a img'
    results_last_chapter_link_selector = '.caption ul li a'
    results_last_chapter_lastest_updates_link_selector = '.caption ul li a'

    chapters_selector = '#list-chapter-dt ul li.row'

    long_strip_genres = [
        'Manhua',
        'Manhwa',
    ]

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        manga_slug = manga_slug.split('/')[0]

        return super(Doctruyen3q, self).get_manga_chapter_data(manga_slug, manga_name, chapter_slug, chapter_url)

    def get_manga_chapters_data(self, slug, soup):
        """
        Returns manga chapters list
        """
        chapters = []
        for element in soup.select(self.chapters_selector):
            a_element = element.select_one('div a')
            url = a_element.get('href')
            slug = url.split('/')[-2]
            num = slug.split('-')[-1] if slug.startswith(f'{self.chapters_name}-') else None
            date = element.select_one('div:last-child').text.strip()

            chapters.append({
                'slug': url.split('/', len(url.split('/')) - self.slug_segments)[-1],
                'title': a_element.text.strip(),
                'num': num if is_number(num) else None,
                'date': convert_date_string(date),
            })

        return list(reversed(chapters))
