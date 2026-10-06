from django.urls import path

from . import org_views, promo_views, views

app_name = 'billing'

urlpatterns = [
    # Public — self-serve browsing & checkout (StubGateway for now, see billing/gateway.py)
    path('subscribe/', views.PlanBrowseView.as_view(), name='plan_browse'),
    path('subscribe/<int:pk>/', views.PlanDetailView.as_view(), name='plan_detail'),
    path('subscribe/<int:pk>/checkout/', views.subscribe_checkout, name='subscribe_checkout'),
    path('articles/<slug:slug>/purchase/', views.purchase_checkout, name='purchase_checkout'),
    # Fonepay checkout (settings.PAYMENT_GATEWAY = "fonepay") — see billing/payments.py
    path('pay/<str:reference>/', views.payment_page, name='payment_page'),
    path('pay/<str:reference>/status/', views.payment_check, name='payment_check'),
    path('account/billing/', views.account, name='account'),
    path('account/receipts/<str:reference>/', views.receipt, name='receipt'),
    path('account/subscriptions/<str:reference>/cancel/', views.subscription_cancel, name='subscription_cancel'),
    # Organization dashboard — the institution's own managers (billing/org_views.py)
    path('redeem/', promo_views.redeem, name='redeem'),
    path('redeem/<str:code>/', promo_views.redeem, name='redeem_code'),
    path('redeem/<str:code>/start-trial/', promo_views.start_trial, name='start_trial'),
    path('manage/billing/promos/', promo_views.PromoListView.as_view(), name='manage_promo_list'),
    path('manage/billing/promos/new/', promo_views.PromoCreateView.as_view(), name='manage_promo_create'),
    path('manage/billing/promos/<int:pk>/edit/', promo_views.PromoUpdateView.as_view(), name='manage_promo_update'),
    path('manage/billing/promos/<int:pk>/export.csv', promo_views.promo_export, name='manage_promo_export'),
    path('organization/', org_views.dashboard, name='org_dashboard'),
    path('organization/<int:pk>/', org_views.dashboard, name='org_dashboard_for'),
    path('organization/<int:pk>/report.csv', org_views.report_csv, name='org_report_csv'),
    path('organization/<int:pk>/invite/', org_views.invite, name='org_invite'),
    path('organization/<int:pk>/members/<int:member_pk>/remove/', org_views.member_remove, name='org_member_remove'),
    path('organization/<int:pk>/members/<int:member_pk>/restore/', org_views.member_restore, name='org_member_restore'),
    path('organization/<int:pk>/members/<int:member_pk>/manager/', org_views.member_manager, name='org_member_manager'),

    # Editorial — Editor/EiC/Admin (see EDITORIAL_ROLES in views.py)
    path('manage/billing/plans/', views.PlanListView.as_view(), name='manage_plan_list'),
    path('manage/billing/plans/new/', views.PlanCreateView.as_view(), name='manage_plan_create'),
    path('manage/billing/plans/<int:pk>/edit/', views.PlanUpdateView.as_view(), name='manage_plan_update'),
    path('manage/billing/plans/<int:pk>/toggle-active/', views.plan_toggle_active, name='manage_plan_toggle_active'),

    # Senior staff only — EiC/Admin (see SENIOR_STAFF_ROLES in views.py)
    path('manage/billing/subscriptions/', views.SubscriptionListView.as_view(), name='manage_subscription_list'),
    path('manage/billing/subscriptions/grant/', views.SubscriptionGrantView.as_view(), name='manage_subscription_grant'),
    path('manage/billing/subscriptions/<int:pk>/revoke/', views.subscription_revoke, name='manage_subscription_revoke'),
    path('manage/billing/purchases/', views.PurchaseListView.as_view(), name='manage_purchase_list'),
    path('manage/billing/purchases/grant/', views.PurchaseGrantView.as_view(), name='manage_purchase_grant'),
    path('manage/billing/payments/', views.PaymentListView.as_view(), name='manage_payment_list'),
    path('manage/billing/payments/<str:reference>/refund/', views.payment_refund, name='manage_payment_refund'),
    path('manage/billing/payments/<str:reference>/handled/', views.payment_clear_attention, name='manage_payment_handled'),
    path('manage/billing/organizations/', views.OrganizationListView.as_view(), name='manage_organization_list'),
    path('manage/billing/organizations/new/', views.OrganizationCreateView.as_view(), name='manage_organization_create'),
    path('manage/billing/organizations/<int:pk>/edit/', views.OrganizationUpdateView.as_view(), name='manage_organization_update'),
    path('manage/billing/organizations/<int:pk>/send-report/', views.organization_send_report, name='manage_organization_send_report'),
    path('manage/billing/organizations/<int:pk>/members/<int:member_pk>/manager/', views.organization_member_manager,
         name='manage_organization_member_manager'),
]
