"""Find uploaded files under MEDIA_ROOT that nothing references any more,
and optionally move them out of public reach.

    python manage.py quarantine_orphan_media          # list only
    python manage.py quarantine_orphan_media --move   # move to ORPHAN_MEDIA_ROOT

"Referenced" means: the value of any FileField/ImageField on any model, or a
MEDIA_URL path appearing inside any long-text field (images inserted in the
article editor are only referenced from Article.html_content, for example).
Files changed in the last --grace-days are left alone — an editor may have
just uploaded an image into a draft that isn't saved yet.

Nothing is deleted. Moved files keep their relative path under
ORPHAN_MEDIA_ROOT (not served by the web server) and each run appends to
its manifest.tsv, so any file can be put back by moving it back.
"""
import datetime
import os
import re
import shutil
from pathlib import Path
from urllib.parse import unquote

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import models
from django.utils import timezone


def referenced_media_names() -> set[str]:
    """Every MEDIA_ROOT-relative name the database points at."""
    names = set()
    media_url = settings.MEDIA_URL
    url_pattern = re.compile(re.escape(media_url) + r'([^"\'\s<>)?#]+)')
    for model in apps.get_models():
        file_fields = [f.name for f in model._meta.get_fields() if isinstance(f, models.FileField)]
        # Long-text fields only (article/newsletter HTML, descriptions):
        # that's where editor-inserted images live, and scanning every short
        # CharField means a LIKE over large log/analytics tables.
        text_fields = [f.name for f in model._meta.get_fields() if isinstance(f, models.TextField)]
        if file_fields:
            for row in model._default_manager.values_list(*file_fields):
                names.update(value for value in row if value)
        for field in text_fields:
            for value in model._default_manager.filter(**{f'{field}__contains': media_url}).values_list(field, flat=True):
                names.update(unquote(match) for match in url_pattern.findall(value or ''))
    return names


class Command(BaseCommand):
    help = 'Lists (or with --move, quarantines) files under MEDIA_ROOT that nothing references.'

    def add_arguments(self, parser):
        parser.add_argument('--move', action='store_true', help='Move orphans to ORPHAN_MEDIA_ROOT (default: list only).')
        parser.add_argument('--grace-days', type=int, default=2, help='Skip files changed within this many days.')

    def handle(self, *args, move=False, grace_days=2, **options):
        media_root = Path(settings.MEDIA_ROOT)
        target_root = Path(settings.ORPHAN_MEDIA_ROOT)
        referenced = referenced_media_names()
        cutoff = timezone.now().timestamp() - grace_days * 86400

        orphans, total_bytes = [], 0
        for path in sorted(media_root.rglob('*')):
            if not path.is_file() or path.name.startswith('.'):
                continue
            name = path.relative_to(media_root).as_posix()
            if name in referenced or path.stat().st_mtime > cutoff:
                continue
            orphans.append((name, path))
            total_bytes += path.stat().st_size

        for name, _path in orphans:
            self.stdout.write(name)
        self.stdout.write(self.style.NOTICE(
            f'{len(orphans)} unreferenced file(s), {total_bytes / 1_048_576:.1f} MB '
            f'({len(referenced)} referenced names checked).',
        ))
        if not move or not orphans:
            if orphans and not move:
                self.stdout.write('Nothing moved. Run with --move to quarantine them.')
            return

        stamp = timezone.localtime().strftime('%Y-%m-%d %H:%M')
        target_root.mkdir(parents=True, exist_ok=True)
        with open(target_root / 'manifest.tsv', 'a', encoding='utf-8') as manifest:
            for name, path in orphans:
                destination = target_root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(destination))
                manifest.write(f'{stamp}\t{name}\n')
        # Tidy up directories the move left empty.
        for directory in sorted((p for p in media_root.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()
        self.stdout.write(self.style.SUCCESS(f'Moved {len(orphans)} file(s) to {target_root} (see manifest.tsv).'))
