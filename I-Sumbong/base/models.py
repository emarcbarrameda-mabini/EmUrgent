from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.utils import timezone
from django.conf import settings


def _file_exists(file_field):
    try:
        return bool(file_field and getattr(file_field, 'name', '') and file_field.storage.exists(file_field.name))
    except Exception:
        return False


def _safe_file_url(file_field):
    try:
        return file_field.url if _file_exists(file_field) else ''
    except Exception:
        return ''


def _is_image_name(name):
    lowered = (name or '').lower()
    return lowered.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif'))


class Report(models.Model):
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reports')
    title = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    # optional geolocation (latitude / longitude)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='low')
    description = models.TextField()
    photo = models.ImageField(upload_to='reports/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_reports')
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # timestamp when report was resolved (set when status changes to 'resolved')
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} — {self.user.username}"

    @property
    def safe_photo_url(self):
        return _safe_file_url(self.photo)

    @property
    def display_image_urls(self):
        urls = [img.safe_url for img in self.images.all() if img.safe_url]
        if urls:
            return urls
        return [self.safe_photo_url] if self.safe_photo_url else []


class Notification(models.Model):
    TYPE_CHOICES = [
        ('report_submitted', 'Report Submitted'),
        ('status_changed', 'Status Changed'),
        ('resolved', 'Report Resolved'),
        ('admin_action', 'Admin Action'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='notifications')
    notif_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    # delivery tracking
    delivery_status = models.CharField(max_length=20, default='pending', choices=[('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')])
    delivery_attempts = models.IntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.notif_type} — {self.user.username}"


class ReportAction(models.Model):
    ACTION_CHOICES = [
        ('acknowledged', 'Acknowledged'),
        ('for_verification', 'For Verification'),
        ('dispatched_team', 'Dispatched Team'),
        ('scheduled_repair', 'Scheduled Repair/Cleanup'),
        ('need_more_info', 'Need More Info'),
        ('duplicate_report', 'Duplicate Report'),
        ('outside_scope', 'Outside Scope'),
        ('resolved', 'Resolved'),
    ]

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='actions')
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='report_actions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.report.title} - {self.get_action_display()}"


class ReportImage(models.Model):
    report = models.ForeignKey('Report', on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='reports/images/')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Image for {self.report.title}"

    @property
    def safe_url(self):
        return _safe_file_url(self.image)


class Barangay(models.Model):
    name = models.CharField(max_length=120, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class CommunityProfile(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='community_profile')
    barangay = models.ForeignKey(Barangay, on_delete=models.PROTECT, related_name='community_members')
    address = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, blank=True)
    proof_of_residency = models.ImageField(upload_to='residency_proofs/')
    avatar = models.ImageField(upload_to='profiles/', null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_community_profiles')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} ({self.barangay.name}) - {self.get_status_display()}"

    @property
    def safe_avatar_url(self):
        return _safe_file_url(self.avatar)


class BarangayAdminProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='barangay_admin_profile')
    barangay = models.ForeignKey(Barangay, on_delete=models.PROTECT, related_name='admin_profiles')

    class Meta:
        verbose_name = 'Barangay Admin Profile'
        verbose_name_plural = 'Barangay Admin Profiles'

    def __str__(self):
        return f"{self.user.username} - {self.barangay.name}"


class BulletinPost(models.Model):
    CATEGORY_CHOICES = [
        ('announcement', 'Announcement'),
        ('memorandum', 'Memorandum'),
        ('advisory', 'Advisory'),
        ('event', 'Event'),
        ('public_safety', 'Public Safety Notice'),
        ('health_notice', 'Health Notice'),
        ('disaster_update', 'Disaster Update'),
        ('service_schedule', 'Service Schedule'),
        ('project_update', 'Project Update'),
        ('lost_and_found', 'Lost and Found'),
        ('ordinance', 'Ordinance / Resolution'),
        ('volunteer_call', 'Volunteer Call'),
        ('job_opportunity', 'Job / Livelihood Opportunity'),
        ('document_requirement', 'Document Requirements'),
        ('report_status', 'Report Status Update'),
    ]

    POST_TYPE_CHOICES = [
        ('bulletin', 'Bulletin'),
        ('memorandum', 'Memorandum'),
    ]

    PRIORITY_CHOICES = [
        ('normal', 'Normal'),
        ('important', 'Important'),
        ('urgent', 'Urgent'),
    ]

    barangay = models.ForeignKey(Barangay, on_delete=models.PROTECT, related_name='bulletins')
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    post_type = models.CharField(max_length=20, choices=POST_TYPE_CHOICES, default='bulletin')
    content = models.TextField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    attachment = models.FileField(upload_to='bulletins/', blank=True, null=True)
    is_pinned = models.BooleanField(default=False)
    expires_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='bulletins_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_pinned', '-created_at']

    def __str__(self):
        return f"{self.title} ({self.barangay.name})"

    @property
    def safe_attachment_url(self):
        return _safe_file_url(self.attachment)

    @property
    def display_image_urls(self):
        urls = [img.safe_url for img in self.images.all() if img.safe_url]
        if urls:
            return urls
        if self.safe_attachment_url and _is_image_name(getattr(self.attachment, 'name', '')):
            return [self.safe_attachment_url]
        return []


class BulletinImage(models.Model):
    post = models.ForeignKey(BulletinPost, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='bulletins/images/')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Image for {self.post.title}"

    @property
    def safe_url(self):
        return _safe_file_url(self.image)


