"""Article.translation: the same story in the other language, linked both ways."""
from django.test import TestCase
from django.urls import reverse

from .forms import ArticleForm
from .models import Article


def story(title, **extra):
    return Article.objects.create(title=title, status=Article.Status.PUBLISHED, html_content='<p>x</p>', **extra)


class TranslationLinkTests(TestCase):
    def setUp(self):
        self.ne = story('डेंगुका बिरामी बढे')
        self.en = story('Dengue cases rise')

    def refresh(self, *articles):
        for article in articles:
            article.refresh_from_db()

    def test_linking_one_links_both(self):
        self.ne.translation = self.en
        self.ne.save()
        self.refresh(self.en)
        self.assertEqual(self.en.translation, self.ne)

    def test_relinking_frees_the_old_partner_and_unlinking_clears_both(self):
        self.ne.translation = self.en
        self.ne.save()
        other = story('Dengue: what to do')
        self.ne.translation = other
        self.ne.save()
        self.refresh(self.en, other)
        self.assertIsNone(self.en.translation)
        self.assertEqual(other.translation, self.ne)
        # Linking the partner elsewhere frees this one too.
        third = story('तेस्रो')
        other.translation = third
        other.save()
        self.refresh(self.ne, third)
        self.assertIsNone(self.ne.translation)
        self.assertEqual(third.translation, other)
        other.translation = None
        other.save()
        self.refresh(third)
        self.assertIsNone(third.translation)

    def test_article_page_links_the_other_language(self):
        self.ne.translation = self.en
        self.ne.save()
        response = self.client.get(reverse('articles:article_detail', args=[self.ne.slug]))
        self.assertContains(response, 'Read this story in English')
        self.assertContains(response, 'hreflang="en"')
        response = self.client.get(reverse('articles:article_detail', args=[self.en.slug]))
        self.assertContains(response, 'यो लेख नेपालीमा पढ्नुहोस्')

    def test_unpublished_partner_not_linked_for_readers(self):
        self.ne.translation = self.en
        self.ne.save()
        Article.objects.filter(pk=self.en.pk).update(status=Article.Status.DRAFT)
        response = self.client.get(reverse('articles:article_detail', args=[self.ne.slug]))
        self.assertNotContains(response, 'Read this story in English')

    def test_saving_the_published_version_keeps_a_draft_translation(self):
        draft = Article.objects.create(title='Dengue (English draft)', status=Article.Status.DRAFT, translation=self.ne)
        data = {'title': self.ne.title, 'article_type': 'news_commentary', 'access_type': 'open_access',
                'featured_image_fit': 'cover', 'html_content': '<p>typo fixed</p>',
                'translation_pick': f'[{{"id": {draft.pk}}}]'}  # what the form sends back for the linked draft
        form = ArticleForm(data=data, instance=self.ne)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.refresh(self.ne, draft)
        self.assertEqual(self.ne.translation, draft)
        self.assertEqual(draft.translation, self.ne)

    def test_form_picks_one(self):
        data = {'title': 'Dengue', 'article_type': 'news_commentary', 'access_type': 'open_access',
                'featured_image_fit': 'cover', 'html_content': '<p>x</p>'}
        form = ArticleForm(data={**data, 'translation_pick': f'[{{"id": {self.ne.pk}}}]'}, instance=self.en)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.refresh(self.ne)
        self.assertEqual(self.ne.translation, self.en)
        two = f'[{{"id": {self.ne.pk}}}, {{"id": {story("x").pk}}}]'
        self.assertFalse(ArticleForm(data={**data, 'translation_pick': two}, instance=self.en).is_valid())
        # A form that doesn't send the picker leaves the link alone.
        ArticleForm(data=data, instance=self.en).save()
        self.refresh(self.ne)
        self.assertEqual(self.ne.translation, self.en)
