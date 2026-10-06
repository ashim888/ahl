import datetime
import json
import re

from django import forms
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import slugify
from django_ckeditor_5.widgets import CKEditor5Widget

from sections.models import Section
from users.models import User

from . import bylines as byline_utils
from .models import Article, ArticleCorrection, ArticleNote, Author, Keyword, keyword_slug
from .sanitize import sanitize_editorial_html


class TagifyKeywordsField(forms.CharField):
    """Backs a Tagify-enhanced text input (see article_form.html) — Tagify
    serializes its chips as a JSON array of {"value": "..."} objects on the
    underlying <input>, which this parses into a deduplicated list of
    Keyword instances, creating any that don't already exist. Falls back to
    a plain comma-split if the value isn't valid JSON (Tagify progressively
    enhances the input, so this also has to work with JS disabled).

    Dedup is by *slug*, not the raw typed name — "Diabetes" and "diabetes"
    fold into the same Keyword row rather than creating a near-duplicate;
    see Keyword's docstring in articles/models.py.
    """

    widget = forms.TextInput

    def to_python(self, value):
        if not value:
            return []
        try:
            parsed = json.loads(value)
            raw_names = [item['value'] for item in parsed if isinstance(item, dict) and item.get('value')]
        except (json.JSONDecodeError, TypeError, KeyError):
            raw_names = value.split(',')

        seen_slugs = set()
        keywords = []
        for raw_name in raw_names:
            name = raw_name.strip()
            slug = keyword_slug(name)
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            keyword, _created = Keyword.objects.get_or_create(slug=slug, defaults={'name': name})
            keywords.append(keyword)
        return keywords


class TagifyRelatedArticlesField(forms.CharField):
    """Backs the Tagify-enhanced "Related articles" input (article_form.html)
    — Tagify serializes its chips as a JSON array of {"value": title,
    "id": pk} objects. Unlike TagifyKeywordsField this never creates
    anything: only existing, published articles can be picked, and the
    article being edited is dropped (ArticleForm.clean_related_articles).
    With JS off it accepts a comma-separated list of article pks.
    """

    widget = forms.TextInput

    def to_python(self, value):
        if not value:
            return []
        try:
            parsed = json.loads(value)
            raw_ids = [item.get('id') for item in parsed if isinstance(item, dict)]
        except (json.JSONDecodeError, TypeError, AttributeError):
            raw_ids = value.split(',')
        ids = []
        for raw_id in raw_ids:
            try:
                pk = int(raw_id)
            except (TypeError, ValueError):
                continue
            if pk not in ids:
                ids.append(pk)
        found = Article.objects.filter(pk__in=ids, status=Article.Status.PUBLISHED).in_bulk()
        return [found[pk] for pk in ids if pk in found]


def edit_token_for(article) -> str:
    """The version marker the editor carries in its hidden edit_token field."""
    return f'{article.updated_at.timestamp():.6f}' if article.updated_at else ''


