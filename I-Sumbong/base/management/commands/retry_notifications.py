from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.utils import timezone
from django.conf import settings
from base.models import Notification

class Command(BaseCommand):
    help = 'Retry pending/failed notifications (email delivery)'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100, help='Maximum notifications to process')

    def handle(self, *args, **options):
        limit = options.get('limit') or 100
        qs = Notification.objects.filter(delivery_status__in=['pending', 'failed']).order_by('created_at')[:limit]
        total = qs.count()
        sent = 0
        failed = 0
        for n in qs:
            try:
                if n.user and n.user.email:
                    send_mail(
                        f'i-Sumbong: {n.get_notif_type_display() if hasattr(n, "get_notif_type_display") else n.notif_type}',
                        n.message,
                        getattr(settings, 'DEFAULT_FROM_EMAIL', None),
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
                    n.delivery_status = 'failed'
                    n.delivery_attempts = (n.delivery_attempts or 0) + 1
                    n.last_attempt_at = timezone.now()
                    n.last_error = 'No user email'
                    n.save(update_fields=['delivery_status', 'delivery_attempts', 'last_attempt_at', 'last_error'])
                    failed += 1
            except Exception as e:
                n.delivery_status = 'failed'
                n.delivery_attempts = (n.delivery_attempts or 0) + 1
                n.last_attempt_at = timezone.now()
                n.last_error = str(e)
                n.save(update_fields=['delivery_status', 'delivery_attempts', 'last_attempt_at', 'last_error'])
                failed += 1
        self.stdout.write(self.style.SUCCESS(f'Processed {total} notifications: sent={sent} failed={failed}'))