class BulletinPostView(models.Model):
    post = models.ForeignKey(BulletinPost, on_delete=models.CASCADE, related_name='views')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bulletin_views')
    seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('post', 'user')

    def __str__(self):
        return f"{self.user.username} saw {self.post.title}"


class BulletinPostHistory(models.Model):
    ACTION_CHOICES = [
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('pin_toggled', 'Pin Toggled'),
        ('urgent_resent', 'Urgent Resent'),
        ('deleted', 'Deleted'),
    ]

    bulletin = models.ForeignKey(BulletinPost, on_delete=models.SET_NULL, null=True, blank=True, related_name='history')
    barangay = models.ForeignKey(Barangay, on_delete=models.PROTECT, related_name='bulletin_history')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='bulletin_history_actions')
    title_snapshot = models.CharField(max_length=200)
    category_snapshot = models.CharField(max_length=30)
    priority_snapshot = models.CharField(max_length=10)
    content_snapshot = models.TextField()
    is_pinned_snapshot = models.BooleanField(default=False)
    expires_at_snapshot = models.DateTimeField(null=True, blank=True)
    attachment_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        title = self.title_snapshot or 'Bulletin'
        return f"{title} - {self.get_action_display()}"


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('approve_user', 'Approve User'),
        ('reject_user', 'Reject User'),
        ('bulk_approve_users', 'Bulk Approve Users'),
        ('bulk_reject_users', 'Bulk Reject Users'),
        ('undo_bulk', 'Undo Bulk Action'),
        ('create_bulletin', 'Create Bulletin'),
        ('update_bulletin', 'Update Bulletin'),
        ('delete_bulletin', 'Delete Bulletin'),
        ('toggle_bulletin_pin', 'Toggle Bulletin Pin'),
        ('report_action', 'Report Action'),
        ('update_status', 'Update Report Status'),
        ('delete_report', 'Delete Report'),
        ('resend_urgent', 'Resend Urgent Bulletin'),
        ('resend_membership', 'Resend Membership Email'),
        ('promote_admin', 'Promote to Barangay Admin'),
        ('demote_admin', 'Demote Barangay Admin'),
        ('assign_report', 'Assign Report'),
    ]

    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='activity_logs')
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    target_type = models.CharField(max_length=50, blank=True)
    target_id = models.IntegerField(null=True, blank=True)
    target_repr = models.CharField(max_length=255, blank=True)
    barangay = models.ForeignKey(Barangay, on_delete=models.SET_NULL, null=True, blank=True, related_name='activity_logs')
    reason = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        actor = self.actor.username if self.actor else 'System'
        return f"{self.get_action_display()} by {actor} on {self.target_repr or self.target_type}"


# Signal: notify user when report is submitted
@receiver(post_save, sender=Report)
def notify_on_submit(sender, instance, created, **kwargs):
    if created:
        Notification.objects.create(
            user=instance.user,
            report=instance,
            notif_type='report_submitted',
            message=f'Your report "{instance.title}" has been submitted successfully.',
            delivery_status='pending'
        )


# Signal: notify user when status changes
@receiver(pre_save, sender=Report)
def notify_on_status_change(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        old = Report.objects.get(pk=instance.pk)
    except Report.DoesNotExist:
        return

    if old.status != instance.status:
        if instance.status == 'resolved':
            # record resolved timestamp; let the save continue normally
            instance.resolved_at = timezone.now()
            Notification.objects.create(
                user=instance.user,
                report=instance,
                notif_type='resolved',
                message=f'Your report "{instance.title}" has been marked as Resolved. Thank you!'
                ,delivery_status='pending'
            )
        elif instance.status == 'in_progress':
            Notification.objects.create(
                user=instance.user,
                report=instance,
                notif_type='status_changed',
                message=f'Your report "{instance.title}" is now In Progress.',
                delivery_status='pending'
            )
        else:
            Notification.objects.create(
                user=instance.user,
                report=instance,
                notif_type='status_changed',
                message=f'Your report "{instance.title}" status changed to {instance.get_status_display()}.'
                ,delivery_status='pending'
            )


# Attempt to deliver notifications (best-effort synchronous attempt)
@receiver(post_save, sender=Notification)
def deliver_notification(sender, instance, created, **kwargs):
    # only attempt when pending
    if instance.delivery_status != 'pending':
        return
    # simple email delivery if user has email
    if instance.user and instance.user.email:
        try:
            send_mail(
                f'i-Sumbong: {instance.get_notif_type_display() if hasattr(instance, "get_notif_type_display") else instance.notif_type}',
                instance.message,
                getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                [instance.user.email],
                fail_silently=False,
            )
            instance.delivery_status = 'sent'
            instance.delivery_attempts = (instance.delivery_attempts or 0) + 1
            instance.last_attempt_at = timezone.now()
            instance.last_error = ''
            instance.save(update_fields=['delivery_status', 'delivery_attempts', 'last_attempt_at', 'last_error'])
            return
        except Exception as e:
            instance.delivery_status = 'failed'
            instance.delivery_attempts = (instance.delivery_attempts or 0) + 1
            instance.last_attempt_at = timezone.now()
            instance.last_error = str(e)
            instance.save(update_fields=['delivery_status', 'delivery_attempts', 'last_attempt_at', 'last_error'])
            return


class ReportComment(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='comments')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='report_comments')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.user.username} on {self.report.title}"
