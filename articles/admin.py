from django.contrib import admin

from .models import Article, ArticleAuthor, Author


class ArticleAuthorInline(admin.TabularInline):
    model = ArticleAuthor
    extra = 1
    autocomplete_fields = ['author']


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ['name', 'affiliation', 'user', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'affiliation', 'email', 'user__email']
    prepopulated_fields = {'slug': ('name',)}
    raw_id_fields = ['user']


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ['title', 'article_type', 'access_type', 'status', 'issue', 'publication_date', 'doi']
    list_select_related = ['issue']
    list_filter = ['article_type', 'access_type', 'status']
    search_fields = ['title', 'abstract', 'keyword_tags__name', 'doi']
    prepopulated_fields = {'slug': ('title',)}
    inlines = [ArticleAuthorInline]
