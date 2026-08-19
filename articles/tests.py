import datetime

from django.test import TestCase
from django.urls import reverse

from .models import Article


def make_article(slug, article_type, status=Article.Status.PUBLISHED, homepage_section='', publication_date=None):
    return Article.objects.create(
        title=slug.replace('-', ' ').title(), slug=slug, abstract='Abstract',
        article_type=article_type, status=status, homepage_section=homepage_section,
        publication_date=publication_date,
    )


class HomeViewSectionCurationTests(TestCase):
    """Article.homepage_section lets an editor override the previously fully
    automatic (most-recent-by-type) homepage section selection — these cover
    curation taking priority, autofill still covering unfilled slots, and no
    article ever appearing in two sections at once.
    """

    def test_explicit_hero_wins_over_most_recent_article(self):
        older = make_article(
            'flagship-research', Article.ArticleType.ORIGINAL_RESEARCH,
            homepage_section=Article.HomepageSection.HERO, publication_date=datetime.date(2026, 1, 1),
        )
        make_article('breaking-news', Article.ArticleType.NEWS_COMMENTARY, publication_date=datetime.date(2026, 6, 1))

        response = self.client.get(reverse('articles:home'))
        self.assertEqual(response.context['hero_article'], older)

    def test_no_explicit_hero_falls_back_to_most_recent(self):
        make_article('older-piece', Article.ArticleType.NEWS_COMMENTARY, publication_date=datetime.date(2026, 1, 1))
        newest = make_article('newest-piece', Article.ArticleType.NEWS_COMMENTARY, publication_date=datetime.date(2026, 6, 1))

        response = self.client.get(reverse('articles:home'))
        self.assertEqual(response.context['hero_article'], newest)

    def test_latest_news_autofills_unfilled_slots(self):
        # An unrelated explicit Hero pick, so Hero's own fallback (no type
        # filter — see pick() in views.py) doesn't compete with Latest News
        # for the same pool of unflagged articles.
        make_article('unrelated-hero', Article.ArticleType.EDITORIAL, homepage_section=Article.HomepageSection.HERO)

        # Only one explicit pick, but the section holds 3 — the other 2
        # slots should still autofill from recent news_commentary articles.
        picked = make_article(
            'curated-news', Article.ArticleType.NEWS_COMMENTARY,
            homepage_section=Article.HomepageSection.LATEST_NEWS, publication_date=datetime.date(2026, 1, 1),
        )
        auto1 = make_article('auto-news-1', Article.ArticleType.NEWS_COMMENTARY, publication_date=datetime.date(2026, 6, 1))
        auto2 = make_article('auto-news-2', Article.ArticleType.NEWS_COMMENTARY, publication_date=datetime.date(2026, 5, 1))

        response = self.client.get(reverse('articles:home'))
        latest_news = response.context['latest_news']
        self.assertEqual(len(latest_news), 3)
        self.assertIn(picked, latest_news)
        self.assertIn(auto1, latest_news)
        self.assertIn(auto2, latest_news)

    def test_article_never_appears_in_two_sections(self):
        # Explicitly featured as Hero — even though it's also a
        # news_commentary article that would otherwise auto-fill Latest News.
        make_article(
            'dual-candidate', Article.ArticleType.NEWS_COMMENTARY,
            homepage_section=Article.HomepageSection.HERO, publication_date=datetime.date(2026, 6, 1),
        )

        response = self.client.get(reverse('articles:home'))
        hero = response.context['hero_article']
        latest_news = response.context['latest_news']
        self.assertNotIn(hero, latest_news)

    def test_homepage_section_overrides_article_type_routing(self):
        # A news_commentary article explicitly placed in Research Highlights
        # shows up there instead of (or as well as) Latest News.
        override = make_article(
            'reclassified-story', Article.ArticleType.NEWS_COMMENTARY,
            homepage_section=Article.HomepageSection.RESEARCH,
        )

        response = self.client.get(reverse('articles:home'))
        self.assertIn(override, response.context['research_highlights'])
        self.assertNotIn(override, response.context['latest_news'])

    def test_draft_articles_never_selected_even_if_flagged(self):
        make_article(
            'unpublished-hero-pick', Article.ArticleType.NEWS_COMMENTARY,
            status=Article.Status.DRAFT, homepage_section=Article.HomepageSection.HERO,
        )
        response = self.client.get(reverse('articles:home'))
        self.assertIsNone(response.context['hero_article'])
