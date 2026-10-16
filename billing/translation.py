from modeltranslation.translator import TranslationOptions, register

from .models import PlanFeature, SubscriptionPlan


@register(PlanFeature)
class PlanFeatureTranslationOptions(TranslationOptions):
    fields = ('label',)


@register(SubscriptionPlan)
class SubscriptionPlanTranslationOptions(TranslationOptions):
    fields = ('name', 'description')