class ArticleForm(forms.ModelForm):
    """Front-end editorial CRUD form. Authors (ArticleAuthor byline rows,
    with order and the corresponding-author flag) come in through the hidden
    `bylines` field, edited by the Authors box in the form's sidebar — see
    articles/bylines.py.

    No `status` field on purpose — status is set procedurally by
    ArticleFormMixin.form_valid() based on which submit button (Save as
    Draft / Save & Publish) was pressed, not a dropdown that could disagree
    with it. Archiving an article stays a Django-admin-only action.
    """

    # Not a model field — Article.keyword_tags is a real M2M, but Tagify
    # needs a plain text input to progressively enhance (see
    # TagifyKeywordsField's docstring) rather than Django's default
    # <select multiple>. Declared explicitly instead of listed in Meta.fields.
    keywords = TagifyKeywordsField(
        required=False, label='Keywords',
        help_text='Press enter after each one. Existing keywords are suggested as you type.',
    )
    # Same reason as `keywords` above — Article.related_articles is a real
    # M2M, but the input is a Tagify-enhanced text field, so it's declared
    # here and saved by hand in save() rather than listed in Meta.fields.
    related_articles = TagifyRelatedArticlesField(
        required=False, label='Related articles',
        help_text='Hand-picked "Related reading" for this article. Leave empty to let the site pick '
                  'the most similar articles automatically (see suggestions below).',
    )

    # Not a model field: the go-live time for the Schedule button (stored in
    # Article.published_at with status Scheduled — see ArticleFormMixin).
    # A datetime-local input is read in the site's time zone (TIME_ZONE).
    schedule_at = forms.DateTimeField(
        required=False, label='Publish at',
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
    )

    # Breaking news: how long the site-wide banner should run. "" leaves
    # the current setting alone, "off" ends it early (see ArticleFormMixin).
    BREAKING_CHOICES = [
        ('', '— No change —'), ('1', 'Breaking for 1 hour'), ('3', 'Breaking for 3 hours'), ('6', 'Breaking for 6 hours'),
        ('12', 'Breaking for 12 hours'), ('24', 'Breaking for 24 hours'), ('off', 'Stop breaking-news banner'),
    ]
    breaking_hours = forms.ChoiceField(choices=BREAKING_CHOICES, required=False, label='Breaking news')

    # Which saved version the editor opened (Article.updated_at, as a
    # timestamp). If someone else saves in the meantime, ArticleFormMixin
    # refuses the save instead of silently overwriting their changes.
    edit_token = forms.CharField(required=False, widget=forms.HiddenInput)

    # The Authors box (see articles/bylines.py): the byline as JSON. Absent
    # from the POST (not just empty) means "leave the bylines alone".
    bylines = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Article
        # No date fields here on purpose — created_at covers "when was this
        # made" and publication_date is stamped automatically by Article.save()
        # the moment status becomes Published (see articles/models.py).
        fields = [
            'title', 'slug', 'article_type', 'access_type', 'price', 'is_pinned', 'homepage_section',
            'abstract', 'issue', 'section', 'volume', 'page_numbers', 'doi',
            'video_url', 'html_content', 'references', 'featured_image', 'featured_image_alt', 'featured_image_caption',
            'featured_image_credit', 'pdf_file', 'assigned_to', 'seo_title', 'seo_description', 'social_image',
        ]
        widgets = {
            'abstract': forms.Textarea(attrs={'rows': 5}),
            # 'articles' config adds sourceEditing so a technical editor can
            # still drop into raw HTML (e.g. an embedded chart) — see the
            # CKEDITOR_5_CONFIGS comment in settings.py. Citations are typed
            # as plain [1], [2] placeholders (articles/citations.py), not
            # hand-written <sup><a href="#ref-1"> markup.
            'html_content': CKEditor5Widget(config_name='articles'),
            'references': forms.Textarea(attrs={'rows': 6}),
        }
        # Editor-facing wording — the model help_texts are written for
        # developers (they point at code), these are for the newsroom.
        labels = {
            'abstract': 'Summary',
            'is_pinned': 'Pin to top',
            'homepage_section': 'Homepage spot',
            'featured_image': 'Featured image',
            'pdf_file': 'PDF version',
            'slug': 'URL slug',
            'doi': 'DOI',
            'assigned_to': 'Assigned editor',
        }
        help_texts = {
            'title': '',
            'abstract': 'One or two sentences (about 120–220 characters) shown under the headline and on article cards. '
                        'Use “Suggest one-liners” to pick the strongest lines from your text, then edit.',
            'video_url': 'Optional. A YouTube link (watch, youtu.be, Shorts or live). The player appears at the top of '
                         'the story; on a free story its thumbnail is used when there is no featured image. For a '
                         'subscriber-only video, upload it to YouTube as Unlisted and add a featured image — '
                         'anyone with a public link can watch it on YouTube for free.',
            'section': 'Where the story appears in the site menu.',
            'homepage_section': 'Put this story in a specific homepage spot, or leave on Auto.',
            'is_pinned': 'Keep this story at the top of lists and the homepage.',
            'issue': 'Optional. Add the story to an ongoing coverage series.',
            'access_type': 'Who can read the full text.',
            'slug': 'Leave empty to create it from the headline.',
            'pdf_file': 'Optional. Readers can download it from the article page.',
            'references': 'One source per line. Cite them in the text as [1], [2], …',
            'assigned_to': 'Who reviews this story. They get an email when it is sent to them for review.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['homepage_section'].choices = [('', "Auto (don't feature)")] + list(Article.HomepageSection.choices)
        self.fields['section'].required = False
        self.fields['issue'].empty_label = '— No issue —'
        self.fields['assigned_to'].queryset = User.objects.filter(
            is_active=True, role__in=User.EDITORIAL_ROLES,
        ).order_by('first_name', 'last_name')
        self.fields['assigned_to'].empty_label = '— Unassigned —'
        self.fields['assigned_to'].label_from_instance = lambda user: user.get_full_name() or user.email
        if self.instance.pk and self.instance.updated_at:
            self.fields['edit_token'].initial = edit_token_for(self.instance)
        self.fields['bylines'].initial = byline_utils.initial_json(self.instance)
        self.created_authors = {}
        if self.instance.pk and self.instance.status == Article.Status.SCHEDULED and self.instance.published_at:
            self.fields['schedule_at'].initial = timezone.localtime(self.instance.published_at)
        # Grouped <optgroup> choices, not a plain flat list — visually
        # matches the two-level hierarchy an editor is actually picking
        # from. Overriding .choices on a ModelChoiceField only changes what
        # renders; validation still resolves the submitted pk against
        # self.queryset (Django's ModelChoiceField.clean() doesn't consult
        # .choices at all), so this is safe.
        # Link-override sections (Training, Issues — see Section.link_url_name)
        # are excluded: an article assigned there would never actually be
        # reachable, since that nav entry just redirects to the existing
        # feature's own page instead of rendering a section landing page.
        section_choices = [('', '— No section —')]
        top_sections = Section.objects.filter(
            parent__isnull=True, link_url_name='',
        ).order_by('order', 'name').prefetch_related('children')
        for top in top_sections:
            options = [(top.pk, f'{top.name} (general)')]
            options += [(child.pk, child.name) for child in top.children.order_by('order', 'name')]
            section_choices.append((top.name, options))
        self.fields['section'].choices = section_choices
        # Pre-fill Tagify's expected format for an existing article's
        # current keywords — a JSON array of {"value": "..."} objects, the
        # same shape TagifyKeywordsField.to_python() parses back out of the
        # submitted form. self.instance.pk guards against a brand-new,
        # unsaved instance, whose keyword_tags M2M can't be queried yet.
        if self.instance.pk:
            self.fields['keywords'].initial = json.dumps(
                [{'value': kw.name} for kw in self.instance.keyword_tags.all()],
            )
        if self.instance.pk:
            self.fields['related_articles'].initial = json.dumps(
                [{'value': a.title, 'id': a.pk} for a in self.instance.related_articles.all()],
            )
        # Blank is valid — Article.save() auto-generates slug + short_code
        # from the title when left empty (see articles/models.py). Django's
        # own unique-value validation on the ModelForm already rejects an
        # explicitly-typed slug that collides with another article's.
        self.fields['slug'].required = False

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('access_type') == Article.AccessType.PAY_PER_ARTICLE and not cleaned_data.get('price'):
            self.add_error('price', 'Set a price for pay-per-article articles.')
        if cleaned_data.get('article_type') == Article.ArticleType.VIDEO and not cleaned_data.get('video_url'):
            self.add_error('video_url', 'A video story needs its YouTube link.')
        return cleaned_data

    def clean_bylines(self):
        if self.add_prefix('bylines') not in self.data:
            return None
        return byline_utils.parse(self.cleaned_data.get('bylines'), self.instance)

    def clean_related_articles(self):
        related = self.cleaned_data.get('related_articles', [])
        return [a for a in related if a.pk != self.instance.pk]

    def clean_html_content(self):
        # See articles/sanitize.py — defense in depth on top of the
        # EDITORIAL_ROLES-only write access this field already relies on.
        return sanitize_editorial_html(self.cleaned_data.get('html_content'))

    def save(self, commit=True):
        # keyword_tags is a real M2M but keywords isn't a Meta.field (it's
        # the declared TagifyKeywordsField above), so Django's own automatic
        # save_m2m handling — which only knows about Meta.fields — never
        # sees it. Same commit=False/save_m2m() contract as a normal
        # ModelForm M2M field, just implemented by hand: callers that save
        # with commit=False (article_autosave, article_preview) must still
        # call form.save_m2m() themselves once the instance has a pk.
        # related_articles is the same kind of hand-saved M2M. Django's own
        # _save_m2m() is still called too, so any M2M later added to
        # Meta.fields isn't silently dropped by this override.
        instance = super().save(commit=False)
        keywords = self.cleaned_data.get('keywords', [])
        related = self.cleaned_data.get('related_articles', [])
        bylines = self.cleaned_data.get('bylines')

        def save_m2m():
            self._save_m2m()
            instance.keyword_tags.set(keywords)
            instance.related_articles.set(related)
            if bylines is not None:
                self.created_authors = byline_utils.save(instance, bylines)

        if commit:
            instance.save()
            save_m2m()
        else:
            self.save_m2m = save_m2m
        return instance


