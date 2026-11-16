from django.apps import AppConfig


class LibraryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'library'
    verbose_name = 'Health library'

    def ready(self):
        from django.db.models.signals import m2m_changed, post_delete, post_save

        from .glossary_marking import clear_cache
        from .models import GlossaryTerm

        # Article pages mark glossary terms from a cached index; any change to a
        # term (name, alias, published, deleted) has to show up straight away.
        post_save.connect(clear_cache, sender=GlossaryTerm, dispatch_uid='glossary-marking-save')
        post_delete.connect(clear_cache, sender=GlossaryTerm, dispatch_uid='glossary-marking-delete')
        m2m_changed.connect(clear_cache, sender=GlossaryTerm.related_terms.through, dispatch_uid='glossary-marking-m2m')
