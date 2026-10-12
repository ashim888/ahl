"""Nepali is the default language; a browser asking for English gets
English; the reader's choice (language switcher cookie) always wins; the
site name is Nepali on Nepali pages and English on English ones (the
copyright line always uses the registered English name).

The rest of the suite runs in English (test_runner.py), so these tests put
the real default back with override_settings."""
from django.test import TestCase, override_settings
from django.urls import reverse

NEPALI = override_settings(LANGUAGE_CODE='ne', JOURNAL_NAME='Ajna Health Lens', JOURNAL_NAME_NE='अज्ना हेल्थ लेन्स')


@NEPALI
class DefaultLanguageTests(TestCase):
    def test_settings_default_is_nepali(self):
        from importlib import import_module

        self.assertEqual(import_module('ajna_health_lens.settings').LANGUAGE_CODE, 'ne')

    def test_no_browser_preference_gets_nepali_and_the_nepali_name(self):
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, '<html lang="ne">')
        self.assertContains(response, 'अज्ना हेल्थ लेन्स')
        self.assertContains(response, 'सदस्यता लिनुहोस्')

    def test_browser_asking_for_english_gets_english(self):
        response = self.client.get(reverse('articles:home'), HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9')
        self.assertContains(response, '<html lang="en">')
        self.assertContains(response, 'AJNA HEALTH LENS')
        self.assertNotContains(response, 'अज्ना हेल्थ लेन्स')

    def test_switcher_choice_beats_the_browser(self):
        self.client.post(reverse('set_language'), {'language': 'ne', 'next': '/'})
        response = self.client.get(reverse('articles:home'), HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9')
        self.assertContains(response, '<html lang="ne">')

    def test_copyright_keeps_the_registered_english_name(self):
        with self.settings(BUSINESS_LEGAL_NAME=''):
            response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'Ajna Health Lens. ')
