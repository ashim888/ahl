from django.views.static import serve
from django.urls import re_path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from articles.sitemaps import NewsArticleSitemap, sitemaps
from ajna_health_lens.ckeditor_views import ckeditor5_upload_file
from ajna_health_lens.comments_views import rate_limited_post_comment
from ajna_health_lens.views import robots_txt


urlpatterns = [
    path('admin/', admin.site.urls),
    # Registered directly (not via include('django_ckeditor_5.urls')) under
    # the exact view name the widget reverses, so the upload endpoint goes
    # through EDITORIAL_ROLES instead of the package's own weaker check —
    # see ckeditor_views.py and the CKEDITOR_5_FILE_UPLOAD_PERMISSION
    # comment in settings.py.
    path('ckeditor5/image_upload/', ckeditor5_upload_file, name='ck_editor_5_upload_file'),
    path('', include('articles.urls')),
    path('', include('issues.urls')),
    path('', include('users.urls')),
    # submissions.urls deliberately NOT included — OJS owns manuscript
    # submission now (CLAUDE.md SCOPE NOTE / ARCHITECTURE.md §4.4). The app
    # stays in INSTALLED_APPS (models/admin/migrations kept for a possible
    # future OJS integration), but its views are unrouted: they were only
    # ever guarded by @verification_required, so any verified_author could
    # still reach the old 3-step academic wizard by URL even with no nav
    # link to it — see ROADMAP.md Risk Register (August 2026 audit resolved
    # this as "unroute", not "leave reachable by accident").
    path('', include('editorial_board.urls')),
    path('', include('sections.urls')),
    path('', include('training.urls')),
    path('', include('billing.urls')),
    path('', include('newsletter.urls')),
    path('', include('ads.urls')),
    path('', include('pitches.urls')),
    # Overrides django_comments' own 'comments-post-comment' URL with a
    # rate-limited wrapper (see comments_views.py) — must come before the
    # django_comments_xtd include below, since Django resolves URLs in
    # list order and the first match wins. django_comments_xtd.urls also
    # includes django_comments.urls (the actual post/delete/flag endpoints)
    # under this same prefix.
    path('comments/post/', rate_limited_post_comment, name='comments-post-comment'),
    path('comments/', include('django_comments_xtd.urls')),
    path('editorial/', include('admin_custom.urls')),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path(
        'news-sitemap.xml', sitemap, {'sitemaps': {'news': NewsArticleSitemap}, 'template_name': 'sitemaps/news_sitemap.xml'},
        name='news_sitemap',
    ),
    path('robots.txt', robots_txt, name='robots_txt'),
    # Django's built-in set_language view — POST-only, sets the
    # django_language cookie LocaleMiddleware reads (see settings.py), then
    # redirects to ?next=. Powers the language switcher in base.html.
    path('i18n/', include('django.conf.urls.i18n')),
    re_path(
        r'^media/(?P<path>.*)$',
        serve,
        {'document_root': settings.MEDIA_ROOT},
    ),
    re_path(
        r'^static/(?P<path>.*)$',
        serve,
        {'document_root': settings.STATIC_ROOT},
    ),
]

# Django serves /media/ itself only in DEBUG — Django's own docs call this
# "wildly inefficient and probably insecure" outside development. In
# production, nginx (or Apache) serves /media/ directly from MEDIA_ROOT
# instead — see the nginx location block in ARCHITECTURE.md §9.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    import debug_toolbar
    urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
