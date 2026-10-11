"""Where each ad zone appears on the site, in words — shown next to the
layout picture on the ad form (templates/ads/manage/adslot_form.html) so
an editor can see a zone before choosing it.

Keep in step with the templates that place the zones: templates/base.html
(header leaderboard, mobile anchor), templates/home.html (the homepage
zones) and templates/articles/article_detail.html with
articles/content_ads.py (the article zones).
"""
from .models import AdSlot

Z = AdSlot.Zone

PLACEMENTS = {
    Z.HEADER_LEADERBOARD: {
        'page': 'Every page', 'screens': 'Computers and tablets',
        'where': 'A strip across the top of every page, just under the menu.',
    },
    Z.HOMEPAGE_RECTANGLE_1: {
        'page': 'Homepage', 'screens': 'All screens',
        'where': 'First of three boxes side by side, after the top stories and trending (stacked one under '
                 'another on phones).',
    },
    Z.HOMEPAGE_RECTANGLE_2: {
        'page': 'Homepage', 'screens': 'All screens',
        'where': 'Middle of the three boxes after the top stories and trending.',
    },
    Z.HOMEPAGE_RECTANGLE_3: {
        'page': 'Homepage', 'screens': 'All screens',
        'where': 'Last of the three boxes after the top stories and trending.',
    },
    Z.HOMEPAGE_LEADERBOARD: {
        'page': 'Homepage', 'screens': 'Large screens only',
        'where': 'A wide strip lower down the homepage, between the videos and research highlights.',
    },
    Z.MOBILE_LARGE_BANNER: {
        'page': 'Homepage', 'screens': 'Phones only',
        'where': 'Right under the top stories on a phone.',
    },
    Z.MOBILE_ANCHOR: {
        'page': 'Every page', 'screens': 'Phones only',
        'where': 'A small bar fixed to the bottom of the screen, on every page, while the reader scrolls.',
    },
    Z.ARTICLE_IN_CONTENT: {
        'page': 'Article pages', 'screens': 'All screens',
        'where': 'A box inside the article text: at the start of the text (computers and tablets), and after '
                 'paragraphs 4 and 14 of a long article.',
    },
    Z.ARTICLE_CONTENT_BANNER: {
        'page': 'Article pages', 'screens': 'All screens',
        'where': 'A strip inside the article text, after paragraph 9 of a long article.',
    },
    Z.ARTICLE_SIDEBAR: {
        'page': 'Article pages', 'screens': 'All screens',
        'where': 'The right-hand column next to the article, under the reading links (below the article on '
                 'phones).',
    },
    Z.ARTICLE_SIDEBAR_HALF_PAGE: {
        'page': 'Article pages', 'screens': 'All screens',
        'where': 'A tall box in the right-hand column, under the sidebar rectangle (below the article on phones).',
    },
}
