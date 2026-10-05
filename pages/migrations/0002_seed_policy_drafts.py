# Seeds Terms, Privacy and Refund policy as UNPUBLISHED drafts describing
# how the site actually works (VAT-exclusive prices, Fonepay, no automatic
# renewal, organization access by confirmed email, full refunds only).
# Senior staff review and publish them at /manage/pages/ — nothing here is
# public until then. Existing pages are never overwritten.
from django.conf import settings
from django.db import migrations


def _drafts():
    name = settings.JOURNAL_NAME
    business = getattr(settings, 'BUSINESS_LEGAL_NAME', '') or name
    email = settings.JOURNAL_CONTACT_EMAIL
    prefix = getattr(settings, 'RECEIPT_PREFIX', 'AHL-')
    vat = getattr(settings, 'VAT_RATE', 13)
    vat = f'{vat:f}'.rstrip('0').rstrip('.') if hasattr(vat, 'is_finite') else vat
    return {
        'terms': ('Terms of use', f'''
<p>These terms apply when you read, subscribe to or buy anything on {name}, which is run by {business}. By creating an
account or paying, you agree to them. Questions: <a href="mailto:{email}">{email}</a>.</p>

<h2>Your account</h2>
<p>Give us your real name and an email address you use. Keep your password to yourself — an account is for one person,
and sharing a login or a paid account is not allowed. You can ask us to close your account at any time.</p>

<h2>Prices, VAT and payment</h2>
<ul>
<li>Prices on the site are shown <strong>before VAT</strong>. VAT at {vat}% is added at checkout, and the total you pay is
shown before you pay.</li>
<li>Payments are made through Fonepay (QR or your bank's app). We never see or store your bank login or card details.</li>
<li>You get a numbered receipt by email for every payment, and can see all of them on your Billing page.</li>
</ul>

<h2>Subscriptions</h2>
<ul>
<li>A subscription is paid in advance for a fixed period (for example 30 or 365 days) shown on the plan.</li>
<li><strong>Subscriptions do not renew automatically.</strong> We email you before yours ends. If you renew early, the new
period starts the day after the current one ends, so you never lose days.</li>
<li>What each plan includes is listed on the plan's page. We may change plans and prices for the future; a change never
affects a period you have already paid for.</li>
</ul>

<h2>Special articles and training courses</h2>
<p>A special article you buy stays readable on your account. A training course enrollment gives you a place on that
course as described on its page; if we have to cancel or reschedule a course, we will offer you a refund.</p>

<h2>Access through your organization</h2>
<p>If your organization has an institutional subscription, you can read with it after confirming an email address at the
organization's domain. That access lasts while the organization's agreement with us is in place and you keep that
address; it ends when either ends.</p>

<h2>Refunds</h2>
<p>See our <a href="/refund-policy/">Refund policy</a>.</p>

<h2>Using our content</h2>
<p>Articles, images and videos on {name} are protected by copyright. You may read them and share links (including gift
links from a subscriber), and quote short extracts with credit and a link. You may not copy or republish whole articles,
resell access, or collect content automatically (scraping) without our written permission.</p>

<h2>Health information</h2>
<p>{name} publishes health news, research and commentary for information. It is <strong>not medical advice</strong> and is
no substitute for a qualified health professional. Do not delay or ignore medical advice because of something you read
here.</p>

<h2>Comments</h2>
<p>Be civil and on topic. We may remove comments, or block accounts, that are abusive, misleading, spam or unlawful.</p>

<h2>Changes and law</h2>
<p>We may update these terms; the date at the top of this page shows the latest version. These terms are governed by the
laws of Nepal.</p>
'''),
        'privacy': ('Privacy policy', f'''
<p>This policy explains what {business} collects when you use {name}, why, and the choices you have. Questions or
requests: <a href="mailto:{email}">{email}</a>.</p>

<h2>What we collect</h2>
<ul>
<li><strong>Your account:</strong> name, email address and password (stored scrambled, never in plain text), plus anything
you add to your profile.</li>
<li><strong>Payments:</strong> what you bought, the amount, VAT, and Fonepay's payment reference. Payment itself happens
with Fonepay and your bank — we never receive your bank login or card details.</li>
<li><strong>Reading:</strong> which articles are viewed, to count readership and recommend related stories. We keep these
records for about 13 months and then delete them.</li>
<li><strong>Newsletter and comments:</strong> your email address if you subscribe, and what you post in comments.</li>
<li><strong>Cookies:</strong> to keep you signed in, remember your language, protect forms, and (through Google Analytics)
measure how the site is used.</li>
</ul>

<h2>How we use it</h2>
<p>To run your account and give you what you paid for; to send receipts, renewal reminders and account emails; to send the
newsletter if you asked for it; to keep the site secure and stop abuse; and to understand what readers find useful.
We do not sell your personal information.</p>

<h2>Who we share it with</h2>
<p>Only the services that help us run the site: Fonepay (payments), our email provider (to deliver emails), our hosting
provider, and Google Analytics (usage statistics). If your organization gives you access, it may be told that you joined
its subscription. We also share information if the law requires it.</p>

<h2>How long we keep it</h2>
<p>Account information for as long as you have an account. Payment and receipt records for as long as tax and accounting
rules require. Reading statistics for about 13 months.</p>

<h2>Your choices</h2>
<p>You can update your profile at any time, unsubscribe from the newsletter using the link in every issue, and ask us to
see, correct or delete your information by writing to <a href="mailto:{email}">{email}</a>. Some records (such as receipts)
we must keep for legal reasons even after an account is closed.</p>

<h2>Changes</h2>
<p>We will update this page if anything changes; the date at the top shows the latest version.</p>
'''),
        'refund-policy': ('Refund policy', f'''
<p>We want you to be happy with what you pay for. Here is when you can get your money back, and how. To ask for a refund,
email <a href="mailto:{email}">{email}</a> with your <strong>receipt number</strong> (for example {prefix}000123 — it's
on your receipt email and your Billing page).</p>

<h2>Subscriptions</h2>
<p>You can get a full refund if you ask within <strong>7 days</strong> of paying. After that, a subscription runs until the
end of the period you paid for; it isn't refunded part-way. Subscriptions never renew automatically, so there is nothing
to cancel.</p>

<h2>Special articles</h2>
<p>A special article is unlocked as soon as you pay, so it isn't refundable — except when something went wrong (see
below).</p>

<h2>Training courses</h2>
<p>Full refund if you ask at least <strong>7 days before the course starts</strong> (or, for a course you can start any
time, within 7 days of enrolling and before you've started). If we cancel or move a course and the new date doesn't suit
you, you get a full refund.</p>

<h2>When something went wrong</h2>
<p>If you were charged twice, paid for something you already had, or paid but didn't get access, tell us and we'll refund
the extra payment in full.</p>

<h2>Organizations</h2>
<p>Refunds for institutional subscriptions follow the agreement with your organization.</p>

<h2>How refunds are paid</h2>
<p>Refunds are always for the full amount you paid, including VAT, and go back the way you paid — normally within 7
working days of our approving them, though your bank may take a few more days. You'll receive a credit note by email,
and the access that came with the payment ends.</p>
'''),
    }


def seed(apps, schema_editor):
    SitePage = apps.get_model('pages', 'SitePage')
    for slug, (title, body) in _drafts().items():
        if not SitePage.objects.filter(slug=slug).exists():
            SitePage.objects.create(
                slug=slug, title=title, title_en=title, body=body.strip(), body_en=body.strip(), is_published=False,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('pages', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
