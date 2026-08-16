from django.urls import path

from . import views

app_name = 'billing'

urlpatterns = [
    # Public — self-serve browsing & checkout (StubGateway for now, see billing/gateway.py)
    path('subscribe/', views.PlanBrowseView.as_view(), name='plan_browse'),
    path('subscribe/<int:pk>/checkout/', views.subscribe_checkout, name='subscribe_checkout'),
    path('articles/<slug:slug>/purchase/', views.purchase_checkout, name='purchase_checkout'),

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
]