class LenientArticleForm(ArticleForm):
    """Same fields/validation rules as ArticleForm, but nothing is required —
    used only by the autosave-on-next-tab endpoint, which saves whatever's
    been filled in so far as a draft. The real "required" enforcement still
    happens in ArticleForm on the final Save as Draft / Save & Publish submit.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False

    def clean(self):
        # Skip ArticleForm.clean()'s price-required-for-pay-per-article check —
        # autosave fires on every tab click and must never block on an
        # incomplete draft (that enforcement belongs to the real submit only).
        return forms.ModelForm.clean(self)


class DraftArticleForm(LenientArticleForm):
    """Save draft: only a title is needed, so an editor can park a half-done
    story at any point. Everything else is checked at publish time
    (PublishArticleForm) — a draft is allowed to be incomplete.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['title'].required = True


IMG_TAG_RE = re.compile(r'<img\b[^>]*>', re.IGNORECASE)
ALT_RE = re.compile(r'\balt\s*=\s*("([^"]*)"|\'([^\']*)\')', re.IGNORECASE)


def images_missing_alt(html: str) -> int:
    """How many <img> in `html` have no (or an empty) alt text."""
    missing = 0
    for tag in IMG_TAG_RE.findall(html or ''):
        match = ALT_RE.search(tag)
        if not match or not (match.group(2) or match.group(3) or '').strip():
            missing += 1
    return missing


