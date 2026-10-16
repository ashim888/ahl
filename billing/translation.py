from modeltranslation.translator import TranslationOptions, register

from .models import PlanFeature


@register(PlanFeature)
class PlanFeatureTranslationOptions(TranslationOptions):
    fields = ('label',)
