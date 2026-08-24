from django import forms

from articles.models import Article
from users.models import User

from .models import ArticlePurchase, SubscriptionPlan, UserSubscription
from .services import start_subscription


class SubscriptionPlanForm(forms.ModelForm):
    class Meta:
        model = SubscriptionPlan
        fields = ['name', 'plan_type', 'price', 'duration_days', 'description', 'features', 'is_featured', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'features': forms.CheckboxSelectMultiple,
        }


class GrantSubscriptionForm(forms.ModelForm):
    """Stands in for Stripe checkout until that exists — an editor picks a
    reader and a plan, and the subscription window is set from the plan's
    duration_days automatically (start today, end = today + duration_days).
    """

    class Meta:
        model = UserSubscription
        fields = ['user', 'plan']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = User.objects.order_by('first_name', 'last_name')
        self.fields['plan'].queryset = SubscriptionPlan.objects.filter(is_active=True)

    def save(self, commit=True):
        # commit is always effectively True here — start_subscription() always
        # creates the row — but the ModelForm.save(commit=...) signature is
        # kept so this drops in anywhere a ModelForm is expected.
        cleaned = self.cleaned_data
        return start_subscription(cleaned['user'], cleaned['plan'])


class GrantPurchaseForm(forms.ModelForm):
    """Manually records a pay-per-article purchase — e.g. paid by bank
    transfer/invoice outside Stripe. Amount defaults to the article's price
    but stays editable in case a different amount was actually collected.
    """

    class Meta:
        model = ArticlePurchase
        fields = ['user', 'article', 'amount']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = User.objects.order_by('first_name', 'last_name')
        self.fields['article'].queryset = Article.objects.filter(
            access_type=Article.AccessType.PAY_PER_ARTICLE,
        ).order_by('-created_at')
