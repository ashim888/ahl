"""Editor helpers: the one/two-line summary generator (articles/summarize.py),
the slug checker (static/js/slug_quality.js + its Chrome extension copy) and
romanized slugs for Nepali headlines (articles/transliterate.py)."""
import json
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from users.models import User

from .models import Article
from .summarize import sentences, suggest
from .transliterate import romanize

ROOT = Path(settings.BASE_DIR)
CHECKER = ROOT / 'static' / 'js' / 'slug_quality.js'
EXTENSION_COPY = ROOT / 'tools' / 'slug-checker-extension' / 'slug_quality.js'

BODY = '''
<p>Dengue cases in Kathmandu rose to 4,200 this week, up 35% from last year, the Health Ministry said on Sunday.</p>
<p>He added that hospitals were preparing extra beds. "We are ready for a bigger wave," Dr. Rai told reporters.</p>
<figure><img src="x.jpg" alt=""><figcaption>Patients wait at Teku hospital.</figcaption></figure>
<p>Experts say clearing standing water around homes is still the best protection against the mosquitoes.</p>
'''


class SentenceSplittingTests(TestCase):
    def test_abbreviations_do_not_end_sentences(self):
        self.assertEqual(
            sentences('Dr. Rai said 40% of cases rise. It is bad. एपेन्डिक्स ५–१० से.मी. लामो हुन्छ। यो सानो छ।'),
            ['Dr. Rai said 40% of cases rise.', 'It is bad.', 'एपेन्डिक्स ५–१० से.मी. लामो हुन्छ।', 'यो सानो छ।'],
        )


class SummarizeTests(TestCase):
    def test_suggestions_come_from_the_article_and_lead_with_the_key_fact(self):
        options = suggest('Dengue cases rise in Kathmandu', BODY, ['Dengue'])
        self.assertTrue(1 <= len(options) <= 3)
        self.assertTrue(options[0]['text'].startswith('Dengue cases in Kathmandu rose to 4,200'))
        for option in options:
            self.assertLessEqual(option['chars'], 280)
            self.assertNotIn('Teku', option['text'])  # captions are skipped
        self.assertEqual(len({o['text'] for o in options}), len(options))

    def test_sentence_needing_context_is_not_the_lead(self):
        options = suggest('Hospitals prepare', '<p>He added that hospitals were preparing extra beds for patients today.</p>'
                          '<p>Hospitals across Nepal are preparing extra beds as dengue cases rise sharply this month.</p>')
        self.assertTrue(options[0]['text'].startswith('Hospitals across Nepal'))

    def test_nepali(self):
        body = '<p>नेपालमा यस वर्ष डेंगुका बिरामी ४० प्रतिशतले बढेका छन् भने काठमाडौंमा सबैभन्दा बढी संक्रमण देखिएको छ।</p><p>उनले भने।</p>'
        options = suggest('डेंगु बढ्यो', body, ['डेंगु'])
        self.assertIn('४० प्रतिशत', options[0]['text'])

    def test_empty_text(self):
        self.assertEqual(suggest('Title', ''), [])
        self.assertEqual(suggest('Title', '<p>Short.</p>'), [])


class SummaryEndpointTests(TestCase):
    url = reverse('articles:manage_article_summary_suggestions')

    def test_editors_get_suggestions(self):
        editor = User.objects.create_user(email='ed@example.com', password='pw', first_name='E', last_name='D',
                                          role=User.Role.EDITOR)
        self.client.force_login(editor)
        response = self.client.post(self.url, {'title': 'Dengue cases rise', 'html': BODY, 'keywords': 'Dengue'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)['suggestions'])

    def test_readers_and_get_requests_refused(self):
        reader = User.objects.create_user(email='r@example.com', password='pw', first_name='R', last_name='D')
        self.client.force_login(reader)
        self.assertEqual(self.client.post(self.url, {'html': BODY}).status_code, 403)


class RomanizedSlugTests(TestCase):
    CASES = {
        'निःसन्तान पनको समस्या र समाधान': 'nihsantan panako samasya ra samadhan',
        'मानसिक स्वास्थ्य': 'manasik swasthya', 'राष्ट्र': 'rashtra', 'क्षयरोग': 'kshayarog', 'ज्ञान': 'gyan',
        'डेंगु': 'dengu', 'नेपाल २०८३': 'nepal 2083', 'Dengue in Nepal': 'Dengue in Nepal',
    }

    def test_romanize(self):
        for text, expected in self.CASES.items():
            self.assertEqual(romanize(text), expected, text)

    def test_nepali_headline_gets_a_readable_slug(self):
        article = Article.objects.create(title='मानसिक स्वास्थ्य र युवा')
        self.assertTrue(article.slug.startswith('manasik-swasthya-ra-yuwa-'), article.slug)

    def test_english_headline_slug_unchanged(self):
        article = Article.objects.create(title='Dengue cases rise')
        self.assertTrue(article.slug.startswith('dengue-cases-rise-'))


class SlugCheckerTests(TestCase):
    def test_extension_copy_matches_the_site_copy(self):
        self.assertEqual(CHECKER.read_text(), EXTENSION_COPY.read_text(),
                         'Run `npm run build:extension` after editing static/js/slug_quality.js.')

    def test_editor_loads_the_checker(self):
        editor = User.objects.create_user(email='ed2@example.com', password='pw', first_name='E', last_name='D',
                                          role=User.Role.EDITOR)
        self.client.force_login(editor)
        response = self.client.get(reverse('articles:manage_article_create'))
        self.assertContains(response, 'js/slug_quality.js')
        self.assertContains(response, 'id="slug-helper"')
        self.assertContains(response, 'id="summary-helper"')

    def test_js_and_python_romanizers_agree(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node not installed')
        script = (f'const S=require({json.dumps(str(CHECKER))});'
                  f'const cases={json.dumps(list(RomanizedSlugTests.CASES), ensure_ascii=False)};'
                  'console.log(JSON.stringify(cases.map(c=>S.romanize(c))));')
        output = subprocess.run([node, '-e', script], capture_output=True, text=True, timeout=30, check=True).stdout
        self.assertEqual(json.loads(output), [romanize(text) for text in RomanizedSlugTests.CASES])

    def test_node_suite_passes(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node not installed')
        result = subprocess.run([node, '--test', str(ROOT / 'tools/slug-checker-extension/test/slug_quality.test.js')],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout[-2000:])
