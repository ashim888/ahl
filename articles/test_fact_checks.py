"""Fact checks: the story type, its verdict box, ClaimReview, /fact-checks/."""
import json
import re

from django.test import TestCase
from django.urls import reverse

from users.models import User

from .forms import ArticleForm
from .models import Article


def fact_check(title='Hot water does not cure dengue', verdict='false', **kwargs):
    kwargs.setdefault('status', Article.Status.PUBLISHED)
    kwargs.setdefault('html_content', '<p>The evidence.</p>')
    return Article.objects.create(
        title=title, article_type=Article.ArticleType.FACT_CHECK,
        fact_check_claim='Drinking hot water every hour cures dengue.',
        fact_check_claim_source='Viral Facebook posts',
        fact_check_claim_url='https://web.archive.org/web/2026/https://facebook.com/post/1',
        fact_check_verdict=verdict,
        fact_check_verdict_summary='No study shows hot water kills the dengue virus in the body.', **kwargs)


class FactCheckPageTests(TestCase):
    def test_verdict_box_and_chip(self):
        article = fact_check()
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, 'class="fact-check-box verdict--false')
        self.assertContains(response, 'Drinking hot water every hour cures dengue.')
        self.assertContains(response, 'Viral Facebook posts')
        self.assertContains(response, 'verdict-chip verdict-chip--false')

    def test_always_free_whatever_access_was_chosen(self):
        from unittest.mock import patch

        article = fact_check(access_type=Article.AccessType.PAY_PER_ARTICLE, price=50)
        self.assertEqual((article.access_type, article.price), (Article.AccessType.OPEN_ACCESS, None))
        with patch('billing.access.FREE_SAMPLE_LIMIT_PER_MONTH', 0):  # no free reads left: still the whole story
            response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertTrue(response.context['show_full_text'])
        self.assertContains(response, 'The evidence.')

    def test_claim_review_structured_data(self):
        article = fact_check(verdict='mostly_false')
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', response.content.decode(), re.S)
        review = next(json.loads(b) for b in blocks if '"ClaimReview"' in b)
        self.assertEqual(review['claimReviewed'], 'Drinking hot water every hour cures dengue.')
        self.assertEqual(review['reviewRating']['ratingValue'], 2)
        self.assertEqual(review['reviewRating']['alternateName'], 'Mostly false')
        self.assertEqual(review['itemReviewed']['author']['name'], 'Viral Facebook posts')

    def test_unproven_has_no_number(self):
        article = fact_check(verdict='unproven')
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertIn('"alternateName": "Unproven"', response.content.decode())
        self.assertNotIn('"ratingValue"', response.content.decode())

    def test_ordinary_article_has_no_box(self):
        article = Article.objects.create(title='News', status=Article.Status.PUBLISHED, html_content='<p>x</p>')
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertNotContains(response, 'fact-check-box')
        self.assertNotContains(response, 'ClaimReview')


class FactCheckListTests(TestCase):
    def test_list_and_verdict_filter(self):
        false = fact_check('False one', 'false')
        true = fact_check('True one', 'true')
        fact_check('Draft one', 'false', status=Article.Status.DRAFT)
        url = reverse('articles:fact_check_list')
        response = self.client.get(url)
        self.assertCountEqual(response.context['fact_checks'], [false, true])
        self.assertEqual(response.context['total_count'], 2)
        self.assertEqual(list(self.client.get(url, {'verdict': 'true'}).context['fact_checks']), [true])
        self.assertEqual(len(self.client.get(url, {'verdict': 'nonsense'}).context['fact_checks']), 2)

    def test_menu_can_link_to_it(self):
        from sections.forms import LINK_TARGETS

        self.assertIn('articles:fact_check_list', dict(LINK_TARGETS))


class FactCheckFormTests(TestCase):
    def form(self, **extra):
        data = {'title': 'A check', 'article_type': 'fact_check', 'access_type': 'open_access',
                'featured_image_fit': 'cover', 'html_content': '<p>x</p>'}
        data.update(extra)
        return ArticleForm(data=data)

    def test_paid_access_is_overridden_not_an_error(self):
        form = self.form(fact_check_claim='c', fact_check_verdict='false', fact_check_verdict_summary='s',
                         access_type='pay_per_article')  # no price: would normally be refused
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().access_type, Article.AccessType.OPEN_ACCESS)

    def test_claim_verdict_and_reason_required_for_fact_checks(self):
        form = self.form()
        self.assertFalse(form.is_valid())
        for field in ('fact_check_claim', 'fact_check_verdict', 'fact_check_verdict_summary'):
            self.assertIn(field, form.errors)
        form = self.form(fact_check_claim='Claim', fact_check_verdict='false', fact_check_verdict_summary='Why.')
        self.assertTrue(form.is_valid(), form.errors)

    def test_other_types_unaffected(self):
        form = self.form(article_type='news_commentary')
        self.assertTrue(form.is_valid(), form.errors)

    def test_editor_form_page_has_the_fields(self):
        editor = User.objects.create_user(email='fc@example.com', password='pw', first_name='F', last_name='C',
                                          role=User.Role.EDITOR)
        self.client.force_login(editor)
        response = self.client.get(reverse('articles:manage_article_create'))
        self.assertContains(response, 'id="fact-check-fields"')
        self.assertContains(response, 'name="fact_check_verdict"')

    def test_one_click_publish_refuses_fact_check_without_verdict(self):
        editor = User.objects.create_user(email='qp@example.com', password='pw', first_name='Q', last_name='P',
                                          role=User.Role.EDITOR_IN_CHIEF)
        self.client.force_login(editor)
        # What autosave leaves behind: a fact check with text but no verdict yet.
        draft = Article.objects.create(title='Half done', article_type=Article.ArticleType.FACT_CHECK,
                                       status=Article.Status.DRAFT, html_content='<p>Research so far.</p>')
        self.client.post(reverse('articles:manage_article_quick_publish', args=[draft.slug]))
        draft.refresh_from_db()
        self.assertEqual(draft.status, Article.Status.DRAFT)
        # Filled in, it publishes.
        draft.fact_check_claim, draft.fact_check_verdict = 'A claim.', 'false'
        draft.fact_check_verdict_summary = 'Why.'
        draft.save()
        self.client.post(reverse('articles:manage_article_quick_publish', args=[draft.slug]))
        draft.refresh_from_db()
        self.assertEqual(draft.status, Article.Status.PUBLISHED)

    def test_policies_explain_the_scale(self):
        response = self.client.get(reverse('editorial_board:public_list'), {'tab': 'policies'})
        self.assertContains(response, 'How We Rate Claims')
