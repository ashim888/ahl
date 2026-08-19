from django import forms
from django.forms import inlineformset_factory

from users.models import User

from .models import Article, ArticleAuthor


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

    class Meta:
        model = Article
        # No date fields here on purpose — created_at covers "when was this
        # made" and publication_date is stamped automatically by Article.save()
        # the moment status becomes Published (see articles/models.py).
        fields = [
            'title', 'slug', 'article_type', 'access_type', 'price', 'is_pinned', 'homepage_section',
            'abstract', 'keywords', 'issue', 'volume', 'page_numbers', 'doi',
            'html_content', 'references', 'featured_image', 'pdf_file',
        ]
        widgets = {
            'abstract': forms.Textarea(attrs={'rows': 5}),
            'html_content': forms.Textarea(attrs={'rows': 16, 'class': 'font-mono text-xs'}),
            'references': forms.Textarea(attrs={'rows': 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['homepage_section'].choices = [('', "Auto (don't feature)")] + list(Article.HomepageSection.choices)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('access_type') == Article.AccessType.PAY_PER_ARTICLE and not cleaned_data.get('price'):
            self.add_error('price', 'Set a price for pay-per-article articles.')
        return cleaned_data


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