class PublishArticleForm(ArticleForm):
    """Publish / Update: ArticleForm's own rules, plus — the first time an
    article goes live — there must be something to read (body text or a PDF).
    """

    def clean(self):
        cleaned_data = super().clean()
        if self.instance.pk and self.instance.status == Article.Status.PUBLISHED:
            # Already live: don't block fixing a typo in an older article
            # that was published before this rule existed (e.g. abstract-only).
            return cleaned_data
        body = cleaned_data.get('html_content') or ''
        has_pdf = bool(cleaned_data.get('pdf_file') or self.instance.pdf_file)
        # A video story's video is its content; the text is optional.
        has_video = bool(cleaned_data.get('video_url'))
        if not strip_tags(body).strip() and '<img' not in body and not has_pdf and not has_video:
            self.add_error('html_content', 'Add the article text (or a video link, or attach a PDF) before publishing.')
        # Accessibility: every image needs a description for screen-reader users.
        missing = images_missing_alt(body)
        if missing:
            self.add_error('html_content', (
                f'{missing} image{"s" if missing > 1 else ""} in the text {"have" if missing > 1 else "has"} no description. '
                'Click the image, then the "Change image text alternative" button, and describe what it shows.'
            ))
        has_featured = bool(cleaned_data.get('featured_image') or (self.instance.pk and self.instance.featured_image))
        if has_featured and not (cleaned_data.get('featured_image_alt') or '').strip() and 'featured_image_alt' in self.fields:
            self.add_error('featured_image_alt', 'Describe the featured image for readers who can’t see it.')
        return cleaned_data


class ScheduleArticleForm(PublishArticleForm):
    """Schedule: everything Publish checks, plus a go-live time that's at
    least a minute away (anything sooner is just "Publish now")."""

    def clean_schedule_at(self):
        value = self.cleaned_data.get('schedule_at')
        if not value:
            raise forms.ValidationError('Pick the date and time it should go live.')
        if value <= timezone.now() + datetime.timedelta(minutes=1):
            raise forms.ValidationError('Pick a time in the future — or use Publish to publish now.')
        return value


class AuthorForm(forms.ModelForm):
    """Editorial create/edit of an Author byline profile — no login fields.
    Giving the author an account is a separate action (Create user account
    on /manage/authors/), so creating a byline never requires a password.
    """

    class Meta:
        model = Author
        fields = [
            'name', 'affiliation', 'department', 'email', 'bio', 'photo', 'orcid', 'research_interests',
            'website_url', 'linkedin_url', 'researchgate_url', 'is_active',
        ]
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 5}),
            'research_interests': forms.Textarea(attrs={'rows': 2}),
        }
        help_texts = {
            'name': 'As it should appear in bylines, e.g. "Dr. Sunita Rai".',
        }

    # Fields that fall back to the linked account's profile when left blank
    # (Author.display_*) — shown as greyed placeholders so an editor can see
    # what the public page will use.
    ACCOUNT_FALLBACK_FIELDS = [
        'affiliation', 'department', 'bio', 'orcid', 'research_interests', 'linkedin_url', 'researchgate_url',
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = self.instance.user if self.instance.pk and self.instance.user_id else None
        if user:
            for name in self.ACCOUNT_FALLBACK_FIELDS:
                value = getattr(user, name, None)
                if value:
                    self.fields[name].widget.attrs['placeholder'] = f'From account: {value}'[:200]

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if email and Author.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Another author already uses this email address.')
        return email


class ArticleCorrectionForm(forms.ModelForm):
    """Adding a correction/clarification/update note to a live article."""

    class Meta:
        model = ArticleCorrection
        fields = ['kind', 'note']
        widgets = {'note': forms.Textarea(attrs={'rows': 3, 'placeholder': 'e.g. An earlier version said the clinic opened in 2019. It opened in 2021.'})}


class ArticleNoteForm(forms.ModelForm):
    """Internal editorial note on an article — never shown to readers."""

    class Meta:
        model = ArticleNote
        fields = ['body']
