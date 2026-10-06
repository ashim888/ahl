"""Terms / Privacy / Refund policy pages."""
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from billing.models import SubscriptionPlan
from users.models import User

from .models import SitePage


def make_user(email, role=User.Role.UNVERIFIED):
    return User.objects.create_user(email=email, password='pw', first_name='P', last_name='G', role=role)


class SitePageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.eic = make_user('eic-pages@example.com', User.Role.EDITOR_IN_CHIEF)

    def test_drafts_are_seeded_unpublished_and_hidden(self):
        self.assertEqual(
            sorted(SitePage.objects.values_list('slug', 'is_published')),
            [('faq', False), ('privacy', False), ('refund-policy', False), ('terms', False)],
        )
        for name in ('terms', 'privacy', 'refunds', 'faq'):
            self.assertEqual(self.client.get(reverse(f'pages:{name}')).status_code, 404, name)
        self.assertNotContains(self.client.get(reverse('articles:home')), '/terms/')

    def test_drafts_describe_how_billing_works(self):
        terms = SitePage.objects.get(slug='terms').body
        self.assertIn('do not renew automatically', terms)
        self.assertIn('VAT at 13%', terms)
        self.assertIn('not medical advice', terms)
        self.assertIn('7 days', SitePage.objects.get(slug='refund-policy').body)

    def test_senior_staff_preview_a_draft(self):
        self.client.force_login(self.eic)
        response = self.client.get(reverse('pages:terms'))
        self.assertContains(response, 'Draft — only Editors-in-Chief and Admins')

    def test_publishing_puts_it_in_the_footer_and_checkout(self):
        self.client.force_login(self.eic)
        for slug in ('terms', 'refund-policy'):
            page = SitePage.objects.get(slug=slug)
            self.client.post(reverse('pages:manage_page_update', args=[slug]), {
                'title_en': page.title_en, 'body_en': page.body_en, 'title_ne': '', 'body_ne': '', 'is_published': 'on',
            })
        reader = make_user('reader-pages@example.com')
        self.client.force_login(reader)
        home = self.client.get(reverse('articles:home'))
        self.assertContains(home, 'href="/terms/"')
        self.assertContains(home, 'href="/refund-policy/"')
        self.assertNotContains(home, 'href="/privacy/"')
        self.assertEqual(self.client.get('/terms/').status_code, 200)
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=499, duration_days=30,
        )
        with override_settings(PAYMENT_GATEWAY='stub'):
            checkout = self.client.get(reverse('billing:subscribe_checkout', args=[plan.pk]))
        self.assertContains(checkout, 'By paying you agree to our')
        self.assertContains(checkout, 'href="/refund-policy/"')

    def test_editing_saves_who_and_strips_scripts(self):
        self.client.force_login(self.eic)
        self.client.post(reverse('pages:manage_page_update', args=['privacy']), {
            'title_en': 'Privacy', 'body_en': '<p>Hello</p><script>alert(1)</script>', 'title_ne': 'गोपनीयता',
            'body_ne': '<p>नमस्ते</p>',
        })
        page = SitePage.objects.get(slug='privacy')
        self.assertEqual(page.updated_by, self.eic)
        self.assertNotIn('<script', page.body_en)
        self.assertNotIn('alert', page.body_en)
        self.assertIn('<p>Hello</p>', page.body_en)
        self.assertFalse(page.is_published)

    def test_nepali_falls_back_to_english_until_written(self):
        page = SitePage.objects.get(slug='terms')
        page.is_published = True
        page.save()
        with translation.override('ne'):
            self.assertEqual(page.title, 'Terms of use')
            page.title_ne = 'प्रयोगका सर्तहरू'
            page.save()
            self.assertEqual(SitePage.objects.get(pk=page.pk).title, 'प्रयोगका सर्तहरू')

    def test_only_senior_staff_edit(self):
        self.client.force_login(make_user('editor-pages@example.com', User.Role.EDITOR))
        self.assertEqual(self.client.get(reverse('pages:manage_page_list')).status_code, 403)
        self.assertEqual(self.client.post(reverse('pages:manage_page_update', args=['terms']), {'title_en': 'x'}).status_code, 403)


class NoAdsOnMoneyPagesTests(TestCase):
    """Checkout, billing, receipts and policy pages never show the
    site-wide ads (base.html's header_ad / anchor_ad blocks)."""

    def test_header_ad_is_left_out(self):
        from ads.models import AdSlot
        from ads.tests import demo_image

        cache.clear()
        AdSlot.objects.create(
            sponsor_name='Sponsor', zone=AdSlot.Zone.HEADER_LEADERBOARD, image=demo_image(size=(728, 90)),
            link_url='https://sponsor.example/',
        )
        eic = make_user('eic-noads@example.com', User.Role.EDITOR_IN_CHIEF)
        self.client.force_login(eic)
        self.assertContains(self.client.get(reverse('articles:home')), 'Sponsor (advertisement)')
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=499, duration_days=30,
        )
        for url in (reverse('billing:account'), reverse('pages:terms'), reverse('billing:subscribe_checkout', args=[plan.pk])):
            self.assertNotContains(self.client.get(url), 'alt="Sponsor', msg_prefix=url)


class BroaderDraftsMigrationTests(TestCase):
    """pages/migrations/0003 replaces untouched drafts only."""

    def _run(self):
        import importlib

        from django.apps import apps

        module = importlib.import_module('pages.migrations.0003_broader_policy_drafts')
        module.update_untouched_drafts(apps, None)

    def test_drafts_cover_the_whole_site(self):
        terms = SitePage.objects.get(slug='terms').body_en
        for topic in ('Author verification', 'Things you send us', 'Community rules', 'Gift links', 'Training courses',
                      'not medical advice', 'do not renew automatically'):
            self.assertIn(topic, terms)
        privacy = SitePage.objects.get(slug='privacy').body_en
        for topic in ('Comments:', 'Story pitches:', 'Security:', 'YouTube', 'Cloudflare Turnstile', 'Cookies'):
            self.assertIn(topic, privacy)
        refunds = SitePage.objects.get(slug='refund-policy')
        self.assertEqual(refunds.title_en, 'Refunds & cancellations')
        self.assertIn('Newsletter:', refunds.body_en)

    def test_edited_or_published_pages_are_left_alone(self):
        eic = make_user('eic-keep@example.com', User.Role.EDITOR_IN_CHIEF)
        SitePage.objects.filter(slug='terms').update(body_en='<p>Ours</p>', updated_by=eic)
        SitePage.objects.filter(slug='privacy').update(body_en='<p>Live</p>', is_published=True)
        self._run()
        self.assertEqual(SitePage.objects.get(slug='terms').body_en, '<p>Ours</p>')
        self.assertEqual(SitePage.objects.get(slug='privacy').body_en, '<p>Live</p>')
