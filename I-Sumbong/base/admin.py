from django.contrib import admin
from django.core.mail import send_mail
from django.utils import timezone
from .models import (
    Barangay,
    BarangayAdminProfile,
    BulletinPost,
    BulletinPostHistory,
    BulletinPostView,
    CommunityProfile,
    Report,
    ReportAction,
    Notification,
    ReportImage,
    BulletinImage,
    AuditLog,
    ReportComment,
)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'user_barangay', 'location', 'priority', 'status', 'assigned_to', 'latitude', 'longitude', 'resolved_at', 'created_at')
    list_filter = ('status', 'priority')
    search_fields = ('title', 'location', 'user__username')
    list_editable = ('status',)
    ordering = ('-created_at',)

    def user_barangay(self, obj):
        try:
            return obj.user.community_profile.barangay.name
        except Exception:
            return ''
    user_barangay.short_description = 'Barangay'


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'notif_type', 'message', 'is_read', 'delivery_status', 'delivery_attempts', 'last_attempt_at', 'created_at')
    list_filter = ('notif_type', 'is_read', 'delivery_status')
    ordering = ('-created_at',)
    actions = ['retry_delivery']

    def retry_delivery(self, request, queryset):
        sent = 0
        failed = 0
        for n in queryset:
            # attempt delivery by email
            try:
                if n.user and n.user.email:
                    send_mail(
                        f'i-Sumbong: {n.get_notif_type_display() if hasattr(n, "get_notif_type_display") else n.notif_type}',
                        n.message,
                        getattr(__import__('django.conf').conf.settings, 'DEFAULT_FROM_EMAIL', None),
                        [n.user.email],
                        fail_silently=False,
                    )
                    n.delivery_status = 'sent'
                    n.delivery_attempts = (n.delivery_attempts or 0) + 1
                    n.last_attempt_at = timezone.now()
                    n.last_error = ''
                    n.save(update_fields=['delivery_status', 'delivery_attempts', 'last_attempt_at', 'last_error'])
                    sent += 1
                else:
                    n.last_error = 'No user email'
                    n.delivery_status = 'failed'
                    n.delivery_attempts = (n.delivery_attempts or 0) + 1
                    n.last_attempt_at = timezone.now()
                    n.save(update_fields=['delivery_status', 'delivery_attempts', 'last_attempt_at', 'last_error'])
                    failed += 1
            except Exception as e:
                n.delivery_status = 'failed'
                n.delivery_attempts = (n.delivery_attempts or 0) + 1
                n.last_attempt_at = timezone.now()
                n.last_error = str(e)
                n.save(update_fields=['delivery_status', 'delivery_attempts', 'last_attempt_at', 'last_error'])
                failed += 1
        self.message_user(request, f'Retry completed: {sent} sent, {failed} failed')
    retry_delivery.short_description = 'Retry delivery for selected notifications'


@admin.register(ReportAction)
class ReportActionAdmin(admin.ModelAdmin):
    list_display = ('report', 'action', 'created_by', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('report__title', 'report__location', 'note', 'created_by__username')
    ordering = ('-created_at',)


@admin.register(Barangay)
class BarangayAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(CommunityProfile)
class CommunityProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'barangay', 'phone_number', 'status', 'created_at', 'reviewed_by', 'reviewed_at')
    list_filter = ('status', 'barangay')
    search_fields = ('user__username', 'user__email', 'address', 'barangay__name', 'phone_number')
    ordering = ('-created_at',)


@admin.register(BarangayAdminProfile)
class BarangayAdminProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'barangay')
    list_filter = ('barangay',)
    search_fields = ('user__username', 'barangay__name')


@admin.register(BulletinPost)
class BulletinPostAdmin(admin.ModelAdmin):
    list_display = ('title', 'barangay', 'category', 'priority', 'is_pinned', 'expires_at', 'created_at')
    list_filter = ('barangay', 'category', 'priority', 'is_pinned')
    search_fields = ('title', 'content', 'barangay__name')
    ordering = ('-is_pinned', '-created_at')


@admin.register(BulletinPostView)
class BulletinPostViewAdmin(admin.ModelAdmin):
    list_display = ('post', 'user', 'seen_at')
    list_filter = ('seen_at',)
    search_fields = ('post__title', 'user__username')
    ordering = ('-seen_at',)


@admin.register(BulletinPostHistory)
class BulletinPostHistoryAdmin(admin.ModelAdmin):
    list_display = ('title_snapshot', 'barangay', 'action', 'changed_by', 'created_at')
    list_filter = ('action', 'barangay')
    search_fields = ('title_snapshot', 'content_snapshot', 'changed_by__username')
    ordering = ('-created_at',)


@admin.register(ReportImage)
class ReportImageAdmin(admin.ModelAdmin):
    list_display = ('report', 'created_at')
    search_fields = ('report__title',)
    ordering = ('-created_at',)


@admin.register(BulletinImage)
class BulletinImageAdmin(admin.ModelAdmin):
    list_display = ('post', 'created_at')
    search_fields = ('post__title',)
    ordering = ('-created_at',)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'actor', 'target_repr', 'barangay', 'created_at')
    search_fields = ('actor__username', 'target_repr', 'reason')
    list_filter = ('action', 'barangay')
    ordering = ('-created_at',)


@admin.register(ReportComment)
class ReportCommentAdmin(admin.ModelAdmin):
    list_display = ('report', 'user', 'parent', 'created_at')
    search_fields = ('report__title', 'user__username', 'message')
    ordering = ('-created_at',)