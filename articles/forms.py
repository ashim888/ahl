import json

from django import forms
from django.forms import inlineformset_factory
from django.utils.text import slugify
from django_ckeditor_5.widgets import CKEditor5Widget

from users.models import User

from .models import Article, ArticleAuthor, Keyword


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
            slug = slugify(name)
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            keyword, _created = Keyword.objects.get_or_create(slug=slug, defaults={'name': name})
            keywords.append(keyword)
        return keywords


class ArticleForm(forms.ModelForm):
    """Front-end editorial CRUD form. Authors (the Article<->User through
    model, with ordering/corresponding-author flags) are edited separately
    via ArticleAuthorFormSet below (see manage_article_authors) — a plain
    multi-select here can't represent that ordering cleanly, so this form
    sticks to the article's own fields.

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

    class Meta:
        model = Article
        # No date fields here on purpose — created_at covers "when was this
        # made" and publication_date is stamped automatically by Article.save()
        # the moment status becomes Published (see articles/models.py).
        fields = [
            'title', 'slug', 'article_type', 'access_type', 'price', 'is_pinned', 'homepage_section',
            'abstract', 'issue', 'volume', 'page_numbers', 'doi',
            'html_content', 'references', 'featured_image', 'pdf_file',
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['homepage_section'].choices = [('', "Auto (don't feature)")] + list(Article.HomepageSection.choices)
        # Pre-fill Tagify's expected format for an existing article's
        # current keywords — a JSON array of {"value": "..."} objects, the
        # same shape TagifyKeywordsField.to_python() parses back out of the
        # submitted form. self.instance.pk guards against a brand-new,
        # unsaved instance, whose keyword_tags M2M can't be queried yet.
        if self.instance.pk:
            self.fields['keywords'].initial = json.dumps(
                [{'value': kw.name} for kw in self.instance.keyword_tags.all()],
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
        return cleaned_data

    def save(self, commit=True):
        # keyword_tags is a real M2M but keywords isn't a Meta.field (it's
        # the declared TagifyKeywordsField above), so Django's own automatic
        # save_m2m handling — which only knows about Meta.fields — never
        # sees it. Same commit=False/save_m2m() contract as a normal
        # ModelForm M2M field, just implemented by hand: callers that save
        # with commit=False (article_autosave, article_preview) must still
        # call form.save_m2m() themselves once the instance has a pk.
        instance = super().save(commit=False)
        keywords = self.cleaned_data.get('keywords', [])

        def save_keywords():
            instance.keyword_tags.set(keywords)

        if commit:
            instance.save()
            save_keywords()
        else:
            self.save_m2m = save_keywords
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


class ArticleAuthorForm(forms.ModelForm):
    class Meta:
        model = ArticleAuthor
        fields = ['user', 'order', 'is_corresponding']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = User.objects.order_by('first_name', 'last_name')


# Byline editor for an article — mirrors what the Django admin's
# ArticleAuthorInline already did (order, is_corresponding, add/remove),
# just as a standalone page instead of buried in /admin/.
ArticleAuthorFormSet = inlineformset_factory(
    Article, ArticleAuthor, form=ArticleAuthorForm, extra=2, can_delete=True,
)
