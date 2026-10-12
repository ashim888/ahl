import re

from django import forms
from django.db import transaction

from articles.models import Article
from users.models import User

from .models import ArticlePurchase, Organization, PromoCode, SubscriptionPlan, UserSubscription
from .services import start_subscription

DOMAIN_RE = re.compile(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}')


class SubscriptionPlanForm(forms.ModelForm):
    class Meta:
        model = SubscriptionPlan
        fields = [
            'name', 'plan_type', 'price', 'duration_days', 'description', 'features',
            'grants_ad_free_reading', 'grants_unlimited_articles', 'grants_premium_newsletter',
            'grants_full_archive', 'gift_articles_per_month', 'is_featured', 'is_active',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'features': forms.CheckboxSelectMultiple,
        }


AMOUNT_RECEIVED_HELP = (
    'Money actually received for this, VAT included (e.g. by bank transfer). It is recorded as a payment, '
    'with a receipt emailed to the reader. Leave at 0 for complimentary access — no payment, no receipt.'
)


class GrantSubscriptionForm(forms.ModelForm):
    """Senior staff giving a reader a subscription by hand — complimentary,
    or paid outside the checkout (bank transfer). The window comes from the
    plan's duration, starting today or after the reader's current one ends
    (billing.services.start_subscription)."""

    amount_received = forms.DecimalField(
        label='Amount received (incl. VAT)', min_value=0, max_digits=10, decimal_places=2, initial=0,
        required=False, help_text=AMOUNT_RECEIVED_HELP,
    )

    class Meta:
        model = UserSubscription
        fields = ['user', 'plan']

    def __init__(self, *args, recorded_by=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.recorded_by = recorded_by
        self.fields['user'].queryset = User.objects.order_by('first_name', 'last_name')
        self.fields['plan'].queryset = SubscriptionPlan.objects.filter(is_active=True)

    def save(self, commit=True):
        # commit is always effectively True here — the row is always
        # created — but the ModelForm.save(commit=...) signature is kept so
        # this drops in anywhere a ModelForm is expected.
        from . import payments
        from .models import Payment

        cleaned = self.cleaned_data
        with transaction.atomic():
            subscription = start_subscription(cleaned['user'], cleaned['plan'])
            if cleaned.get('amount_received'):
                payment = payments.record_paid_payment(
                    user=cleaned['user'], kind=Payment.Kind.SUBSCRIPTION, plan=cleaned['plan'],
                    total_paid=cleaned['amount_received'], description=f'Subscription — {cleaned["plan"].name}',
                    gateway=Payment.Gateway.MANUAL, recorded_by=self.recorded_by, grant=False,
                )
                subscription.payment_reference = payment.reference
                subscription.save(update_fields=['payment_reference'])
        return subscription


class GrantPurchaseForm(forms.ModelForm):
    """Senior staff giving a reader a pay-per-article ("special") article —
    complimentary, or paid outside the checkout."""

    amount = forms.DecimalField(
        label='Amount received (incl. VAT)', min_value=0, max_digits=10, decimal_places=2, initial=0,
        help_text=AMOUNT_RECEIVED_HELP,
    )

    class Meta:
        model = ArticlePurchase
        fields = ['user', 'article', 'amount']

    def __init__(self, *args, recorded_by=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.recorded_by = recorded_by
        self.fields['user'].queryset = User.objects.order_by('first_name', 'last_name')
        self.fields['article'].queryset = Article.objects.filter(
            access_type=Article.AccessType.PAY_PER_ARTICLE,
        ).order_by('-created_at')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('user') and cleaned.get('article') and ArticlePurchase.objects.filter(
            user=cleaned['user'], article=cleaned['article'],
        ).exists():
            raise forms.ValidationError('This reader already has this article.')
        return cleaned

    def save(self, commit=True):
        from . import payments
        from .models import Payment
        from .money import split_vat_inclusive

        received = self.cleaned_data.get('amount') or 0
        with transaction.atomic():
            purchase = super().save(commit=False)
            # The purchase records the price excluding VAT, like a checkout purchase.
            purchase.amount = split_vat_inclusive(received)[0]
            if received:
                payment = payments.record_paid_payment(
                    user=purchase.user, kind=Payment.Kind.ARTICLE, article=purchase.article, total_paid=received,
                    description=f'Article — {purchase.article.title}', gateway=Payment.Gateway.MANUAL,
                    recorded_by=self.recorded_by, grant=False,
                )
                purchase.payment_reference = payment.reference
            purchase.save()
        return purchase


class OrganizationForm(forms.ModelForm):
    """An institutional deal. Any money received is recorded separately
    (amount_received) as a payment against the organization."""

    amount_received = forms.DecimalField(
        label='Record a payment received (incl. VAT)', min_value=0, max_digits=12, decimal_places=2, required=False,
        help_text='Optional. Records money received for this deal as a payment, and emails a receipt to the '
                  'contact email. Leave empty when nothing new was received.',
    )

    class Meta:
        model = Organization
        fields = [
            'name', 'email_domains', 'plan', 'start_date', 'end_date', 'seats', 'is_active',
            'contact_name', 'contact_email', 'pan', 'account_manager', 'notes',
        ]
        widgets = {
            'email_domains': forms.Textarea(attrs={'rows': 3, 'placeholder': 'nhrc.gov.np'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plan'].queryset = SubscriptionPlan.objects.order_by('-is_active', 'name')
        self.fields['account_manager'].queryset = User.objects.filter(
            role__in=User.EDITORIAL_ROLES, is_active=True,
        ).order_by('first_name', 'last_name')
        self.fields['account_manager'].help_text = (
            'Our staff contact for this organization — named on their dashboard, copied on usage reports '
            'and renewal reminders.'
        )

    def clean_email_domains(self):
        from .institutions import PUBLIC_EMAIL_DOMAINS

        domains = []
        for line in self.cleaned_data['email_domains'].splitlines():
            domain = line.strip().lower().lstrip('@')
            if not domain:
                continue
            if not DOMAIN_RE.fullmatch(domain):
                raise forms.ValidationError(f'"{domain}" isn\'t a domain — write it like nhrc.gov.np.')
            if domain in PUBLIC_EMAIL_DOMAINS:
                raise forms.ValidationError(
                    f'{domain} is a public email provider — anyone can get an address there, so it would give '
                    'everyone access.',
                )
            if domain not in domains:
                domains.append(domain)
        if not domains:
            raise forms.ValidationError('Add at least one email domain.')
        return '\n'.join(domains)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('start_date') and cleaned.get('end_date') and cleaned['end_date'] < cleaned['start_date']:
            self.add_error('end_date', 'The end date is before the start date.')
        if cleaned.get('amount_received') and not cleaned.get('contact_email'):
            self.add_error('contact_email', 'Add a contact email so the receipt has somewhere to go.')
        return cleaned


class PromoCodeForm(forms.ModelForm):
    """A promo code (billing/promotions.py). Either money off — a percentage
    or an amount — or a free trial, never both."""

    copies = forms.IntegerField(
        label='Also make single-use copies', min_value=0, max_value=500, required=False,
        help_text='For partner deals: makes this many extra codes (e.g. PARTNER-7K2Q), each usable once, with the '
                  'same settings. Leave empty for one shared code.',
    )

    class Meta:
        model = PromoCode
        fields = [
            'code', 'kind', 'description', 'campaign', 'partner_name',
            'percent_off', 'amount_off', 'trial_days', 'trial_plan',
            'applies_to_subscriptions', 'applies_to_articles', 'applies_to_courses', 'plans', 'courses',
            'valid_from', 'valid_until', 'max_redemptions', 'per_user_limit', 'new_subscribers_only', 'email_domains',
            'is_active', 'notes',
        ]
        widgets = {
            'valid_from': forms.DateInput(attrs={'type': 'date'}),
            'valid_until': forms.DateInput(attrs={'type': 'date'}),
            'email_domains': forms.Textarea(attrs={'rows': 3, 'placeholder': 'edu.np\nku.edu.np'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
            'plans': forms.CheckboxSelectMultiple,
            'courses': forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['trial_plan'].queryset = SubscriptionPlan.objects.exclude(
            plan_type=SubscriptionPlan.PlanType.INSTITUTIONAL).order_by('-is_active', 'price')
        self.fields['plans'].queryset = SubscriptionPlan.objects.exclude(
            plan_type=SubscriptionPlan.PlanType.INSTITUTIONAL).order_by('-is_active', 'price')
        if self.instance.pk:
            del self.fields['copies']

    def clean_code(self):
        code = self.cleaned_data['code'].strip().upper()
        if PromoCode.objects.filter(code=code).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('That code already exists.')
        return code

    def clean_email_domains(self):
        from .institutions import PUBLIC_EMAIL_DOMAINS

        domains = [d.strip().lower().lstrip('@.') for d in self.cleaned_data['email_domains'].replace(',', '\n').splitlines()
                   if d.strip()]
        public = [d for d in domains if d in PUBLIC_EMAIL_DOMAINS]
        if public:
            raise forms.ValidationError(f'Anyone can get an address at {", ".join(public)} — that limits nothing.')
        bad = [d for d in domains if not re.fullmatch(r'[a-z0-9-]+(\.[a-z0-9-]+)+', d)]
        if bad:
            raise forms.ValidationError(f'Not a domain: {", ".join(bad)}')
        return '\n'.join(domains)

    def clean(self):
        cleaned = super().clean()
        benefits = [name for name in ('percent_off', 'amount_off', 'trial_days') if cleaned.get(name)]
        if len(benefits) != 1:
            raise forms.ValidationError('Choose exactly one: a percentage off, an amount off, or free trial days.')
        if cleaned.get('percent_off') and cleaned['percent_off'] > 100:
            self.add_error('percent_off', 'At most 100%.')
        if cleaned.get('trial_days') and not cleaned.get('trial_plan'):
            self.add_error('trial_plan', 'Choose which plan the trial gives.')
        if not cleaned.get('trial_days') and not any(
                cleaned.get(f) for f in ('applies_to_subscriptions', 'applies_to_articles', 'applies_to_courses')):
            raise forms.ValidationError('Tick at least one of subscriptions, special articles or courses.')
        if cleaned.get('valid_from') and cleaned.get('valid_until') and cleaned['valid_until'] < cleaned['valid_from']:
            self.add_error('valid_until', 'Ends before it starts.')
        if cleaned.get('trial_days'):
            cleaned['kind'] = PromoCode.Kind.TRIAL
            cleaned['new_subscribers_only'] = True
            self.instance.kind = PromoCode.Kind.TRIAL
        return cleaned

    def make_copies(self, original, user) -> list:
        """The single-use copies asked for (create only)."""
        import secrets

        count = self.cleaned_data.get('copies') or 0
        alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        made = []
        while len(made) < count:
            suffix = ''.join(secrets.choice(alphabet) for _ in range(5))
            code = f'{original.code[:30]}-{suffix}'
            if PromoCode.objects.filter(code=code).exists():
                continue
            copy = PromoCode.objects.get(pk=original.pk)
            copy.pk = None
            copy.code = code
            copy.max_redemptions = 1
            copy.per_user_limit = 1
            copy.created_by = user
            copy.save()
            copy.plans.set(original.plans.all())
            copy.courses.set(original.courses.all())
            made.append(copy)
        return made
