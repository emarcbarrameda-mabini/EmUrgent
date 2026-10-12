from django.urls import path
from django.urls import reverse_lazy
from django.views.generic import RedirectView
from django.views.decorators.cache import never_cache
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.login_view, name='login'),
    path('home/', views.home, name='home'),
    path('report/<int:report_id>/', views.report_detail, name='report_detail'),
    path('report/<int:report_id>/comment/', views.post_report_comment, name='post_report_comment'),
    path('register/', views.register, name='register'),
    path('terms/', views.terms, name='terms'),
    path('logout/', never_cache(auth_views.LogoutView.as_view(next_page='login')), name='logout'),
    path('notifications/read/', views.mark_notifications_read, name='mark_notifications_read'),
    path('notifications/<int:notification_id>/', views.notification_detail, name='notification_detail'),
    path('resubmit-proof/', views.resubmit_proof, name='resubmit_proof'),
    # keep a redirect from the old literal URL to the new barangay-specific path
    path('admin-dashboard/', RedirectView.as_view(url='/barangay-admin-dashboard/', permanent=True)),
    # barangay-specific admin dashboard
    path('barangay-admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('preview-membership-email/<int:profile_id>/', views.preview_membership_email, name='preview_membership_email'),
    path('resend-membership-email/', views.resend_membership_email, name='resend_membership_email'),
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='registration/password_reset.html'
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html'
    ), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html',
        success_url=reverse_lazy('login')
    ), name='password_reset_confirm'),
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html'
    ), name='password_reset_complete'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('reports/my/fragment/', views.my_reports_fragment, name='my_reports_fragment'),
]
