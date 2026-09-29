import datetime
import secrets
import string

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import Truncator, slugify
from django.utils.translation import gettext_lazy as _

from .validators import (
    article_image_extension_validator, article_pdf_extension_validator,
    validate_article_pdf_size, validate_document_content, validate_featured_image_size,
)

# Shared with articles/views.py HomeView, which caches under this key —
# defined here (not there) so Article.save() can invalidate it without
# models.py importing from views.py.
HOME_SECTIONS_CACHE_KEY = 'home:sections:v2'
# The current breaking-news article (or None) for the site-wide banner —
# see ajna_health_lens/context_processors.py; cleared on every Article.save().
BREAKING_CACHE_KEY = 'articles:breaking:v1'

# 5 lowercase-alphanumeric chars, e.g. "3f2a4" — short enough to be a usable
# permalink (/articles/3f2a4/, see articles/converters.py + urls.py), long
# enough that 36**5 (~60M) combinations make a collision on any one retry
# vanishingly unlikely, matching the retry-loop pattern Article.save() uses.
SHORT_CODE_ALPHABET = string.ascii_lowercase + string.digits
SHORT_CODE_LENGTH = 5


def generate_short_code():
    return ''.join(secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH))


class Keyword(models.Model):
    """A normalized tag, replacing what used to be a raw comma-separated
    string on Article.keywords (August 2026) — the free-text version let
    the same concept fragment into several different spellings ("Diabetes"/
    "diabetes"/"Type 2 Diabetes"), which made keyword search a fragile
    substring match on a joined blob instead of a real lookup. `slug` (not
    `name`) is the actual identity for dedup/lookup purposes — case and
    punctuation differences in `name` fold to the same slug via
    Article.keyword_tags's get_or_create in articles/forms.py, so an editor
    typing "Diabetes" when "diabetes" already exists reuses the same row
    rather than creating a near-duplicate.
    """

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Article(models.Model):
    """A published (or in-production) piece of content, created directly by
    an editor. (Previously also created by promoting an accepted academic
    Submission — that flow, and the submissions/peer_review apps it lived
    in, were removed once OJS took over real manuscript submission; see
    CLAUDE.md's SCOPE NOTE and ROADMAP.md.)
    """

    class ArticleType(models.TextChoices):
        ORIGINAL_RESEARCH = 'original_research', _('Original Research')
        REVIEW_ARTICLE = 'review_article', _('Review Article')
        CASE_REPORT = 'case_report', _('Case Report')
        SHORT_COMMUNICATION = 'short_communication', _('Short Communication')
        METHODOLOGY_PAPER = 'methodology_paper', _('Methodology Paper')
        EDITORIAL = 'editorial', _('Editorial')
        NEWS_COMMENTARY = 'news_commentary', _('News & Commentary')
        LETTER_TO_EDITOR = 'letter_to_editor', _('Letter to Editor')

    class AccessType(models.TextChoices):
        OPEN_ACCESS = 'open_access', _('Free')
        SUBSCRIPTION = 'subscription', _('Subscription')
        PAY_PER_ARTICLE = 'pay_per_article', _('Pay-per-article (special)')

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        IN_REVIEW = 'in_review', 'In review'
        READY = 'ready', 'Ready to publish'
        SCHEDULED = 'scheduled', 'Scheduled'
        PUBLISHED = 'published', 'Published'
        ARCHIVED = 'archived', 'Archived'

    class HomepageSection(models.TextChoices):
        HERO = 'hero', 'Hero (top story)'
        LATEST_NEWS = 'latest_news', 'Latest News'
        OPINION = 'opinion', 'Opinion & Editorial'
        RESEARCH = 'research', 'Research Highlights'

    title = models.CharField(max_length=500)
    slug = models.SlugField(
        max_length=500, unique=True, blank=True,
        help_text='Leave blank to generate from the title (plus a short unique code, e.g. "my-article-3f2a4").',
    )
    short_code = models.CharField(
        max_length=SHORT_CODE_LENGTH, unique=True, blank=True, editable=False,
        help_text='Auto-generated permalink code — also reachable at /articles/<code>/.',
    )
    abstract = models.TextField(
        blank=True,
        help_text='Optional standfirst/summary shown under the headline and in listings. Short news '
                  'pieces can leave it empty — listings then fall back to an excerpt of the body '
                  '(open-access articles only; see Article.summary).',
    )
    # Was a flat comma-separated CharField (pre-August 2026) — replaced with
    # a real M2M to Keyword so the same concept doesn't fragment into near-
    # duplicate spellings, and so keyword search/filter can do an exact tag
    # lookup instead of an icontains substring match on a joined string. See
    # Keyword's docstring above and articles/forms.py's TagifyKeywordsField.
    keyword_tags = models.ManyToManyField(Keyword, blank=True, related_name='articles')
    # Editor-curated "Related reading" — one-directional (A listing B doesn't
    # make B list A), since relevance often isn't mutual. When empty, the
    # article page falls back to text-similarity ranking instead
    # (articles/similarity.py) rather than a fixed rule like "same type".
    related_articles = models.ManyToManyField(
        'self', symmetrical=False, blank=True, related_name='related_from',
        help_text='Hand-picked related reading. Leave empty to let the site suggest articles by text similarity.',
    )
    article_type = models.CharField(max_length=30, choices=ArticleType.choices, default=ArticleType.NEWS_COMMENTARY)
    # A per-article editorial/business call, independent of article_type —
    # see ROADMAP.md Phase 7 "Business model (revised — three access tiers)".
    # No longer derived from article_type (that was a leftover academic-journal
    # assumption — a news article's monetization tier isn't implied by its category).
    access_type = models.CharField(
        max_length=20, choices=AccessType.choices, default=AccessType.OPEN_ACCESS,
        help_text='Free, subscriber-only, or a one-time-purchase "special" article.',
    )
    price = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text='One-time price, required only when access type is Pay-per-article.',
    )
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    is_pinned = models.BooleanField(
        default=False,
        help_text='Pin to the top of listings and the homepage, ahead of publication date. '
                   'If more than one article is pinned, the most recently published pinned one leads.',
    )
    homepage_section = models.CharField(
        max_length=20, choices=HomepageSection.choices, blank=True,
        help_text='Feature this article in a specific homepage section, regardless of its article '
                   'type. Leave blank to let that section auto-fill from recent articles of the '
                   'matching type instead — see articles/views.py HomeView.',
    )

    # Fully automatic, not editor-facing: created_at (below) already records
    # when the article was created, and publication_date is stamped by
    # save() the moment status becomes Published (see below) — no manual
    # submission/acceptance dates to track without an OJS integration.
    publication_date = models.DateField(null=True, blank=True)
    # The real go-live moment (date *and* time) — what listings sort by and
    # readers see. Set automatically on publish; for a Scheduled article
    # it's the future time articles.tasks.publish_due_articles will publish
    # it at. publication_date above is kept as its local calendar date,
    # since digests, sitemaps and citations only need the day.
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # Set only when an editor clicks "Update live article" — not by every
    # save (pinning, homepage placement and counters don't count as an
    # update a reader should be told about).
    last_updated_at = models.DateTimeField(null=True, blank=True)
    # Search & social overrides — optional; empty means use the headline,
    # summary and featured image (see ArticleDetailView's meta tags).
    seo_title = models.CharField(
        'Search headline', max_length=70, blank=True,
        help_text='Shown in Google results and browser tabs. Up to ~60 characters reads best.',
    )
    seo_description = models.CharField(
        'Search description', max_length=160, blank=True,
        help_text='The snippet under the headline in search results and share cards. ~150 characters.',
    )
    social_image = models.ImageField(
        'Share image', upload_to='articles/social/', null=True, blank=True,
        validators=[article_image_extension_validator, validate_featured_image_size],
        help_text='Image for Facebook/X/WhatsApp previews (1200×630 works best). Falls back to the featured image.',
    )
    # Breaking news: while now < breaking_until (and the article is live),
    # a site-wide banner links to it. Expires on its own.
    breaking_until = models.DateTimeField(null=True, blank=True, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_articles',
        help_text='The editor responsible for reviewing this story.',
    )

    doi = models.CharField(max_length=100, unique=True, null=True, blank=True)
    pdf_file = models.FileField(
        upload_to='articles/%Y/%m/', null=True, blank=True,
        validators=[article_pdf_extension_validator, validate_article_pdf_size, validate_document_content],
        help_text='PDF only, up to 100 MB.',
    )
    featured_image = models.ImageField(
        upload_to='articles/images/', null=True, blank=True,
        validators=[article_image_extension_validator, validate_featured_image_size],
        help_text='Hero/thumbnail image shown on the homepage, listing cards, and related-article links. '
                   'JPG or PNG, up to 10 MB.',
    )
    featured_image_alt = models.CharField(
        'Image description (alt text)', max_length=250, blank=True,
        help_text='What the image shows, for screen readers and search engines. Falls back to the headline.',
    )
    featured_image_caption = models.CharField(
        'Caption', max_length=300, blank=True, help_text='Shown under the image on the article page.',
    )
    featured_image_credit = models.CharField(
        'Credit', max_length=150, blank=True, help_text='Photographer or source, e.g. "Ram Shrestha / Ajna Health Lens".',
    )
    html_content = models.TextField(
        null=True, blank=True,
        help_text='Full-text body HTML, rendered as-is (trusted — admin/editor-authored only, '
                   'never end-user input). Shown only for open-access articles; subscription '
                   'articles stay gated behind the Phase 6 paywall regardless of this field.',
    )
    references = models.TextField(
        null=True, blank=True,
        help_text='Bibliography, one formatted citation per line. Rendered as a numbered list.',
    )

    authors = models.ManyToManyField('Author', through='ArticleAuthor', related_name='articles')
    issue = models.ForeignKey(
        'issues.Issue', on_delete=models.SET_NULL, null=True, blank=True, related_name='articles',
        help_text='Optional story trail / issue this article belongs to.',
    )
    section = models.ForeignKey(
        'sections.Section', on_delete=models.SET_NULL, null=True, blank=True, related_name='articles',
        help_text='Optional subject-taxonomy placement (see the sections app) — independent of '
                   'article_type (format) and keyword_tags (free tags). Drives the public '
                   'primary-nav landing pages, not the homepage curation slots above.',
    )

    volume = models.CharField(max_length=10, null=True, blank=True)
    page_numbers = models.CharField(max_length=20, null=True, blank=True)
    citation_count = models.IntegerField(default=0)
    download_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def summary(self) -> str:
        """Listing/meta-description text: the abstract when there is one,
        otherwise (abstract is optional for news) the opening words of the
        body — but only for open-access articles, so a card or feed never
        leaks the start of paywalled text. Empty string when neither applies.
        """
        if self.abstract and self.abstract.strip():
            return self.abstract.strip()
        if self.access_type == self.AccessType.OPEN_ACCESS and self.html_content:
            return Truncator(' '.join(strip_tags(self.html_content).split())).words(40)
        return ''

    @property
    def estimated_read_minutes(self):
        """Word count / 200wpm. Only counts html_content for open-access
        articles — a rough public-facing estimate, not viewer-aware (the
        actual paywall gate for subscription/pay-per-article tiers lives in
        billing.access.article_is_accessible, not here).
        """
        text = self.abstract or ''
        if self.access_type == self.AccessType.OPEN_ACCESS and self.html_content:
            text += ' ' + self.html_content
        return max(1, round(len(text.split()) / 200))

    class Meta:
        # status is filtered on in nearly every public-facing query in this
        # app (HomeView, ArticleListView, SearchView, ArticleDetailView,
        # both feeds, both sitemaps, IssueDetailView's article listing) —
        # without an index, that's a full-table-scan on the busiest table in
        # the schema for nearly every page view.
        indexes = [models.Index(fields=['status'])]
        # Putting something in front of readers (publish, schedule, update or
        # unpublish a live article, add a public correction) is limited to
        # "publishers": Editor-in-Chief/Admin always, other editors only if
        # granted this on the Staff screen. See User.can_publish.
        permissions = [('publish_article', 'Can publish, schedule and change live articles')]

    def save(self, *args, **kwargs):
        # short_code first — a blank slug is built from it below, so it must
        # already exist by the time that runs. Applies regardless of how the
        # article was created (the editorial form, the pitches accept flow,
        # seed_demo_data, Django admin, ...) since every path ends up here.
        if not self.short_code:
            code = generate_short_code()
            while Article.objects.filter(short_code=code).exists():
                code = generate_short_code()
            self.short_code = code
        # Auto-slug from the title when an editor leaves it blank
        # (ArticleForm makes it optional) — the short_code suffix means two
        # articles with the same title can never collide, so there's no
        # uniqueness retry loop needed here the way _unique_article_slug
        # needs one elsewhere for slugs without a code suffix.
        if not self.slug:
            base = slugify(self.title) or 'article'
            self.slug = f'{base}-{self.short_code}'
        # published_at/publication_date are automatic — stamped the moment
        # status becomes Published and never re-stamped by a later edit. A
        # time still in the future (left over from a schedule that was
        # overridden with "Publish now") is pulled back to now, so a live
        # article never claims to have been published later than it was.
        if self.status == self.Status.PUBLISHED:
            now = timezone.now()
            if self.published_at is None and self.publication_date:
                # A date set directly (seed data, back-dated imports) wins:
                # start of that local day.
                self.published_at = timezone.make_aware(
                    datetime.datetime.combine(self.publication_date, datetime.time.min),
                )
            if self.published_at is None or self.published_at > now:
                self.published_at = now
            self.publication_date = timezone.localdate(self.published_at)
        super().save(*args, **kwargs)
        # Cheap and unconditional rather than trying to detect exactly which
        # field changes matter (status, homepage_section, is_pinned, or just
        # an edit to an already-featured article's title/image) — a save is
        # rare enough that clearing on every one isn't worth the complexity
        # of tracking which changes actually affect the homepage. See
        # articles/views.py HomeView.CACHE_KEY.
        cache.delete(HOME_SECTIONS_CACHE_KEY)
        cache.delete(BREAKING_CACHE_KEY)

    def __str__(self):
        return self.title

    @property
    def is_breaking(self) -> bool:
        return bool(
            self.status == self.Status.PUBLISHED and self.breaking_until and self.breaking_until > timezone.now()
        )

    def get_absolute_url(self):
        # Required by django_comments_xtd (comment confirmation/moderation
        # redirects and email templates resolve content_object.get_absolute_url()
        # directly) — see ARCHITECTURE.md's comments section.
        return reverse('articles:article_detail', args=[self.slug])


