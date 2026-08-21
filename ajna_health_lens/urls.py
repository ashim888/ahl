from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from articles.sitemaps import sitemaps
from ajna_health_lens.views import robots_txt

urlpatterns = [
    path('admin/', admin.site.urls),
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
    path('', include('training.urls')),
    path('', include('billing.urls')),
    path('', include('newsletter.urls')),
    path('', include('ads.urls')),
    path('', include('pitches.urls')),
    path('editorial/', include('admin_custom.urls')),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path('robots.txt', robots_txt, name='robots_txt'),
]

# Django serves /media/ itself only in DEBUG — Django's own docs call this
# "wildly inefficient and probably insecure" outside development. In
# production, nginx (or Apache) serves /media/ directly from MEDIA_ROOT
# instead — see the nginx location block in ARCHITECTURE.md §9.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    import debug_toolbar
    urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
