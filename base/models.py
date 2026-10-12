from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver


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
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='low')
    description = models.TextField()
    photo = models.ImageField(upload_to='reports/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} — {self.user.username}"


class Notification(models.Model):
    TYPE_CHOICES = [
        ('report_submitted', 'Report Submitted'),
        ('status_changed', 'Status Changed'),
        ('resolved', 'Report Resolved'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='notifications')
    notif_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.notif_type} — {self.user.username}"


# Signal: notify user when report is submitted
@receiver(post_save, sender=Report)
def notify_on_submit(sender, instance, created, **kwargs):
    if created:
        Notification.objects.create(
            user=instance.user,
            report=instance,
            notif_type='report_submitted',
            message=f'Your report "{instance.title}" has been submitted successfully.'
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
            Notification.objects.create(
                user=instance.user,
                report=instance,
                notif_type='resolved',
                message=f'Your report "{instance.title}" has been marked as Resolved. Thank you!'
            )
        elif instance.status == 'in_progress':
            Notification.objects.create(
                user=instance.user,
                report=instance,
                notif_type='status_changed',
                message=f'Your report "{instance.title}" is now In Progress.'
            )
        else:
            Notification.objects.create(
                user=instance.user,
                report=instance,
                notif_type='status_changed',
                message=f'Your report "{instance.title}" status changed to {instance.get_status_display()}.'
            )