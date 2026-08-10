from django.contrib import admin

from .models import Article, ArticleAuthor


class ArticleAuthorInline(admin.TabularInline):
    model = ArticleAuthor
    extra = 1


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ['title', 'article_type', 'access_type', 'status', 'issue', 'publication_date', 'doi']
    list_filter = ['article_type', 'access_type', 'status']
    search_fields = ['title', 'abstract', 'keywords', 'doi']
    prepopulated_fields = {'slug': ('title',)}
    inlines = [ArticleAuthorInline]
