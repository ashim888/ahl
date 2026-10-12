"""Web-size images uploaded before upload optimization existed
(ajna_health_lens/images.py): every ImageField file plus the images inserted
into article text (media/articles/inline/). Rewrites each file in place, under
the same name, only when that makes it smaller or strips metadata — so it's
safe to run more than once. Run with --dry-run first to see the savings."""
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import ImageField

from ajna_health_lens.images import KEEP_SIZE_MODELS, optimize_bytes

IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp'}


class Command(BaseCommand):
    help = 'Resize, strip metadata from and re-compress already-uploaded images.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report the savings without changing any file.')

    def _paths(self):
        """(path, keep_size) for every stored image, each once."""
        seen = set()
        media_root = Path(settings.MEDIA_ROOT)
        for model in apps.get_models():
            image_fields = [f.name for f in model._meta.concrete_fields if isinstance(f, ImageField)]
            if not image_fields:
                continue
            keep_size = model._meta.label_lower in KEEP_SIZE_MODELS
            for row in model._default_manager.values_list(*image_fields):
                for name in row:
                    if name and name not in seen:
                        seen.add(name)
                        yield media_root / name, keep_size
        inline = media_root / 'articles' / 'inline'
        if inline.exists():
            for path in inline.rglob('*'):
                relative = str(path.relative_to(media_root))
                if path.suffix.lower() in IMAGE_SUFFIXES and relative not in seen:
                    seen.add(relative)
                    yield path, False

    def handle(self, *args, dry_run=False, **options):
        before = after = changed = 0
        for path, keep_size in self._paths():
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            data = path.read_bytes()
            optimized = optimize_bytes(data, keep_size=keep_size)
            # Stripping metadata may cost a few bytes; never make a file noticeably bigger.
            if optimized is None or len(optimized) > len(data) + 1024:
                continue
            changed += 1
            before += len(data)
            after += len(optimized)
            if not dry_run:
                path.write_bytes(optimized)
            if options['verbosity'] > 1:
                self.stdout.write(f'{path}: {len(data) // 1024} KB → {len(optimized) // 1024} KB')
        verb = 'Would optimize' if dry_run else 'Optimized'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {changed} image(s): {before / 1048576:.1f} MB → {after / 1048576:.1f} MB.',
        ))
