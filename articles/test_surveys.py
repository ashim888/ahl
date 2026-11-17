"""Embedded Google Form surveys (Article.survey_url, articles/survey.py)."""
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .forms import ArticleForm, PublishArticleForm
from .models import Article
from .survey import google_form_embed_url, validate_google_form_url

FORM = 'https://docs.google.com/forms/d/e/1FAIpQLSdExampleFormId12345/viewform?usp=sf_link'
EMBED = 'https://docs.google.com/forms/d/e/1FAIpQLSdExampleFormId12345/viewform?embedded=true'


class SurveyLinkTests(TestCase):
    def test_share_links_become_embeds(self):
        self.assertEqual(google_form_embed_url(FORM), EMBED)
        self.assertEqual(google_form_embed_url('https://docs.google.com/forms/d/1AbCdEfGhIjKlMn/edit'),
                         'https://docs.google.com/forms/d/1AbCdEfGhIjKlMn/viewform?embedded=true')
        for bad in ('https://evil.example/forms/d/e/1FAIpQLSdExample/viewform',
                    'https://docs.google.com/document/d/abc123456789/edit', ''):
            self.assertEqual(google_form_embed_url(bad), '')

    def test_short_links_refused_with_a_hint(self):
        with self.assertRaisesMessage(ValidationError, 'docs.google.com/forms/'):
            validate_google_form_url('https://forms.gle/AbC123')


class SurveyStoryTests(TestCase):
    data = {'title': 'Tell us about your clinic', 'article_type': 'survey', 'access_type': 'open_access',
            'featured_image_fit': 'auto'}

    def test_survey_needs_link_which_is_enough_to_publish(self):
        form = ArticleForm(data=self.data)
        self.assertFalse(form.is_valid())
        self.assertIn('survey_url', form.errors)
        self.assertTrue(PublishArticleForm(data={**self.data, 'survey_url': FORM}).is_valid())

    def test_embedded_for_every_reader_even_on_a_paid_story(self):
        from unittest.mock import patch

        article = Article.objects.create(title='Clinic survey', status=Article.Status.PUBLISHED,
                                         article_type=Article.ArticleType.NEWS_COMMENTARY, survey_url=FORM,
                                         access_type=Article.AccessType.SUBSCRIPTION, html_content='<p>Text.</p>')
        with patch('billing.access.FREE_SAMPLE_LIMIT_PER_MONTH', 0):
            response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertFalse(response.context['show_full_text'])
        self.assertContains(response, f'src="{EMBED.replace("&", "&amp;")}"')
        from django.conf import settings

        self.assertIn('https://docs.google.com', settings.CSP_DIRECTIVES['frame-src'])  # or the browser blocks it
