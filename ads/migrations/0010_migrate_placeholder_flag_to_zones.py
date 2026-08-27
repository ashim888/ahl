from django.db import migrations

# Hardcoded snapshot of AdSlot.Zone.values as of this migration — migrations
# must not depend on the live model, which can change independently later.
ALL_ZONES = [
    'header_leaderboard', 'mobile_anchor', 'mobile_large_banner', 'homepage_rectangle',
    'homepage_rectangle_2', 'homepage_rectangle_3', 'homepage_leaderboard', 'article_in_content',
    'article_content_banner', 'article_sidebar', 'article_sidebar_half_page',
]


def migrate_flag_to_zones(apps, schema_editor):
    AdSettings = apps.get_model('ads', 'AdSettings')
    settings_row = AdSettings.objects.filter(pk=1).first()
    if settings_row is None:
        return
    # The sitewide boolean this replaces defaulted to True meaning "show the
    # placeholder in every zone" — preserve that exact behavior for existing
    # installs, rather than silently turning placeholders off everywhere.
    if settings_row.show_placeholder_when_empty:
        settings_row.placeholder_zones = ALL_ZONES
        settings_row.save(update_fields=['placeholder_zones'])


def reverse(apps, schema_editor):
    AdSettings = apps.get_model('ads', 'AdSettings')
    settings_row = AdSettings.objects.filter(pk=1).first()
    if settings_row is None:
        return
    settings_row.show_placeholder_when_empty = bool(settings_row.placeholder_zones)
    settings_row.save(update_fields=['show_placeholder_when_empty'])


class Migration(migrations.Migration):

    dependencies = [
        ('ads', '0009_adsettings_placeholder_zones'),
    ]

    operations = [
        migrations.RunPython(migrate_flag_to_zones, reverse),
    ]
