# Adds the FAQ page (/faq/) as an UNPUBLISHED draft written to match how the
# site works today. Senior staff review and publish it at /manage/pages/.
# Each <h3> is one question — the page also emits FAQPage structured data
# from them (pages/views.py faq_structured_data).
from django.conf import settings
from django.db import migrations, models


def _faq():
    email = settings.JOURNAL_CONTACT_EMAIL
    days = getattr(settings, 'SUBSCRIPTION_CANCEL_DAYS', 3)
    vat = getattr(settings, 'VAT_RATE', 13)
    vat = f'{vat:f}'.rstrip('0').rstrip('.') if hasattr(vat, 'is_finite') else vat
    return f'''
<p>Can't find your answer here? Write to <a href="mailto:{email}">{email}</a> — we reply within two working days.</p>

<h2>Reading</h2>
<h3>Is it free to read?</h3>
<p>Most of our news is free. Some articles are for subscribers; every month you can read a few of those free too —
the article shows how many you have left. A few special reports are sold one at a time.</p>
<h3>Can I read in Nepali?</h3>
<p>The site's menus, buttons and pages switch to Nepali with the language switch at the top of the page. Each article
appears in the language it was written in.</p>
<h3>Can I share a subscriber article with a friend?</h3>
<p>Yes. Subscribers can send a few gift links each month — whoever opens one reads that article free, no account needed.</p>
<h3>Is what I read here medical advice?</h3>
<p>No. Our reporting is general information and can't replace a doctor or health worker who knows your situation.
In an emergency, call 102 or go to the nearest hospital.</p>
<h3>What do you do when you get something wrong?</h3>
<p>We correct it and say so at the end of the article. Every correction is listed on our <a href="/corrections/">Corrections</a>
page. To tell us about a mistake, use "Report it" on the article.</p>

<h2>Subscriptions and payments</h2>
<h3>How much does a subscription cost?</h3>
<p>See <a href="/subscribe/">our plans</a>. Prices are shown before VAT; {vat}% VAT is added at checkout and the total
is shown before you pay.</p>
<h3>How do I pay?</h3>
<p>With Fonepay — scan the QR code with your bank or wallet app. We never see your bank login or card details.</p>
<h3>Does my subscription renew automatically?</h3>
<p>No. We email you 7 days and 1 day before it ends. Renew early and the new period starts the day after the current
one ends, so you never lose days.</p>
<h3>Can I cancel?</h3>
<p>Yes — within {days} days of paying, use <em>Cancel &amp; refund</em> on your Billing page and you get the full amount
back. After that, your subscription runs to the end of the period you paid for. See our Refunds &amp; cancellations
policy for articles and courses.</p>
<h3>Where are my receipts? Can I get a tax invoice with my PAN?</h3>
<p>Every receipt is emailed to you and listed on your Billing page. Add your PAN at checkout and it's printed on the
invoice.</p>
<h3>I paid but I can't read the article.</h3>
<p>Wait a minute and refresh — some banks confirm payments slowly. If it still doesn't work, email us with the
reference from your Billing page and we'll sort it out.</p>

<h2>Organizations</h2>
<h3>Does my hospital, university or office have a subscription?</h3>
<p>If it does, sign up with your work email address and click the confirmation link we send you — you'll read with
your organization's plan straight away. If it doesn't, ask them to write to <a href="mailto:{email}">{email}</a>.</p>
<h3>What does my organization see about my reading?</h3>
<p>Its managers see how many articles you read and when you last read — never which articles.</p>

<h2>Your account</h2>
<h3>Do I need an account?</h3>
<p>Not to read free articles, comment (we confirm your email instead) or send us a story idea. You need one to
subscribe, buy an article or enrol in a course.</p>
<h3>How do I stop emails?</h3>
<p>Every newsletter and reminder has an unsubscribe link. You can also switch each kind of email off on your
<em>Privacy &amp; your data</em> page.</p>
<h3>How do I download or delete my data?</h3>
<p>On your <em>Privacy &amp; your data</em> page (from your profile) you can download everything we hold about you and
delete your account. Receipts are kept for tax law.</p>

<h2>Writing for us</h2>
<h3>Can I pitch a story?</h3>
<p>Yes — use <a href="/pitches/new/">Pitch a story</a>. An editor reads every pitch and emails you with the outcome.</p>
<h3>Do you offer training?</h3>
<p>Yes — see <a href="/training/">our training courses</a>.</p>
'''


def seed(apps, schema_editor):
    SitePage = apps.get_model('pages', 'SitePage')
    if not SitePage.objects.filter(slug='faq').exists():
        body = _faq()
        SitePage.objects.create(slug='faq', title='Frequently asked questions', title_en='Frequently asked questions',
                                body=body, body_en=body, is_published=False)


class Migration(migrations.Migration):

    dependencies = [
        ('pages', '0007_organization_usage_in_privacy'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sitepage',
            name='slug',
            field=models.SlugField(choices=[('terms', 'Terms of use'), ('privacy', 'Privacy policy'),
                                            ('refund-policy', 'Refund policy'), ('faq', 'Frequently asked questions')],
                                   unique=True),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