class Author(models.Model):
    """A public byline profile — the person credited on articles. Needs no
    site account: editors create one for any contributor from
    /manage/authors/. `user` is set only when the author also gets (or
    already has) a login — see users/views.py author_create_account.

    Profile fields here are what the byline and the public author page show.
    For an author linked to an account, a blank field falls back to the
    account's own profile (the display_* properties), so an author who keeps
    their account profile up to date doesn't need it copied here too.
    """

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    email = models.EmailField(
        blank=True, help_text='Contact address for editors. Never shown publicly. Used as the login if an account is created.',
    )
    affiliation = models.CharField(max_length=255, blank=True)
    department = models.CharField(max_length=255, blank=True)
    bio = models.TextField(blank=True)
    photo = models.ImageField(
        upload_to='authors/', null=True, blank=True,
        validators=[article_image_extension_validator, validate_featured_image_size],
    )
    orcid = models.CharField('ORCID', max_length=19, blank=True, help_text='e.g. 0000-0002-1825-0097')
    research_interests = models.TextField(blank=True)
    website_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    researchgate_url = models.URLField(blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='author_profile',
        help_text='Linked login account, if any.',
    )
    is_active = models.BooleanField(
        default=True, help_text='Inactive authors are hidden from the byline picker and have no public page.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or 'author'
            if base.isdigit():  # /authors/<int>/ is the legacy user-id redirect
                base = f'author-{base}'
            slug, n = base, 2
            while Author.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f'{base}-{n}', n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('articles:author_detail', args=[self.slug])

    def _fallback(self, field: str):
        value = getattr(self, field)
        if value:
            return value
        return (getattr(self.user, field, None) or '') if self.user_id else ''

    @property
    def display_affiliation(self) -> str:
        return self._fallback('affiliation')

    @property
    def display_department(self) -> str:
        return self._fallback('department')

    @property
    def display_bio(self) -> str:
        return self._fallback('bio')

    @property
    def display_orcid(self) -> str:
        return self._fallback('orcid')

    @property
    def display_research_interests(self) -> str:
        return self._fallback('research_interests')

    @property
    def display_linkedin_url(self) -> str:
        return self._fallback('linkedin_url')

    @property
    def display_researchgate_url(self) -> str:
        return self._fallback('researchgate_url')

    @property
    def display_photo(self):
        """The author's photo, else the linked account's, else None."""
        if self.photo:
            return self.photo
        if self.user_id and self.user.photo:
            return self.user.photo
        return None

    @property
    def initial(self) -> str:
        words = [w for w in self.name.split() if w.rstrip('.').lower() not in {'dr', 'prof', 'mr', 'mrs', 'ms'}]
        return (words[0][0] if words else self.name[:1]).upper()

    @classmethod
    def for_user(cls, user) -> 'Author':
        """The account's author profile, created from its profile fields on
        first use (e.g. when a pitch from that account is accepted).
        """
        try:
            return user.author_profile
        except cls.DoesNotExist:
            return cls.objects.create(
                user=user, name=user.get_full_name() or user.email, email=user.email,
            )


class ArticleAuthor(models.Model):
    """One byline entry: an Author (see above — no site account needed) in
    a given position on an article.
    """

    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    # PROTECT: an author with bylines is deactivated, never deleted out
    # from under the articles that credit them.
    author = models.ForeignKey(Author, on_delete=models.PROTECT, related_name='bylines')
    order = models.IntegerField(default=0, help_text='Author ordering on the article byline.')
    is_corresponding = models.BooleanField(default=False)

    class Meta:
        ordering = ['order']
        unique_together = ('article', 'author')

    def __str__(self):
        return f'{self.author} on {self.article}'

    @property
    def display_name(self) -> str:
        return self.author.name

    @property
    def display_affiliation(self) -> str:
        return self.author.display_affiliation


class ArticleCorrection(models.Model):
    """A dated note appended to a published article — a correction of a
    factual error, a clarification, or an update with new information.
    Shown on the article page (and flagged under the headline) and in its
    NewsArticle structured data. Adding one also stamps the article's
    last_updated_at, since readers should see it changed.
    """

    class Kind(models.TextChoices):
        CORRECTION = 'correction', _('Correction')
        CLARIFICATION = 'clarification', _('Clarification')
        UPDATE = 'update', _('Update')

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='corrections')
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.CORRECTION)
    note = models.TextField(help_text='What changed and why, in a sentence or two. Shown to readers.')
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.get_kind_display()} on {self.article}'


