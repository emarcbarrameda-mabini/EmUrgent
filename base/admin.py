from django.contrib import admin
from .models import Report, Notification


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'location', 'priority', 'status', 'created_at')
    list_filter = ('status', 'priority')
    search_fields = ('title', 'location', 'user__username')
    list_editable = ('status',)
    ordering = ('-created_at',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'notif_type', 'message', 'is_read', 'created_at')
    list_filter = ('notif_type', 'is_read')
    ordering = ('-created_at',)