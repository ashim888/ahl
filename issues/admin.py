from django.contrib import admin

from articles.models import Article

from .models import Issue


class ArticleInline(admin.TabularInline):
    """Assign articles to this issue. Article.issue is a FK (not M2M — see
    ARCHITECTURE.md §5), so assembly happens here rather than via filter_horizontal.
    """
    model = Article
    fk_name = 'issue'
    fields = ['title', 'article_type', 'status']
    extra = 0
    show_change_link = True


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'volume', 'number', 'publication_date', 'is_published']
    list_filter = ['is_published']
    inlines = [ArticleInline]