class ArticleNote(models.Model):
    """Internal editorial discussion on an article ("check the 2021 figure
    with the ministry") — never shown to readers."""

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='notes')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'Note on {self.article} by {self.author}'


class ArticleRevision(models.Model):
    """A snapshot of an article's words at one save — who, when, what they
    did, and the title/summary/text/references as they stood afterwards.
    Recorded by ArticleFormMixin/article_autosave (see
    articles/revisions.py); the History page compares and restores them.
    """

    class Action(models.TextChoices):
        CREATED = 'created', 'Created'
        AUTOSAVED = 'autosaved', 'Autosaved'
        SAVED = 'saved', 'Saved draft'
        SUBMITTED = 'submitted', 'Sent for review'
        APPROVED = 'approved', 'Marked ready'
        SCHEDULED = 'scheduled', 'Scheduled'
        PUBLISHED = 'published', 'Published'
        UPDATED = 'updated', 'Updated live article'
        UNPUBLISHED = 'unpublished', 'Moved back to draft'
        RESTORED = 'restored', 'Restored an earlier version'

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='revisions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    action = models.CharField(max_length=20, choices=Action.choices)
    status = models.CharField(max_length=20, choices=Article.Status.choices)
    title = models.CharField(max_length=500)
    abstract = models.TextField(blank=True)
    html_content = models.TextField(blank=True)
    references = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return f'{self.get_action_display()} — {self.article} ({self.created_at:%Y-%m-%d %H:%M})'


