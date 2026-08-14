from django import forms

from .models import Article


class ArticleForm(forms.ModelForm):
    """Front-end editorial CRUD form. Authors (the Article<->User through model,
    with ordering/corresponding-author flags) are deliberately still managed via
    the Django admin's inline — a plain multi-select here can't represent that
    ordering cleanly, so this form sticks to the article's own fields.

    No `status` field on purpose — status is set procedurally by
    ArticleFormMixin.form_valid() based on which submit button (Save as
    Draft / Save & Publish) was pressed, not a dropdown that could disagree
    with it. Archiving an article stays a Django-admin-only action, same as
    author ordering — see the note in article_form.html.
    """

    class Meta:
        model = Article
        # No date fields here on purpose — created_at covers "when was this
        # made" and publication_date is stamped automatically by Article.save()
        # the moment status becomes Published (see articles/models.py).
        fields = [
            'title', 'slug', 'article_type', 'access_type', 'is_pinned',
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
        self.fields['access_type'].required = False
        # access_type is a plain CharField+choices (not a FK), so the blank
        # option's label is set by overriding choices, not via empty_label.
        self.fields['access_type'].choices = [('', 'Default from article type')] + list(Article.AccessType.choices)


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
