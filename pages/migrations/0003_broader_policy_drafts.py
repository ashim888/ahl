# Replaces the first drafts (0002, payments-focused) with drafts covering the
# whole site: reading, accounts and author verification, comments, story
# pitches, newsletter, personalisation, gifts, training, organizations, ads,
# embeds and payments. Still UNPUBLISHED drafts for senior staff to review at
# /manage/pages/. A page that anyone has already edited or published is left
# exactly as it is.
import re

from django.conf import settings
from django.db import migrations


def _drafts():
    name = settings.JOURNAL_NAME
    business = getattr(settings, 'BUSINESS_LEGAL_NAME', '') or name
    address = getattr(settings, 'BUSINESS_ADDRESS', '')
    email = settings.JOURNAL_CONTACT_EMAIL
    vat = getattr(settings, 'VAT_RATE', 13)
    vat = f'{vat:f}'.rstrip('0').rstrip('.') if hasattr(vat, 'is_finite') else vat
    prefix = getattr(settings, 'RECEIPT_PREFIX', 'AHL-')
    retention_days = getattr(settings, 'ANALYTICS_RETENTION_DAYS', 400)
    who = f'{business}{f", {address}" if address else ""}'
    contact = f'<a href="mailto:{email}">{email}</a>'

    terms = f'''
<p>{name} is a health news and research publication run by {who} ("we", "us"). These terms apply to everyone who uses
the site — whether you just read, create an account, comment, pitch a story, subscribe, buy an article, join a training
course or read through your organization. By using the site you agree to them. If you have a question, write to
{contact}.</p>

<h2>1. Reading {name}</h2>
<ul>
<li>Many articles are free for everyone. Some are for subscribers, and some "special" articles can be bought one at a
time.</li>
<li>Without a subscription you can read a limited number of subscriber articles each month for free. We decide that
number and may change it.</li>
<li>Older articles may move to our archive, which needs a plan that includes archive access.</li>
</ul>

<h2>2. Your account</h2>
<ul>
<li>Use your real name and an email address you control, and keep your details up to date. One account is for one
person — don't share your login.</li>
<li>Keep your password safe and tell us straight away at {contact} if you think someone else has used your account.
After several wrong passwords we pause sign-in for a while to protect you.</li>
<li>If you are under 18, use the site with your parent's or guardian's permission.</li>
<li>We may ask you to confirm your email address — for example before you can read through your organization.</li>
</ul>

<h2>3. Author verification</h2>
<p>Researchers and writers can ask to be verified. You may be asked for your affiliation, ORCID, publications and a CV.
Our editors decide whether to verify an account, and may later withdraw verification (for example if information turns
out to be inaccurate). Verification is not an endorsement of your views or work.</p>

<h2>4. Subscriptions, purchases and payment</h2>
<ul>
<li>Prices are shown <strong>before VAT</strong>; VAT at {vat}% is added at checkout and the total is shown before you
pay. Payments go through Fonepay — we never see your bank login or card details. You get a numbered receipt by email
for every payment, and all of them are on your Billing page.</li>
<li>A subscription is paid in advance for the period shown on the plan. <strong>Subscriptions do not renew
automatically</strong>: we email you before yours ends. Renewing early adds the new period after the current one, so no
days are lost.</li>
<li>What a plan includes is listed on its page. We may change plans and prices for the future; a change never affects a
period you have already paid for.</li>
<li>A special article you buy stays readable on your account.</li>
<li>Refunds and cancellations are covered by our <a href="/refund-policy/">Refunds &amp; cancellations policy</a>.</li>
</ul>

<h2>5. Training courses</h2>
<p>Each course page describes the format, dates, instructor and whether a certificate is offered. A place is for the
person who enrolled. We may change an instructor, venue or date for good reason and will tell you in advance; if we
cancel a course, you get a full refund. Course materials are for your own learning and may not be shared or resold.
Certificates are issued only to people who complete the course's requirements.</p>

<h2>6. Reading through your organization</h2>
<p>If your organization has an institutional subscription, you can read with it after confirming an email address at
the organization's domain. Your access lasts while the organization's agreement with us is in place and you still use
that address. The organization may see that you joined its subscription.</p>

<h2>7. Gift links</h2>
<p>Some plans let subscribers share a limited number of subscriber articles each month through gift links. A gift link
opens one article for a limited time. Don't publish gift links widely or sell them.</p>

<h2>8. Our content and how you may use it</h2>
<ul>
<li>Articles, images, charts, videos and other material on {name} belong to us or to the people who licensed them to
us, and are protected by copyright.</li>
<li>You may read them, share links, and quote short extracts with credit to {name} and a link back.</li>
<li>Without our written permission you may not copy or republish whole articles, resell or share paid access, get around
the paywall, or collect content automatically (scraping, bulk downloading) — including to build datasets or train
artificial-intelligence models.</li>
<li>Articles we mark as free or open access may come with their own licence, shown on the article; where they do, that
licence applies.</li>
</ul>

<h2>9. Health information is not medical advice</h2>
<p>{name} publishes health news, research and commentary to inform. It is <strong>not medical advice</strong> and is no
substitute for a qualified health professional who knows your situation. Never delay or ignore medical advice because of
something you read here. In an emergency, contact your local emergency services.</p>

<h2>10. Editorial standards, opinion and corrections</h2>
<ul>
<li>Our editors decide what we publish, independently of advertisers, sponsors and subscribers.</li>
<li>Opinion pieces are the authors' own views, not necessarily ours. Research articles go through peer review before
publication as described on our Policies page.</li>
<li>We correct errors. If you spot one, write to {contact}; significant corrections are noted on the article.</li>
<li>Advertisements and sponsored material are labelled as such.</li>
</ul>

<h2>11. Things you send us — comments, pitches and drafts</h2>
<ul>
<li>You keep ownership of what you write. By sending it to us you allow us to publish, edit for length and clarity,
translate (for example into Nepali), and share it on {name}, in our newsletter and on our social channels, with credit to
you.</li>
<li>You confirm that it's your own work (or you have permission to share it), that it's accurate to the best of your
knowledge, and that it doesn't break anyone's rights or the law.</li>
<li>When we accept a story pitch, our editors work with you on the article and the published version may differ from
what you sent. We may decline any pitch without giving a reason.</li>
<li>Comments appear publicly with the name you give. Posting a comment without an account requires confirming it by
email.</li>
</ul>

<h2>12. Community rules</h2>
<p>Be civil and stay on topic. Don't post anything abusive, hateful, threatening, harassing, misleading (including
medical misinformation), spam, advertising, or anything that reveals someone's private or health information without
their consent. We may edit, hide or remove contributions, and suspend accounts, that break these rules.</p>

<h2>13. Things you must not do</h2>
<p>Don't impersonate anyone, interfere with the site's security or running (including probing for vulnerabilities
without our permission — if you find one, please tell us at {contact}), overload it with automated requests, create
accounts in bulk, or use the site for anything unlawful.</p>

<h2>14. Emails</h2>
<p>We send emails you need — receipts, renewal reminders, confirmations, replies about your pitch or verification. The
newsletter is separate: you only get it if you sign up and confirm, and every issue has an unsubscribe link.</p>

<h2>15. Other services and links</h2>
<p>Some features rely on other companies: payments through Fonepay, videos through YouTube, and links to other
websites. Their own terms apply to their services, and we aren't responsible for websites we link to.</p>

<h2>16. Suspending or closing accounts</h2>
<p>You can ask us to close your account at any time. We may suspend or close an account that breaks these terms, is used
fraudulently, or puts others at risk. If we close an account for reasons other than a breach of these terms, we refund
the unused part of any paid subscription.</p>

<h2>17. Availability and changes to the site</h2>
<p>We work to keep {name} available and accurate, but the site may sometimes be unavailable for maintenance or reasons
outside our control, and we may change or stop features.</p>

<h2>18. Our responsibility</h2>
<p>We provide the site with reasonable care and skill. As far as the law allows, we are not responsible for losses that
come from relying on content as medical or professional advice, or for indirect losses; and our total responsibility to
you for any claim is limited to the amount you paid us in the 12 months before it. Nothing in these terms limits rights
you have under the law that can't be limited.</p>

<h2>19. Changes to these terms, and the law</h2>
<p>We may update these terms; the date at the top shows the latest version, and we'll tell account holders by email
about important changes. These terms are governed by the laws of Nepal, and the courts of Nepal deal with any
dispute.</p>

<h2>20. Contact</h2>
<p>{who}. Email: {contact}.</p>
'''

    privacy = f'''
<p>This policy explains what personal information {business} ("we") collects when you use {name}, why, who we share it
with, how long we keep it, and the choices you have. Questions or requests: {contact}.</p>

<h2>1. What we collect, and when</h2>
<ul>
<li><strong>When you just read:</strong> which pages and articles are viewed and when, linked to a random session
identifier (or your account if you're signed in) — so we can count readership, apply the free-article allowance, and
show related and popular stories. We don't store your IP address in these records.</li>
<li><strong>Your account:</strong> name, email address and password (stored scrambled, never in plain text), your
language choice, and whether you've confirmed your email.</li>
<li><strong>Author verification and author profiles:</strong> if you ask to be verified — affiliation, department, ORCID,
research interests, publications, profile links and your CV. If you're credited on articles, your author profile (name,
affiliation, bio, photo, links) is public.</li>
<li><strong>Personalisation:</strong> sections and topics you follow, articles you save, and gift links you create — used
for your reading list and "For you" recommendations.</li>
<li><strong>Comments:</strong> your comment, the name and email you give, the time, and your IP address (kept with the
comment to deal with spam and abuse). The comment and name are public; your email is not.</li>
<li><strong>Story pitches:</strong> your pitch and draft, your name and contact details, and the editors' feedback.</li>
<li><strong>Newsletter:</strong> your email address and when you subscribed and confirmed.</li>
<li><strong>Payments:</strong> what you bought, the price, VAT, total, receipt number and Fonepay's payment reference.
Payment itself happens with Fonepay and your bank — we never receive your bank login or card details.</li>
<li><strong>Training:</strong> the courses you enrol in and your payment status.</li>
<li><strong>Organization access:</strong> that you joined your organization's subscription, and when.</li>
<li><strong>Security:</strong> failed and successful sign-in attempts, with the IP address and browser, to stop password
guessing and protect accounts.</li>
<li><strong>When you contact us:</strong> whatever you choose to tell us.</li>
</ul>

<h2>2. How we use it</h2>
<ul>
<li>to run your account and give you what you signed up or paid for;</li>
<li>to send receipts, renewal reminders, confirmations and replies about your pitch or verification;</li>
<li>to send the newsletter, if you asked for it;</li>
<li>to personalise recommendations and remember your preferences;</li>
<li>to understand which stories readers find useful and improve the site;</li>
<li>to count how often advertisements are shown and clicked (in total — not per person);</li>
<li>to keep the site and your account secure, and to prevent spam, fraud and abuse;</li>
<li>to keep financial records and meet our legal obligations.</li>
</ul>
<p>We do not sell your personal information, and we don't use it for advertising by other companies.</p>

<h2>3. Who we share it with</h2>
<ul>
<li><strong>Service providers</strong> that run parts of the site for us, only for that purpose: Fonepay (payments), our
email provider (delivering emails), our hosting provider, Google Analytics (usage statistics), Google Fonts (typefaces),
and Cloudflare Turnstile (checking that the pitch form isn't used by robots).</li>
<li><strong>YouTube</strong>, when you watch a video on {name}. We use YouTube's privacy-enhanced mode; YouTube's own
privacy policy applies once you press play.</li>
<li><strong>Your organization</strong>, if you read through its subscription — it may be told that you joined.</li>
<li><strong>The public</strong> sees what you choose to publish: your comments and the name on them, and author profiles
of people credited on articles.</li>
<li><strong>Authorities</strong>, when the law requires it, or to protect people from harm.</li>
</ul>

<h2>4. Cookies</h2>
<ul>
<li><strong>Essential:</strong> keeping you signed in, remembering your language, protecting forms against forgery, and
counting free articles. The site doesn't work properly without these.</li>
<li><strong>Analytics:</strong> Google Analytics cookies, to measure how the site is used.</li>
</ul>
<p>You can block or delete cookies in your browser; if you block essential cookies you won't be able to sign in.</p>

<h2>5. How long we keep it</h2>
<ul>
<li>Account, profile and preferences: while you have an account.</li>
<li>Reading and advertising statistics: about {retention_days} days, then deleted automatically.</li>
<li>Comments and published articles: while they're on the site.</li>
<li>Pitches: while useful for the editorial process, and for a published story as long as the article is up.</li>
<li>Payment and receipt records: as long as tax and accounting law requires, even after an account is closed.</li>
<li>Sign-in attempt records: for a limited time for security.</li>
<li>Newsletter: until you unsubscribe.</li>
</ul>

<h2>6. Keeping it safe</h2>
<p>We use encrypted connections, scrambled passwords, limits on repeated sign-in attempts, and restrict staff access to
what each role needs. CVs and other private files are only available to you and to the editors who need them. No system
is perfectly secure; if something goes wrong that affects you, we'll tell you.</p>

<h2>7. Your choices and rights</h2>
<p>You can update your profile at any time, unfollow topics, delete saved articles, and unsubscribe from the newsletter
using the link in every issue. You can ask us to give you a copy of your information, correct it, or delete it — write
to {contact}. We'll reply within 30 days. Some records (such as receipts) we must keep for legal reasons.</p>

<h2>8. Children</h2>
<p>{name} is written for adults and young people interested in health. We don't knowingly collect information from
children under 13; if you think a child has given us personal information, contact us and we'll delete it.</p>

<h2>9. Changes</h2>
<p>We'll update this page if anything changes; the date at the top shows the latest version, and we'll email account
holders about important changes.</p>

<h2>10. Contact</h2>
<p>{who}. Email: {contact}.</p>
'''

    refunds = f'''
<p>This policy explains how to cancel or stop anything on {name} — paid or free — and when you can get your money back.
To ask for a refund or cancellation, email {contact} with your <strong>receipt number</strong> if you have one (for
example {prefix}000123 — it's on your receipt email and your Billing page).</p>

<h2>1. Free things you can stop at any time</h2>
<ul>
<li><strong>Newsletter:</strong> use the unsubscribe link in any issue — it works straight away.</li>
<li><strong>Comment reply emails:</strong> use the link in the email to stop them.</li>
<li><strong>Topics and sections you follow, saved articles:</strong> remove them from your reading list or profile.</li>
<li><strong>Your account:</strong> email us and we'll close it. Receipts we must keep for tax reasons are kept; everything
else is deleted or anonymised. Any paid subscription ends with the account (see section 7).</li>
</ul>

<h2>2. Subscriptions</h2>
<ul>
<li>Subscriptions never renew automatically, so there is nothing to cancel — yours simply ends on its last day.</li>
<li>You can get a <strong>full refund if you ask within 7 days of paying</strong>. After that, a subscription runs until
the end of the period you paid for and isn't refunded part-way.</li>
<li>A renewal you bought early, which hasn't started yet, can be refunded in full at any time before it starts.</li>
</ul>

<h2>3. Special articles</h2>
<p>A special article is unlocked as soon as you pay, so it isn't refundable — except when something went wrong (section
6).</p>

<h2>4. Training courses</h2>
<ul>
<li><strong>If you cancel:</strong> full refund if you ask at least <strong>7 days before the course starts</strong>. For
a course you can start at any time: within 7 days of enrolling, as long as you haven't started it.</li>
<li><strong>Can't make it?</strong> Instead of a refund, you can ask to move to a later run of the same course, or to
pass your place to a colleague, up to the day before it starts.</li>
<li><strong>If we cancel</strong> a course, or move it and the new date doesn't suit you, you get a full refund.</li>
<li>Not attending without telling us, or leaving part-way, isn't refunded.</li>
</ul>

<h2>5. Organizations</h2>
<p>Refunds and cancellations of institutional subscriptions follow the agreement with your organization. If you read
through your organization, your access ends when its subscription ends or when you no longer use its email address.</p>

<h2>6. When something went wrong</h2>
<p>If you were charged twice, paid for something you already had, paid but didn't get access, or a technical problem on
our side stopped you using what you paid for, tell us and we'll put it right or refund the payment in full — whatever
the time limits above say.</p>

<h2>7. If we close an account</h2>
<p>If we close your account for breaking our <a href="/terms/">Terms of use</a>, paid access isn't refunded. If we close
it for any other reason, or stop a service you've paid for, we refund the unused part.</p>

<h2>8. How refunds are paid</h2>
<ul>
<li>Refunds are for the <strong>full amount you paid, including VAT</strong>, and go back the way you paid — normally
within 7 working days of our approving them, though your bank may take a few more days.</li>
<li>You get a <strong>credit note</strong> by email, and the access that came with the payment ends.</li>
<li>Please contact us before asking your bank to reverse a payment — it's usually quicker, and a reversed payment ends
the access it paid for.</li>
</ul>

<h2>9. Changes</h2>
<p>We may update this policy; the version on this page when you paid applies to that payment.</p>
'''
    return {
        'terms': ('Terms of use', terms),
        'privacy': ('Privacy policy', privacy),
        'refund-policy': ('Refunds & cancellations', refunds),
    }


def _tidy(html: str) -> str:
    """One line per paragraph / list item, as the editor would save it."""
    html = re.sub(r'\s+', ' ', html).strip()
    return re.sub(r'(</(?:p|h2|ul|li)>|<ul>)\s*', r'\1\n', html).strip()


def update_untouched_drafts(apps, schema_editor):
    SitePage = apps.get_model('pages', 'SitePage')
    for slug, (title, body) in _drafts().items():
        body = _tidy(body)
        page = SitePage.objects.filter(slug=slug).first()
        if page is None:
            SitePage.objects.create(slug=slug, title=title, title_en=title, body=body, body_en=body, is_published=False)
        elif not page.is_published and page.updated_by_id is None:
            page.title = page.title_en = title
            page.body = page.body_en = body
            page.save(update_fields=['title', 'title_en', 'body', 'body_en'])


class Migration(migrations.Migration):

    dependencies = [
        ('pages', '0002_seed_policy_drafts'),
    ]

    operations = [
        migrations.RunPython(update_untouched_drafts, migrations.RunPython.noop),
    ]