class ArticleView(models.Model):
    """One page-view event — first-party, no third-party analytics vendor
    (August 2026 decision: buildable without an external account, unlike
    GA/Plausible/PostHog). Timestamped events, not just a running total on
    Article, so a real "trending this week" is possible, not just an
    all-time counter. See HomeView._build_sections (articles/views.py) for
    the trending query and ArticleDetailView for where these get recorded.
    """

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='page_views')
    session_key = models.CharField(
        max_length=40, blank=True,
        help_text='Django session key, used only to de-duplicate repeat views within a short window — no IP/fingerprinting.',
    )
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['article', 'viewed_at'])]

    def __str__(self):
        return f'View of {self.article} at {self.viewed_at}'


class Bookmark(models.Model):
    """A reader saving an article for later ("read later" — ROADMAP.md
    Phase 10 deferred list). Distinct from ArticleView above — that's an
    anonymous, session-keyed page-view event for the Trending widget;
    a Bookmark is an explicit, account-only save, shown back to the reader
    themselves on their reading list (/reading-list/) and profile page.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookmarks')
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='bookmarked_by')
    bookmarked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-bookmarked_at']
        unique_together = ('user', 'article')
        indexes = [models.Index(fields=['user', '-bookmarked_at'])]

    def __str__(self):
        return f'{self.user} saved {self.article}'


class KeywordFollow(models.Model):
    """A reader following a Keyword for the personalized feed (/for-you/)
    and weekly digest — ROADMAP.md Phase 10 Session 5, folded into the same
    feed/digest sections.SectionFollow already powers, not a second
    parallel system. Unlike Section (curated, editorially maintained),
    Keyword is coined ad hoc per-article by whichever editor is tagging it,
    so the Follow control itself is only ever shown (see
    articles/views.py:keyword_follow_toggle) on a keyword already used on
    more than one article — a keyword used once is structurally guaranteed
    to never surface a second article, so there's nothing meaningful to
    follow yet. That eligibility check happens at the view layer, not here,
    since a keyword can drop below the threshold later (e.g. an article
    unpublished) without needing to retroactively invalidate existing
    follows.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='keyword_follows')
    keyword = models.ForeignKey(Keyword, on_delete=models.CASCADE, related_name='followers')
    followed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-followed_at']
        unique_together = ('user', 'keyword')

    def __str__(self):
        return f'{self.user} follows {self.keyword}'


