# Brings the (still unedited, unpublished) policy drafts in line with the
# privacy tools added alongside: cookie consent, the Privacy & data page
# (download, email preferences, self-service deletion), one-click
# unsubscribe, consent at sign-up and the daily retention clean-up. Builds
# on 0003's text; pages anyone has edited or published are left alone.
import importlib
import re

from django.db import migrations

_base = importlib.import_module('pages.migrations.0003_broader_policy_drafts')


def _flat(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


# (page slug, old text, new text) — old text exactly as in 0003, whitespace-insensitive.
CHANGES = [
    ('privacy', '''<h2>4. Cookies</h2>
<ul>
<li><strong>Essential:</strong> keeping you signed in, remembering your language, protecting forms against forgery, and
counting free articles. The site doesn't work properly without these.</li>
<li><strong>Analytics:</strong> Google Analytics cookies, to measure how the site is used.</li>
</ul>
<p>You can block or delete cookies in your browser; if you block essential cookies you won't be able to sign in.</p>''',
     '''<h2>4. Cookies</h2>
<ul>
<li><strong>Essential</strong> (always on): keeping you signed in, remembering your language and your cookie choice,
protecting forms against forgery, and counting free articles. The site doesn't work properly without these.</li>
<li><strong>Analytics</strong> (only if you agree): Google Analytics cookies, to measure how the site is used. On your
first visit we ask; Google Analytics doesn't load until you choose "Accept analytics".</li>
</ul>
<p>You can change your choice at any time from "Cookie settings" at the bottom of every page. Choosing "Only
essential" deletes the analytics cookies straight away. We ask again after 6 months.</p>'''),
    ('privacy', '''<li>Account, profile and preferences: while you have an account.</li>
<li>Reading and advertising statistics: about''',
     '''<li>Account, profile and preferences: while you have an account. When you delete it, they're deleted at once.</li>
<li>Reading and advertising statistics: about'''),
    ('privacy', '''<li>Sign-in attempt records: for a limited time for security.</li>
<li>Newsletter: until you unsubscribe.</li>''',
     '''<li>IP addresses stored with comments: 90 days, then removed automatically.</li>
<li>Sign-in attempt records: 90 days.</li>
<li>Newsletter: until you unsubscribe. Sign-ups never confirmed are deleted after 30 days.</li>'''),
    ('privacy', '''<h2>7. Your choices and rights</h2>
<p>You can update your profile at any time, unfollow topics, delete saved articles, and unsubscribe from the newsletter
using the link in every issue. You can ask us to give you a copy of your information, correct it, or delete it — write
to {contact}. We'll reply within 30 days. Some records (such as receipts) we must keep for legal reasons.</p>''',
     '''<h2>7. Your choices and rights</h2>
<p>Signed in, your <a href="/account/privacy/">Privacy &amp; data</a> page lets you, at any time:</p>
<ul>
<li><strong>download a copy</strong> of everything linked to your account (profile, subscriptions, payments, saved
articles, follows, comments, pitches);</li>
<li><strong>choose which emails you get</strong> — newsletter, weekly digest, renewal reminders. Every one of these
emails also has its own unsubscribe link;</li>
<li><strong>change your cookie choice</strong>;</li>
<li><strong>delete your account</strong>. Your profile, files, follows, saved articles, newsletter subscription and
sign-in history are deleted straight away. Receipts are kept because tax law requires it, and anything already
published (comments, articles you're credited on) stays with your name removed — or you can choose to remove your
comments too.</li>
</ul>
<p>You can correct your profile yourself. For anything else — or if you can't sign in — write to {contact} and we'll
reply within 30 days. You can also complain to the authorities responsible for privacy where you live.</p>'''),
    ('terms', '''<h2>16. Suspending or closing accounts</h2>
<p>You can ask us to close your account at any time.''',
     '''<h2>16. Suspending or closing accounts</h2>
<p>You can delete your account at any time from your Privacy &amp; data page (or ask us to).'''),
    ('terms', '''<li>If you are under 18, use the site with your parent's or guardian's permission.</li>''',
     '''<li>If you are under 18, use the site with your parent's or guardian's permission.</li>
<li>When you create an account you agree to these terms and our Privacy policy; we record when you did.</li>'''),
    ('refund-policy', '''<li><strong>Your account:</strong> email us and we'll close it.''',
     '''<li><strong>Your account:</strong> delete it yourself from your Privacy &amp; data page, or email us.'''),
    ('refund-policy', '''<li><strong>Comment reply emails:</strong> use the link in the email to stop them.</li>''',
     '''<li><strong>Comment reply emails, the weekly digest and renewal reminders:</strong> use the link in the email, or
your Privacy &amp; data page, to stop them.</li>'''),
]


def apply_changes(apps, schema_editor):
    SitePage = apps.get_model('pages', 'SitePage')
    drafts = _base._drafts()
    contact = re.search(r'<a href="mailto:[^"]+">[^<]+</a>', drafts['privacy'][1]).group(0)
    for slug, (title, body) in drafts.items():
        text = _flat(body)
        for page_slug, old, new in CHANGES:
            if page_slug != slug:
                continue
            old, new = _flat(old.replace('{contact}', contact)), _flat(new.replace('{contact}', contact))
            assert old in text, f'{slug}: text to replace not found: {old[:60]}'
            text = text.replace(old, new)
        body = _base._tidy(text)
        page = SitePage.objects.filter(slug=slug).first()
        if page is not None and not page.is_published and page.updated_by_id is None:
            page.title = page.title_en = title
            page.body = page.body_en = body
            page.save(update_fields=['title', 'title_en', 'body', 'body_en'])


class Migration(migrations.Migration):

    dependencies = [
        ('pages', '0003_broader_policy_drafts'),
    ]

    operations = [
        migrations.RunPython(apply_changes, migrations.RunPython.noop),
    ]