class KeywordEvent(models.Model):
    """One keyword-pill impression or click on an article page — first-party,
    same event-log pattern as ArticleView and ads.AdEvent. Powers the
    editorial Keyword Analytics page (admin_custom, /editorial/keywords/):
    clicks ÷ impressions is the "how much do readers want to click this
    keyword" signal, and the timestamps drive its weekday × hour heatmap.

    An impression is recorded once per keyword per *counted* article view
    (see articles/views.py:_record_keyword_impressions) — not once per pill,
    even though article_detail.html shows each keyword twice (header and
    footer); `placement` on a click says which of the two was used. Like
    ArticleView, no IP/user is stored — session_key exists only to
    de-duplicate repeat clicks within a short window.
    """

    class EventType(models.TextChoices):
        IMPRESSION = 'impression', 'Impression'
        CLICK = 'click', 'Click'

    class Placement(models.TextChoices):
        HEADER = 'header', 'Article header'
        FOOTER = 'footer', 'Article footer'

    keyword = models.ForeignKey(Keyword, on_delete=models.CASCADE, related_name='events')
    article = models.ForeignKey(
        Article, on_delete=models.SET_NULL, null=True, blank=True, related_name='keyword_events',
        help_text='The article page the keyword was shown/clicked on.',
    )
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    placement = models.CharField(max_length=20, choices=Placement.choices, blank=True)
    session_key = models.CharField(max_length=40, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['keyword', 'event_type', 'occurred_at']),
            models.Index(fields=['event_type', 'occurred_at']),
        ]

    def __str__(self):
        return f'{self.get_event_type_display()} on {self.keyword} at {self.occurred_at}'
