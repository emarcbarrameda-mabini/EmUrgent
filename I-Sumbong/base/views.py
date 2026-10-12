from datetime import datetime
import re

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.contrib import messages
from django.core.mail import send_mail
from django.http import JsonResponse
from django.urls import reverse
from django import forms
from django.utils import timezone
from django.views.decorators.cache import never_cache
import logging

logger = logging.getLogger(__name__)
from django.db.models import Count, Q
from django.core.paginator import Paginator
import csv
from django.http import HttpResponse
from django.db.models.functions import Lower, Trim
from django.conf import settings
import base64
import urllib.parse
import urllib.request
import os
from django.utils.dateparse import parse_datetime
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
    ReportComment,
    AuditLog,
)


class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'placeholder': 'Email Address',
            'class': 'form-input'
        })
    )
    address = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            'placeholder': 'Full Address',
            'class': 'form-input'
        })
    )
    phone_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Mobile Number (optional)',
            'class': 'form-input'
        })
    )
    barangay = forms.ModelChoiceField(
        queryset=Barangay.objects.none(),
        empty_label='Select your barangay',
        widget=forms.Select(attrs={'class': 'form-input'}),
        required=True,
    )
    proof_of_residency = forms.ImageField(
        required=True,
        widget=forms.ClearableFileInput(attrs={'class': 'form-input'}),
        help_text='Upload an ID or proof with your address.',
    )
    terms_accepted = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        label='I agree to the Terms and Conditions'
    )

    class Meta:
        model = User
        fields = (
            'username',
            'email',
            'address',
            'phone_number',
            'barangay',
            'proof_of_residency',
            'password1',
            'password2',
            'terms_accepted',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'placeholder': 'Username', 'class': 'form-input'})
        self.fields['password1'].widget.attrs.update({'placeholder': 'Password', 'class': 'form-input'})
        self.fields['password2'].widget.attrs.update({'placeholder': 'Confirm Password', 'class': 'form-input'})
        self.fields['barangay'].queryset = Barangay.objects.all().order_by('name')

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('This email is already registered.')
        return email

    def clean_phone_number(self):
        raw = (self.cleaned_data.get('phone_number') or '').strip()
        if not raw:
            return ''

        normalized = re.sub(r'[\s\-()]+', '', raw)
        if normalized.startswith('+'):
            if not normalized.startswith('+63'):
                raise forms.ValidationError('Please use a valid Philippine mobile number (+63 or 09 format).')
            digits = normalized[1:]
            if not digits.isdigit() or len(digits) != 12:
                raise forms.ValidationError('Please enter a valid mobile number.')
            return normalized

        if normalized.startswith('09'):
            if not normalized.isdigit() or len(normalized) != 11:
                raise forms.ValidationError('Please enter a valid mobile number.')
            return '+63' + normalized[1:]

        if normalized.startswith('9'):
            if not normalized.isdigit() or len(normalized) != 10:
                raise forms.ValidationError('Please enter a valid mobile number.')
            return '+63' + normalized

        raise forms.ValidationError('Please use a valid Philippine mobile number (+63 or 09 format).')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user


class CustomAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'placeholder': 'Username', 'class': 'form-input'})
        self.fields['password'].widget.attrs.update({'placeholder': 'Password', 'class': 'form-input'})


LOGIN_FORM_PREFIX = 'login'
REGISTER_FORM_PREFIX = 'register'


def _post_uses_prefix(request, prefix):
    return any(key.startswith(f'{prefix}-') for key in request.POST)


def _login_form(request=None, data=None, use_prefix=True):
    prefix = LOGIN_FORM_PREFIX if use_prefix else None
    return CustomAuthenticationForm(request, data=data, prefix=prefix)


def _register_form(data=None, files=None, use_prefix=True):
    prefix = REGISTER_FORM_PREFIX if use_prefix else None
    return CustomUserCreationForm(data=data, files=files, prefix=prefix)


def is_user_approved(user):
    profile = CommunityProfile.objects.filter(user=user).first()
    if not profile:
        return True
    return profile.status == CommunityProfile.STATUS_APPROVED


def _safe_int(value):
    try:
        return int(str(value).strip())
    except Exception:
        return None


def resolve_user_by_id_or_username(value):
    if not value:
        return None
    v = str(value).strip()
    uid = _safe_int(v)
    if uid is not None:
        return User.objects.filter(id=uid).first()
    # fallback: try username
    return User.objects.filter(username=v).first()


def _user_shares_report_barangay(user, report):
    viewer_profile = (
        CommunityProfile.objects.filter(
            user=user,
            status=CommunityProfile.STATUS_APPROVED,
        )
        .select_related('barangay')
        .first()
    )
    if not viewer_profile:
        return False

    report_profile = getattr(report.user, 'community_profile', None)
    return bool(report_profile and report_profile.barangay_id == viewer_profile.barangay_id)


def _user_administers_report_barangay(user, report):
    admin_profile = BarangayAdminProfile.objects.filter(user=user).select_related('barangay').first()
    report_profile = getattr(report.user, 'community_profile', None)
    return bool(admin_profile and report_profile and report_profile.barangay_id == admin_profile.barangay_id)


def show_waiting_approval(request, profile=None):
    if not profile:
        profile = CommunityProfile.objects.filter(user=request.user).select_related('barangay').first()
    return render(
        request,
        'base/waiting_approval.html',
        {
            'community_profile': profile,
            'barangays': Barangay.objects.all().order_by('name'),
        },
    )


def _validate_image_file(f):
    if not f:
        return True, None
    max_size = getattr(settings, 'MAX_UPLOAD_SIZE', 5 * 1024 * 1024)
    allowed_exts = {e.lower() for e in getattr(settings, 'ALLOWED_IMAGE_EXTENSIONS', ['jpg', 'jpeg', 'png', 'webp'])}
    name = getattr(f, 'name', '') or ''
    size = getattr(f, 'size', 0)
    if size and size > max_size:
        return False, f'File "{name}" exceeds the maximum size of {max_size // (1024*1024)} MB.'
    ext = os.path.splitext(name)[1].lower().lstrip('.')
    if ext and ext not in allowed_exts:
        return False, f'Unsupported file type: .{ext}. Allowed: {", ".join(sorted(allowed_exts))}.'
    content_type = getattr(f, 'content_type', '')
    if content_type and not content_type.startswith('image/'):
        return False, 'Uploaded file is not an image.'
    return True, None


def _validate_images_list(files):
    files = files or []
    max_count = getattr(settings, 'MAX_IMAGE_COUNT', 8)
    if len(files) > max_count:
        return False, f'Please upload up to {max_count} images.'
    for f in files:
        ok, err = _validate_image_file(f)
        if not ok:
            return False, err
    return True, None


def send_membership_decision_email(profile):
    if not profile.user.email:
        return

    approved = profile.status == CommunityProfile.STATUS_APPROVED
    decision_text = 'approved' if approved else 'rejected'
    subject = f'Your i-Sumbong registration was {decision_text}'
    reason = profile.review_notes.strip() if profile.review_notes else 'No additional reason provided.'
    body = (
        f'Hello {profile.user.username},\n\n'
        f'Your community account request for {profile.barangay.name} was {decision_text}.\n'
        f'Status: {profile.get_status_display()}\n'
        f'Review notes: {reason}\n\n'
        'If your account was rejected, you can log in and resubmit your proof of residency.\n\n'
        'Thank you,\n'
        'i-Sumbong Team'
    )
    send_mail(subject, body, None, [profile.user.email], fail_silently=True)


@never_cache
@login_required
def preview_membership_email(request, profile_id):
    if not request.user.is_staff:
        return JsonResponse({'error': 'forbidden'}, status=403)

    try:
        profile = CommunityProfile.objects.select_related('user', 'barangay').get(id=profile_id)
    except CommunityProfile.DoesNotExist:
        return JsonResponse({'error': 'not found'}, status=404)

    approved = profile.status == CommunityProfile.STATUS_APPROVED
    decision_text = 'approved' if approved else 'rejected'
    subject = f'Your i-Sumbong registration was {decision_text}'
    reason = profile.review_notes.strip() if profile.review_notes else 'No additional reason provided.'
    body = (
        f'Hello {profile.user.username},\n\n'
        f'Your community account request for {profile.barangay.name} was {decision_text}.\n'
        f'Status: {profile.get_status_display()}\n'
        f'Review notes: {reason}\n\n'
        'If your account was rejected, you can log in and resubmit your proof of residency.\n\n'
        'Thank you,\n'
        'i-Sumbong Team'
    )

    return JsonResponse({'subject': subject, 'body': body})


@never_cache
@login_required
def resend_membership_email(request):
    if request.method != 'POST' or not request.user.is_staff:
        return JsonResponse({'error': 'forbidden'}, status=403)

    profile_id = request.POST.get('profile_id')
    if not profile_id:
        return JsonResponse({'error': 'missing profile_id'}, status=400)

    try:
        profile = CommunityProfile.objects.get(id=profile_id)
    except CommunityProfile.DoesNotExist:
        return JsonResponse({'error': 'not found'}, status=404)

    try:
        send_membership_decision_email(profile)
        AuditLog.objects.create(
            actor=request.user,
            action='resend_membership',
            target_type='CommunityProfile',
            target_id=profile.id,
            target_repr=profile.user.username,
            barangay=profile.barangay,
            reason='Manual resend of membership email',
            data={'status': profile.status}
        )
    except Exception:
        return JsonResponse({'error': 'send_failed'}, status=500)

    return JsonResponse({'ok': True})


def notify_admin_action(report, action_label, note):
    message = f'Barangay update: {action_label}.'
    if note:
        message = f'{message} Notes: {note}'
    Notification.objects.create(
        user=report.user,
        report=report,
        notif_type='admin_action',
        message=message,
    )


def parse_datetime_local(value):
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, '%Y-%m-%dT%H:%M')
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def log_bulletin_history(bulletin, action, changed_by=None):
    if not bulletin:
        return

    BulletinPostHistory.objects.create(
        bulletin=bulletin if bulletin.pk else None,
        barangay=bulletin.barangay,
        action=action,
        changed_by=changed_by,
        title_snapshot=bulletin.title,
        category_snapshot=bulletin.category,
        priority_snapshot=bulletin.priority,
        content_snapshot=bulletin.content,
        is_pinned_snapshot=bulletin.is_pinned,
        expires_at_snapshot=bulletin.expires_at,
        attachment_name=bulletin.attachment.name if bulletin.attachment else '',
    )
    try:
        AuditLog.objects.create(
            actor=changed_by,
            action=('create_bulletin' if action == 'created' else 'update_bulletin') if action in ('created', 'updated') else action,
            target_type='BulletinPost',
            target_id=bulletin.id if bulletin.pk else None,
            target_repr=bulletin.title,
            barangay=bulletin.barangay,
            reason='',
            data={
                'priority': bulletin.priority,
                'is_pinned': bulletin.is_pinned,
            }
        )
    except Exception:
        pass


def send_urgent_bulletin_email(bulletin, recipients):
    if not recipients:
        return
    subject = f"[URGENT] {bulletin.title}"
    body = (
        f"Urgent barangay update from {bulletin.barangay.name}\n\n"
        f"Category: {bulletin.get_category_display()}\n"
        f"Priority: {bulletin.get_priority_display()}\n\n"
        f"{bulletin.content}\n\n"
        "Please log in to i-Sumbong for full details and updates."
    )
    send_mail(subject, body, None, recipients, fail_silently=True)


def send_urgent_bulletin_sms(bulletin, phone_numbers):
    if not phone_numbers:
        return

    provider = getattr(settings, 'SMS_PROVIDER', '').lower()
    if provider != 'twilio':
        return

    account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    from_number = getattr(settings, 'TWILIO_FROM_NUMBER', '')
    if not account_sid or not auth_token or not from_number:
        return

    message = f"[URGENT] {bulletin.title} - {bulletin.barangay.name}. {bulletin.content}"
    base_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    auth_value = base64.b64encode(f"{account_sid}:{auth_token}".encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f"Basic {auth_value}",
        'Content-Type': 'application/x-www-form-urlencoded',
    }

    for raw_number in phone_numbers:
        to_number = raw_number.strip()
        if not to_number:
            continue
        payload = urllib.parse.urlencode({
            'From': from_number,
            'To': to_number,
            'Body': message,
        }).encode('utf-8')
        request = urllib.request.Request(base_url, data=payload, headers=headers, method='POST')
        try:
            urllib.request.urlopen(request, timeout=10)
        except Exception:
            continue


@never_cache
def login_view(request):
    if request.user.is_authenticated and request.method != 'POST':
        if request.user.is_staff:
            return redirect('admin_dashboard')
        if is_user_approved(request.user):
            return redirect('home')
        return show_waiting_approval(request)

    if request.method == 'POST':
        if request.user.is_authenticated:
            logout(request)
        form = _login_form(
            request,
            data=request.POST,
            use_prefix=_post_uses_prefix(request, LOGIN_FORM_PREFIX),
        )
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                if user.is_staff:
                    return redirect('admin_dashboard')
                if is_user_approved(user):
                    return redirect('home')
                return show_waiting_approval(request)
        register_form = _register_form()
    else:
        form = _login_form(request)
        register_form = _register_form()

    return render(
        request,
        'registration/login.html',
        {
            'form': form,
            'register_form': register_form,
            'auth_mode': 'login',
        },
    )


@never_cache
def register(request):
    if request.method == 'POST':
        if request.user.is_authenticated:
            logout(request)
        form = _register_form(
            request.POST,
            request.FILES,
            use_prefix=_post_uses_prefix(request, REGISTER_FORM_PREFIX),
        )
        if form.is_valid():
            user = form.save()
            CommunityProfile.objects.create(
                user=user,
                address=form.cleaned_data['address'],
                phone_number=form.cleaned_data.get('phone_number', '').strip(),
                barangay=form.cleaned_data['barangay'],
                proof_of_residency=form.cleaned_data['proof_of_residency'],
                status=CommunityProfile.STATUS_PENDING,
            )
            messages.success(request, 'Registration submitted. Please wait for barangay admin approval.')
            return redirect('login')
        login_form = _login_form(request)
    else:
        form = _register_form()
        login_form = _login_form(request)
    return render(
        request,
        'base/register.html',
        {
            'form': form,
            'login_form': login_form,
            'auth_mode': 'register',
        },
    )


def terms(request):
    return render(request, 'base/terms.html')


@never_cache
@login_required
def home(request):
    if request.user.is_staff:
        return redirect('admin_dashboard')

    profile = CommunityProfile.objects.filter(user=request.user).select_related('barangay').first()
    if profile and profile.status != CommunityProfile.STATUS_APPROVED:
        return show_waiting_approval(request, profile)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'submit_report':
            title = request.POST.get('title', '').strip()
            location = request.POST.get('location', '').strip()
            priority = request.POST.get('priority', 'low')
            description = request.POST.get('description', '').strip()
            # support multiple photos from community users
            photo = request.FILES.get('photo')
            photos = request.FILES.getlist('photos') if request.FILES else []

            # optional geolocation fields (sent from client if available)
            latitude_raw = request.POST.get('latitude') or None
            longitude_raw = request.POST.get('longitude') or None
            try:
                lat_val = float(latitude_raw) if latitude_raw else None
            except Exception:
                lat_val = None
            try:
                lng_val = float(longitude_raw) if longitude_raw else None
            except Exception:
                lng_val = None

            if title and location and description:
                # server-side validate uploaded images
                files_to_check = []
                if photo:
                    files_to_check.append(photo)
                files_to_check.extend(photos or [])
                ok, err = _validate_images_list(files_to_check)
                if not ok:
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'status': 'error', 'message': err}, status=400)
                    messages.error(request, err)
                    return redirect(reverse('home') + '?page=submit')

                report = Report.objects.create(
                    user=request.user,
                    title=title,
                    location=location,
                    priority=priority,
                    description=description,
                    photo=photo,
                    latitude=lat_val,
                    longitude=lng_val,
                )
                # save additional images
                for f in photos:
                    try:
                        ReportImage.objects.create(report=report, image=f)
                    except Exception:
                        pass
                # If request is AJAX, return JSON (no full-page redirect)
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'ok', 'message': 'Your report has been submitted successfully!'})
                messages.success(request, 'Your report has been submitted successfully!')
                return redirect(reverse('home') + '?page=home')
            messages.error(request, 'Please fill in all required fields.')

        elif action == 'edit_report':
            report_id = request.POST.get('report_id')
            rid = _safe_int(report_id)
            if rid is None:
                messages.error(request, 'Invalid report id.')
                return redirect(reverse('home') + '?page=my-reports')
            try:
                report = Report.objects.get(id=rid, user=request.user)
                report.title = request.POST.get('title', report.title).strip()
                report.location = request.POST.get('location', report.location).strip()
                report.priority = request.POST.get('priority', report.priority)
                report.description = request.POST.get('description', report.description).strip()
                report.save()
                messages.success(request, 'Report updated successfully!')
            except Report.DoesNotExist:
                messages.error(request, 'Report not found.')
            return redirect(reverse('home') + '?page=my-reports')

        elif action == 'delete_report':
            report_id = request.POST.get('report_id')
            rid = _safe_int(report_id)
            if rid is None:
                messages.error(request, 'Invalid report id.')
                return redirect(reverse('home') + '?page=my-reports')
            try:
                report = Report.objects.get(id=rid, user=request.user)
                report.delete()
                messages.success(request, 'Report deleted successfully.')
            except Report.DoesNotExist:
                messages.error(request, 'Report not found.')
            return redirect(reverse('home') + '?page=my-reports')

    # Only show reports created by the logged-in user and not deleted
    my_reports = (
        Report.objects.filter(user=request.user, is_deleted=False)
        .select_related('user')
        .prefetch_related('images')
        .order_by('-created_at')
    )
    # scope community feed to user's barangay when available
    if profile and getattr(profile, 'barangay', None):
        community_reports = (
            Report.objects.filter(
                user__community_profile__barangay=profile.barangay,
                is_deleted=False,
            )
            .exclude(user=request.user)
            .select_related('user')
            .prefetch_related('images')
            .order_by('-created_at')
        )
    else:
        community_reports = Report.objects.none()
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
    unread_count = notifications.filter(is_read=False).count()

    bulletins = []
    urgent_bulletins = []
    if profile and profile.status == CommunityProfile.STATUS_APPROVED:
        bulletin_scope = BulletinPost.objects.filter(barangay=profile.barangay).select_related('barangay', 'created_by')
        active_bulletins = bulletin_scope.filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
        ).order_by('-is_pinned', '-created_at')
        bulletins = list(active_bulletins)
        urgent_bulletins = [b for b in bulletins if b.priority == 'urgent']

        seen_ids = set(
            BulletinPostView.objects.filter(user=request.user, post__in=bulletins)
            .values_list('post_id', flat=True)
        )
        new_views = [
            BulletinPostView(user=request.user, post=post)
            for post in bulletins
            if post.id not in seen_ids
        ]
        if new_views:
            BulletinPostView.objects.bulk_create(new_views, ignore_conflicts=True)

    # expose last bulk action for undo banner
    last_bulk_action = request.session.get('last_bulk_action') if hasattr(request, 'session') else None
    # initial page selection: allowlist from query param (used to render correct active tab server-side)
    allowed_pages = {'home', 'submit', 'my-reports', 'community', 'notifications', 'profile', 'settings'}
    initial_page = request.GET.get('page', 'home')
    if initial_page not in allowed_pages:
        initial_page = 'home'

    context = {
        'initial_page': initial_page,
        'profile': profile,
        'my_reports': my_reports,
        'community_reports': community_reports,
        'community_reports_count': community_reports.count(),
        'my_reports_count': my_reports.count(),
        'pending_count': my_reports.filter(status='pending').count(),
        'inprogress_count': my_reports.filter(status='in_progress').count(),
        'resolved_count': my_reports.filter(status='resolved').count(),
        'notifications': notifications,
        'unread_count': unread_count,
        'bulletins': bulletins,
        'urgent_bulletins': urgent_bulletins,
        'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
    }
    return render(request, 'base/home.html', context)


@never_cache
@login_required
def report_detail(request, report_id):
    try:
        report = (
            Report.objects.select_related('user', 'user__community_profile')
            .prefetch_related('images', 'actions')
            .get(id=report_id, is_deleted=False)
        )
    except Report.DoesNotExist:
        messages.error(request, 'Report not found.')
        return redirect('home')

    can_manage_thread = (
        request.user == report.user
        or request.user.is_staff
        or _user_administers_report_barangay(request.user, report)
    )
    allowed = can_manage_thread or _user_shares_report_barangay(request.user, report)

    if not allowed:
        messages.error(request, 'You are not authorized to view this report.')
        return redirect('home')

    actions = report.actions.all().order_by('-created_at')
    images = report.images.all()
    return render(
        request,
        'base/report_detail.html',
        {
            'report': report,
            'actions': actions,
            'images': images,
            'can_comment': allowed,
            'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
        },
    )


@never_cache
@login_required
def my_reports_fragment(request):
    """Return an HTML fragment with the current user's reports (used by AJAX)."""
    my_reports = (
        Report.objects.filter(user=request.user, is_deleted=False)
        .select_related('user')
        .prefetch_related('images')
        .order_by('-created_at')
    )
    try:
        logger.info('my_reports_fragment called user=%s id=%s count=%s', getattr(request.user, 'username', None), getattr(request.user, 'id', None), my_reports.count())
    except Exception:
        pass
    return render(request, 'base/partials/my_reports_list.html', {'my_reports': my_reports})


@never_cache
@login_required
def post_report_comment(request, report_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    message = (request.POST.get('message') or '').strip()
    parent_id = _safe_int(request.POST.get('parent_id'))
    try:
        report = Report.objects.get(id=report_id, is_deleted=False)
    except Report.DoesNotExist:
        return JsonResponse({'error': 'not_found'}, status=404)

    # Anyone who can view the barangay report can join the conversation.
    allowed = (
        request.user == report.user
        or request.user.is_staff
        or _user_administers_report_barangay(request.user, report)
        or _user_shares_report_barangay(request.user, report)
    )

    if not allowed:
        return JsonResponse({'error': 'forbidden'}, status=403)

    if not message:
        return JsonResponse({'error': 'empty_message'}, status=400)

    parent = None
    if parent_id:
        parent = ReportComment.objects.filter(id=parent_id, report=report).first()

    comment = ReportComment.objects.create(report=report, parent=parent, user=request.user, message=message)

    if request.user != report.user:
        Notification.objects.create(
            user=report.user,
            report=report,
            notif_type='admin_action',
            message=f'{request.user.username} commented on your report "{report.title}": {message[:200]}',
            delivery_status='pending'
        )

    return JsonResponse({'status': 'ok', 'comment': {
        'id': comment.id,
        'user': comment.user.username,
        'message': comment.message,
        'parent': comment.parent.id if comment.parent else None,
        'created_at': comment.created_at.isoformat(),
    }})


@never_cache
@login_required
def edit_profile(request):
    profile = CommunityProfile.objects.filter(user=request.user).first()
    if not profile:
        messages.error(request, 'Community profile not found.')
        return redirect('home')

    if request.method == 'POST':
        address = request.POST.get('address', '').strip()
        phone = request.POST.get('phone_number', '').strip()
        avatar = request.FILES.get('avatar')
        proof = request.FILES.get('proof_of_residency')

        # basic validation
        if avatar:
            ok, err = _validate_image_file(avatar)
            if not ok:
                messages.error(request, err)
                return redirect(reverse('edit_profile'))
            profile.avatar = avatar
        if proof:
            ok, err = _validate_image_file(proof)
            if not ok:
                messages.error(request, err)
                return redirect(reverse('edit_profile'))
            profile.proof_of_residency = proof

        if address:
            profile.address = address
        profile.phone_number = phone
        profile.save()
        messages.success(request, 'Profile updated.')
        return redirect('home')

    return render(request, 'base/profile_edit.html', {'profile': profile, 'barangays': Barangay.objects.all().order_by('name')})


@never_cache
@login_required
def resubmit_proof(request):
    profile = CommunityProfile.objects.filter(user=request.user).first()
    if not profile:
        messages.error(request, 'Community profile not found.')
        return redirect('login')

    if profile.status != CommunityProfile.STATUS_REJECTED:
        messages.info(request, 'Resubmission is only available for rejected accounts.')
        return show_waiting_approval(request, profile)

    if request.method != 'POST':
        return show_waiting_approval(request, profile)

    address = request.POST.get('address', '').strip()
    barangay_id = request.POST.get('barangay', '').strip()
    proof = request.FILES.get('proof_of_residency')

    if not address or not barangay_id or not proof:
        messages.error(request, 'Please complete address, barangay, and proof of residency.')
        return show_waiting_approval(request, profile)

    bid = _safe_int(barangay_id)
    if bid is None:
        messages.error(request, 'Selected barangay is invalid.')
        return show_waiting_approval(request, profile)
    try:
        barangay = Barangay.objects.get(id=bid)
    except Barangay.DoesNotExist:
        messages.error(request, 'Selected barangay is invalid.')
        return show_waiting_approval(request, profile)

    profile.address = address
    profile.barangay = barangay
    profile.proof_of_residency = proof
    profile.status = CommunityProfile.STATUS_PENDING
    profile.reviewed_by = None
    profile.reviewed_at = None
    profile.review_notes = ''
    profile.save()

    messages.success(request, 'Your proof was resubmitted. Please wait for barangay admin review.')
    return show_waiting_approval(request, profile)


@never_cache
@login_required
def mark_notifications_read(request):
    if request.method == 'POST':
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)


@never_cache
@login_required
def notification_detail(request, notification_id):
    try:
        notification = Notification.objects.select_related('report').get(
            id=notification_id,
            user=request.user,
        )
    except Notification.DoesNotExist:
        messages.error(request, 'Notification not found.')
        return redirect(reverse('home') + '?page=notifications')

    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=['is_read'])

    return redirect('report_detail', report_id=notification.report_id)


@never_cache
@login_required
def admin_dashboard(request):
    if not request.user.is_staff:
        return redirect('home')

    admin_profile = BarangayAdminProfile.objects.filter(user=request.user).select_related('barangay').first()
    if request.user.is_superuser and not admin_profile:
        scoped_profiles = CommunityProfile.objects.select_related('user', 'barangay')
        reports_scope = Report.objects.all().select_related('user')
        admin_barangay_name = 'All Barangays'
        bulletin_scope = BulletinPost.objects.select_related('barangay', 'created_by')
        admin_barangay = None
    elif admin_profile:
        scoped_profiles = CommunityProfile.objects.filter(barangay=admin_profile.barangay).select_related('user', 'barangay')
        reports_scope = Report.objects.filter(user__community_profile__barangay=admin_profile.barangay).select_related('user')
        admin_barangay_name = admin_profile.barangay.name
        bulletin_scope = BulletinPost.objects.filter(barangay=admin_profile.barangay).select_related('barangay', 'created_by')
        admin_barangay = admin_profile.barangay
    else:
        scoped_profiles = CommunityProfile.objects.none()
        reports_scope = Report.objects.none()
        admin_barangay_name = None
        bulletin_scope = BulletinPost.objects.none()
        admin_barangay = None
        messages.warning(request, 'No barangay is assigned to your admin account yet.')

    # Admin users list for assignments
    admin_users = User.objects.filter(is_staff=True).order_by('username')
    # Users that can be promoted to barangay admin (non-staff) - scoped to admin's barangay when applicable
    if admin_profile and admin_profile.barangay:
        promotable_users = User.objects.filter(is_staff=False, community_profile__barangay=admin_profile.barangay).order_by('username')
        barangay_admins = BarangayAdminProfile.objects.filter(barangay=admin_profile.barangay).select_related('user')
    else:
        promotable_users = User.objects.filter(is_staff=False).order_by('username')
        barangay_admins = BarangayAdminProfile.objects.all().select_related('user', 'barangay')
    # expose last actions for undo banners
    last_bulk_action = request.session.get('last_bulk_action') if hasattr(request, 'session') else None
    last_deleted_report = request.session.get('last_deleted_report') if hasattr(request, 'session') else None

    # Handle status update
    if request.method == 'POST':
        action = request.POST.get('action')
        report_id = request.POST.get('report_id')
        profile_id = request.POST.get('profile_id')
        selected_profile_ids = request.POST.getlist('profile_ids')

        if action == 'create_bulletin':
            title = request.POST.get('title', '').strip()
            category = request.POST.get('category', '').strip()
            content = request.POST.get('content', '').strip()
            priority = request.POST.get('priority', 'normal')
            is_pinned = request.POST.get('is_pinned') == 'on'
            expires_at = parse_datetime_local(request.POST.get('expires_at', '').strip())
            # support single legacy attachment or multiple images
            attachment = request.FILES.get('attachment')
            attachments = request.FILES.getlist('attachments') if request.FILES else []

            selected_barangay = admin_barangay
            if not selected_barangay and request.user.is_superuser:
                barangay_id = request.POST.get('barangay_id')
                if barangay_id:
                    selected_barangay = Barangay.objects.filter(id=barangay_id).first()

            if not selected_barangay:
                messages.error(request, 'Please select a barangay for this bulletin post.')
                return redirect(reverse('admin_dashboard'))

            valid_categories = {choice[0] for choice in BulletinPost.CATEGORY_CHOICES}
            valid_priorities = {choice[0] for choice in BulletinPost.PRIORITY_CHOICES}

            if not title or not content or category not in valid_categories:
                messages.error(request, 'Please complete title, category, and content for the bulletin post.')
                return redirect(reverse('admin_dashboard'))

            if priority not in valid_priorities:
                priority = 'normal'

            if request.POST.get('expires_at') and not expires_at:
                messages.error(request, 'Expiration date is invalid. Please use the date picker.')
                return redirect(reverse('admin_dashboard'))

            # validate attachments/images
            if attachment:
                ok, err = _validate_image_file(attachment)
                if not ok:
                    messages.error(request, err)
                    return redirect(reverse('admin_dashboard'))
            if attachments:
                ok, err = _validate_images_list(attachments)
                if not ok:
                    messages.error(request, err)
                    return redirect(reverse('admin_dashboard'))

            bulletin = BulletinPost.objects.create(
                barangay=selected_barangay,
                title=title,
                category=category,
                content=content,
                priority=priority,
                is_pinned=is_pinned,
                expires_at=expires_at,
                attachment=attachment,
                created_by=request.user,
            )

            # save additional images if any
            from .models import BulletinImage
            for f in attachments:
                try:
                    BulletinImage.objects.create(post=bulletin, image=f)
                except Exception:
                    pass

            log_bulletin_history(bulletin, 'created', request.user)

            if bulletin.priority == 'urgent':
                recipient_emails = list(
                    CommunityProfile.objects.filter(
                        barangay=selected_barangay,
                        status=CommunityProfile.STATUS_APPROVED,
                        user__email__isnull=False,
                    ).exclude(user__email='').values_list('user__email', flat=True)
                )
                recipient_numbers = list(
                    CommunityProfile.objects.filter(
                        barangay=selected_barangay,
                        status=CommunityProfile.STATUS_APPROVED,
                    ).exclude(phone_number='').values_list('phone_number', flat=True)
                )
                send_urgent_bulletin_email(bulletin, recipient_emails)
                send_urgent_bulletin_sms(bulletin, recipient_numbers)

            # if AJAX, return JSON for client-side UX
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'ok', 'message': 'Bulletin post published successfully.', 'bulletin_id': bulletin.id})

            messages.success(request, 'Bulletin post published successfully.')
            return redirect(reverse('admin_dashboard'))

        if action in ['bulk_approve_users', 'bulk_reject_users']:
            if not selected_profile_ids:
                messages.error(request, 'Select at least one community user.')
                return redirect(reverse('admin_dashboard'))

            review_notes = request.POST.get('review_notes', '').strip()
            if action == 'bulk_reject_users' and not review_notes:
                messages.error(request, 'Reject reason is required for bulk rejection.')
                return redirect(reverse('admin_dashboard'))

            profiles = list(scoped_profiles.filter(id__in=selected_profile_ids).select_related('user', 'barangay'))
            updated_count = 0
            for member_profile in profiles:
                member_profile.status = (
                    CommunityProfile.STATUS_APPROVED
                    if action == 'bulk_approve_users'
                    else CommunityProfile.STATUS_REJECTED
                )
                member_profile.reviewed_by = request.user
                member_profile.reviewed_at = timezone.now()
                member_profile.review_notes = '' if action == 'bulk_approve_users' else review_notes
                member_profile.save()
                try:
                    AuditLog.objects.create(
                        actor=request.user,
                        action=('bulk_approve_users' if action == 'bulk_approve_users' else 'bulk_reject_users'),
                        target_type='CommunityProfile',
                        target_id=member_profile.id,
                        target_repr=member_profile.user.username,
                        barangay=member_profile.barangay,
                        reason=member_profile.review_notes or '',
                        data={'status': member_profile.status}
                    )
                except Exception:
                    pass
                send_membership_decision_email(member_profile)
                updated_count += 1

            # store last bulk action in session for quick undo
            try:
                request.session['last_bulk_action'] = {
                    'ids': selected_profile_ids,
                    'action': action,
                    'by': request.user.id,
                    'count': updated_count,
                    'timestamp': timezone.now().isoformat(),
                }
                request.session.modified = True
            except Exception:
                pass

            verb = 'approved' if action == 'bulk_approve_users' else 'rejected'
            messages.success(request, f'{updated_count} community user(s) {verb} successfully. You can undo this action for a short time.')
            return redirect(reverse('admin_dashboard'))

        if action == 'assign_report':
            rid = request.POST.get('report_id')
            assignee_id = request.POST.get('assignee_id')
            rid_int = _safe_int(rid)
            if rid_int is None:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': 'Invalid report id.'}, status=400)
                messages.error(request, 'Invalid report id.')
                return redirect(reverse('admin_dashboard'))
            try:
                report = reports_scope.get(id=rid_int)
                assignee = resolve_user_by_id_or_username(assignee_id)
                if assignee and not assignee.is_staff:
                    assignee = None
                report.assigned_to = assignee
                report.save()
                try:
                    AuditLog.objects.create(
                        actor=request.user,
                        action='report_action',
                        target_type='Report',
                        target_id=report.id,
                        target_repr=report.title,
                        barangay=report.user.community_profile.barangay if hasattr(report.user, 'community_profile') else None,
                        reason=f'Assigned to {assignee.username if assignee else "(unassigned)"}',
                        data={'assignee': assignee.username if assignee else ''}
                    )
                except Exception:
                    pass
                # AJAX response
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'ok', 'message': 'Report assignment updated.', 'report_id': report.id, 'assignee': assignee.username if assignee else '', 'assignee_id': assignee.id if assignee else None})
                messages.success(request, 'Report assignment updated.')
            except Report.DoesNotExist:
                messages.error(request, 'Report not found.')
            return redirect(reverse('admin_dashboard'))

        if action == 'promote_to_barangay_admin':
            target_user_id = request.POST.get('user_id')
            barangay_id = request.POST.get('barangay_id')
            if not target_user_id or not barangay_id:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': 'Select a user and a barangay to promote.'}, status=400)
                messages.error(request, 'Select a user and a barangay to promote.')
                return redirect(reverse('admin_dashboard'))
            try:
                target_user = resolve_user_by_id_or_username(target_user_id)
                if not target_user:
                    raise User.DoesNotExist()
                bid = _safe_int(barangay_id)
                if bid is None:
                    raise Barangay.DoesNotExist()
                barangay = Barangay.objects.get(id=bid)
                # mark user as staff and create/update BarangayAdminProfile
                target_user.is_staff = True
                target_user.save()
                BarangayAdminProfile.objects.update_or_create(
                    user=target_user,
                    defaults={'barangay': barangay}
                )
                try:
                    AuditLog.objects.create(
                        actor=request.user,
                        action='promote_admin',
                        target_type='User',
                        target_id=target_user.id,
                        target_repr=target_user.username,
                        barangay=barangay,
                        reason='Promoted to barangay admin',
                        data={}
                    )
                except Exception:
                    pass
                # notify promoted user via email (best-effort)
                try:
                    if target_user.email:
                        send_mail(
                            f'You have been promoted to Barangay Admin',
                            f'Hello {target_user.username},\n\nYou have been promoted to Barangay Admin for {barangay.name}. You can now access admin tools in i-Sumbong.\n\nRegards,\ni-Sumbong Team',
                            None,
                            [target_user.email],
                            fail_silently=True,
                        )
                except Exception:
                    pass
                # AJAX response
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'ok', 'message': f'{target_user.username} promoted to barangay admin for {barangay.name}.', 'user_id': target_user.id})

                messages.success(request, f'{target_user.username} promoted to barangay admin for {barangay.name}.')
            except User.DoesNotExist:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': 'User not found.'}, status=404)
                messages.error(request, 'User not found.')
            except Barangay.DoesNotExist:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': 'Barangay not found.'}, status=404)
                messages.error(request, 'Barangay not found.')
            return redirect(reverse('admin_dashboard'))
        if action == 'demote_barangay_admin':
            target_user_id = request.POST.get('user_id')
            if not target_user_id:
                messages.error(request, 'Select an admin to demote.')
                return redirect(reverse('admin_dashboard'))
            try:
                target_user = resolve_user_by_id_or_username(target_user_id)
                if not target_user:
                    raise User.DoesNotExist()
                # remove BarangayAdminProfile if exists
                BarangayAdminProfile.objects.filter(user=target_user).delete()
                target_user.is_staff = False
                target_user.save()
                try:
                    AuditLog.objects.create(
                        actor=request.user,
                        action='demote_admin',
                        target_type='User',
                        target_id=target_user.id,
                        target_repr=target_user.username,
                        barangay=None,
                        reason='Demoted from barangay admin',
                        data={}
                    )
                except Exception:
                    pass
                # AJAX support
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'ok', 'message': f'{target_user.username} has been demoted from barangay admin.', 'user_id': target_user.id})
                messages.success(request, f'{target_user.username} has been demoted from barangay admin.')
            except User.DoesNotExist:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': 'User not found.'}, status=404)
                messages.error(request, 'User not found.')
            return redirect(reverse('admin_dashboard'))

        if action in ['toggle_bulletin_pin', 'delete_bulletin']:
            bulletin_id = request.POST.get('bulletin_id')
            bid = _safe_int(bulletin_id)
            if bid is None:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': 'Invalid bulletin id.'}, status=400)
                return redirect(reverse('admin_dashboard'))
            try:
                bulletin = bulletin_scope.get(id=bid)
                if action == 'toggle_bulletin_pin':
                    bulletin.is_pinned = not bulletin.is_pinned
                    bulletin.save()
                    log_bulletin_history(bulletin, 'pin_toggled', request.user)
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'status': 'ok', 'message': 'Bulletin pin status updated.', 'is_pinned': bulletin.is_pinned, 'bulletin_id': bulletin.id})
                    messages.success(request, 'Bulletin pin status updated.')
                else:
                    log_bulletin_history(bulletin, 'deleted', request.user)
                    bulletin.delete()
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'status': 'ok', 'message': 'Bulletin post deleted.', 'bulletin_id': bulletin.id})
                    messages.success(request, 'Bulletin post deleted.')
            except BulletinPost.DoesNotExist:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': 'Bulletin post not found.'}, status=404)
                messages.error(request, 'Bulletin post not found.')
            return redirect(reverse('admin_dashboard'))

        if action == 'edit_bulletin':
            bulletin_id = request.POST.get('bulletin_id')
            bid = _safe_int(bulletin_id)
            if bid is None:
                return redirect(reverse('admin_dashboard'))
            try:
                bulletin = bulletin_scope.get(id=bid)
            except BulletinPost.DoesNotExist:
                messages.error(request, 'Bulletin post not found.')
                return redirect(reverse('admin_dashboard'))

            title = request.POST.get('title', '').strip()
            category = request.POST.get('category', '').strip()
            content = request.POST.get('content', '').strip()
            priority = request.POST.get('priority', 'normal')
            is_pinned = request.POST.get('is_pinned') == 'on'
            expires_at = parse_datetime_local(request.POST.get('expires_at', '').strip())
            attachment = request.FILES.get('attachment')
            remove_attachment = request.POST.get('remove_attachment') == 'on'

            valid_categories = {choice[0] for choice in BulletinPost.CATEGORY_CHOICES}
            valid_priorities = {choice[0] for choice in BulletinPost.PRIORITY_CHOICES}

            if not title or not content or category not in valid_categories:
                messages.error(request, 'Please complete title, category, and content for the bulletin post.')
                return redirect(reverse('admin_dashboard'))

            if priority not in valid_priorities:
                priority = 'normal'

            if request.POST.get('expires_at') and not expires_at:
                messages.error(request, 'Expiration date is invalid. Please use the date picker.')
                return redirect(reverse('admin_dashboard'))

            was_urgent = bulletin.priority == 'urgent'
            bulletin.title = title
            bulletin.category = category
            bulletin.content = content
            bulletin.priority = priority
            bulletin.is_pinned = is_pinned
            bulletin.expires_at = expires_at

            if remove_attachment and bulletin.attachment:
                bulletin.attachment.delete(save=False)
                bulletin.attachment = None
            if attachment:
                ok, err = _validate_image_file(attachment)
                if not ok:
                    messages.error(request, err)
                    return redirect(reverse('admin_dashboard'))
                bulletin.attachment = attachment

            bulletin.save()

            log_bulletin_history(bulletin, 'updated', request.user)

            if bulletin.priority == 'urgent' and not was_urgent:
                recipient_emails = list(
                    CommunityProfile.objects.filter(
                        barangay=bulletin.barangay,
                        status=CommunityProfile.STATUS_APPROVED,
                        user__email__isnull=False,
                    ).exclude(user__email='').values_list('user__email', flat=True)
                )
                recipient_numbers = list(
                    CommunityProfile.objects.filter(
                        barangay=bulletin.barangay,
                        status=CommunityProfile.STATUS_APPROVED,
                    ).exclude(phone_number='').values_list('phone_number', flat=True)
                )
                send_urgent_bulletin_email(bulletin, recipient_emails)
                send_urgent_bulletin_sms(bulletin, recipient_numbers)

            messages.success(request, 'Bulletin post updated successfully.')
            return redirect(reverse('admin_dashboard'))

        if action == 'resend_urgent_bulk':
            bulletin_ids = request.POST.getlist('bulletin_ids')
            if not bulletin_ids:
                messages.error(request, 'Select at least one bulletin to resend.')
                return redirect(reverse('admin_dashboard'))

            resend_count = 0
            skipped_count = 0
            for bulletin in bulletin_scope.filter(id__in=bulletin_ids):
                if bulletin.priority != 'urgent':
                    skipped_count += 1
                    continue

                recipient_emails = list(
                    CommunityProfile.objects.filter(
                        barangay=bulletin.barangay,
                        status=CommunityProfile.STATUS_APPROVED,
                        user__email__isnull=False,
                    ).exclude(user__email='').values_list('user__email', flat=True)
                )
                recipient_numbers = list(
                    CommunityProfile.objects.filter(
                        barangay=bulletin.barangay,
                        status=CommunityProfile.STATUS_APPROVED,
                    ).exclude(phone_number='').values_list('phone_number', flat=True)
                )

                send_urgent_bulletin_email(bulletin, recipient_emails)
                send_urgent_bulletin_sms(bulletin, recipient_numbers)
                log_bulletin_history(bulletin, 'urgent_resent', request.user)
                resend_count += 1

            if resend_count:
                messages.success(request, f'Resent {resend_count} urgent bulletin update(s).')
            if skipped_count:
                messages.info(request, f'Skipped {skipped_count} non-urgent bulletin(s).')
            return redirect(reverse('admin_dashboard'))

        if action in ['approve_user', 'reject_user'] and profile_id:
            pid = _safe_int(profile_id)
            if pid is None:
                messages.error(request, 'Invalid profile id.')
                return redirect(reverse('admin_dashboard'))
            try:
                member_profile = scoped_profiles.get(id=pid)
                review_notes = request.POST.get('review_notes', '').strip()

                if action == 'reject_user' and not review_notes:
                    messages.error(request, 'Reject reason is required.')
                    return redirect(reverse('admin_dashboard'))

                member_profile.status = (
                    CommunityProfile.STATUS_APPROVED
                    if action == 'approve_user'
                    else CommunityProfile.STATUS_REJECTED
                )
                member_profile.reviewed_by = request.user
                member_profile.reviewed_at = timezone.now()
                member_profile.review_notes = review_notes
                member_profile.save()
                try:
                    AuditLog.objects.create(
                        actor=request.user,
                        action=('approve_user' if action == 'approve_user' else 'reject_user'),
                        target_type='CommunityProfile',
                        target_id=member_profile.id,
                        target_repr=member_profile.user.username,
                        barangay=member_profile.barangay,
                        reason=member_profile.review_notes or '',
                        data={'status': member_profile.status}
                    )
                except Exception:
                    pass
                send_membership_decision_email(member_profile)

                verb = 'approved' if action == 'approve_user' else 'rejected'
                # AJAX response
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'ok', 'message': f'{member_profile.user.username} was {verb} successfully.', 'profile_id': member_profile.id, 'user': member_profile.user.username, 'new_status': member_profile.status})
                messages.success(request, f'{member_profile.user.username} was {verb} successfully.')
            except CommunityProfile.DoesNotExist:
                messages.error(request, 'Community member request not found.')
            return redirect(reverse('admin_dashboard'))

        if action == 'undo_delete_report':
            last = request.session.pop('last_deleted_report', None)
            request.session.modified = True
            if not last:
                messages.error(request, 'No recent deletion to undo.')
                return redirect(reverse('admin_dashboard'))
            try:
                rep = Report.objects.filter(id=last.get('id')).first()
                if rep:
                    rep.is_deleted = False
                    rep.deleted_at = None
                    rep.save()
                    try:
                        AuditLog.objects.create(
                            actor=request.user,
                            action='undo_bulk',
                            target_type='Report',
                            target_id=rep.id,
                            target_repr=rep.title,
                            reason='Undo delete',
                            data={}
                        )
                    except Exception:
                        pass
                    messages.success(request, 'Report restore successful.')
                else:
                    messages.error(request, 'Report not found to restore.')
            except Exception:
                messages.error(request, 'Failed to restore report.')
            return redirect(reverse('admin_dashboard'))

        if action == 'undo_last_bulk':
            last = request.session.pop('last_bulk_action', None)
            request.session.modified = True
            if not last or not last.get('ids'):
                messages.error(request, 'No recent bulk action to undo.')
                return redirect(reverse('admin_dashboard'))

            undone = 0
            ids = last.get('ids', [])
            for pid in ids:
                try:
                    prof = scoped_profiles.filter(id=pid).first()
                    if not prof:
                        continue
                    # revert to pending and clear reviewer info
                    prof.status = CommunityProfile.STATUS_PENDING
                    prof.reviewed_by = None
                    prof.reviewed_at = None
                    prof.review_notes = ''
                    prof.save()
                    try:
                        AuditLog.objects.create(
                            actor=request.user,
                            action='undo_bulk',
                            target_type='CommunityProfile',
                            target_id=prof.id,
                            target_repr=prof.user.username,
                            barangay=prof.barangay,
                            reason=f"Undo of {last.get('action')}",
                            data={}
                        )
                    except Exception:
                        pass
                    undone += 1
                except Exception:
                    continue

            if undone:
                messages.success(request, f'Undid bulk action for {undone} user(s).')
            else:
                messages.info(request, 'Nothing was undone.')

            return redirect(reverse('admin_dashboard'))

        if action == 'update_status' and report_id:
            report_id_int = _safe_int(report_id)
            if report_id_int is None:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': 'Invalid report id.'}, status=400)
                messages.error(request, 'Invalid report id.')
                return redirect(reverse('admin_dashboard'))
            try:
                report = reports_scope.get(id=report_id_int)
                new_status = request.POST.get('status')
                if new_status in ['pending', 'in_progress', 'resolved']:
                    report.status = new_status
                    report.save()
                    try:
                        AuditLog.objects.create(
                            actor=request.user,
                            action='update_status',
                            target_type='Report',
                            target_id=report.id,
                            target_repr=report.title,
                            barangay=report.user.community_profile.barangay if hasattr(report.user, 'community_profile') else None,
                            reason='',
                            data={'status': report.status}
                        )
                    except Exception:
                        pass
                    # Return JSON when requested via AJAX
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'status': 'ok', 'message': f'Status updated to {report.get_status_display()}.', 'new_status': report.status, 'report_id': report.id})
                    messages.success(request, f'Status updated to {report.get_status_display()}.')
            except Report.DoesNotExist:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': 'Report not found.'}, status=404)
                messages.error(request, 'Report not found.')

        elif action == 'add_report_action' and report_id:
            report_id_int = _safe_int(report_id)
            if report_id_int is None:
                messages.error(request, 'Invalid report id.')
                return redirect(reverse('admin_dashboard'))
            try:
                report = reports_scope.get(id=report_id_int)
            except Report.DoesNotExist:
                messages.error(request, 'Report not found.')
                return redirect(reverse('admin_dashboard'))

            action_value = request.POST.get('report_action', '').strip()
            action_note = request.POST.get('action_note', '').strip()
            valid_actions = {choice[0] for choice in ReportAction.ACTION_CHOICES}
            if action_value not in valid_actions:
                messages.error(request, 'Please select a valid admin action.')
                return redirect(reverse('admin_dashboard'))

            status_map = {
                'acknowledged': 'pending',
                'need_more_info': 'pending',
                'for_verification': 'in_progress',
                'dispatched_team': 'in_progress',
                'scheduled_repair': 'in_progress',
                'duplicate_report': 'resolved',
                'outside_scope': 'resolved',
                'resolved': 'resolved',
            }
            report.status = status_map.get(action_value, report.status)
            report.save()

            action_entry = ReportAction.objects.create(
                report=report,
                action=action_value,
                note=action_note,
                created_by=request.user,
            )
            try:
                AuditLog.objects.create(
                    actor=request.user,
                    action='report_action',
                    target_type='Report',
                    target_id=report.id,
                    target_repr=report.title,
                    barangay=report.user.community_profile.barangay if hasattr(report.user, 'community_profile') else None,
                    reason=action_note or '',
                    data={'action': action_value}
                )
            except Exception:
                pass
            notify_admin_action(report, action_entry.get_action_display(), action_note)
            # AJAX support
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'ok', 'message': 'Admin action saved and user notified.', 'report_id': report.id, 'new_status': report.status})
            messages.success(request, 'Admin action saved and user notified.')

        elif action == 'delete_report' and report_id:
            report_id_int = _safe_int(report_id)
            if report_id_int is None:
                messages.error(request, 'Invalid report id.')
                return redirect(reverse('admin_dashboard'))
            try:
                rep = reports_scope.get(id=report_id_int)
                # soft-delete
                rep.is_deleted = True
                rep.deleted_at = timezone.now()
                rep.save()
                # store for undo
                try:
                    request.session['last_deleted_report'] = {
                        'id': rep.id,
                        'title': rep.title,
                        'deleted_at': rep.deleted_at.isoformat() if rep.deleted_at else ''
                    }
                    request.session.modified = True
                except Exception:
                    pass
                try:
                    AuditLog.objects.create(
                        actor=request.user,
                        action='delete_report',
                        target_type='Report',
                        target_id=rep.id,
                        target_repr=rep.title,
                        barangay=rep.user.community_profile.barangay if hasattr(rep.user, 'community_profile') else None,
                        reason='Soft-deleted by admin',
                        data={}
                    )
                except Exception:
                    pass
                # AJAX response
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'ok', 'message': 'Report deleted. You can undo this action from the dashboard.', 'report_id': rep.id})
                messages.success(request, 'Report deleted. You can undo this action from the dashboard.')
            except Report.DoesNotExist:
                messages.error(request, 'Report not found.')

        return redirect(reverse('admin_dashboard'))

    # Filters
    status_filter = request.GET.get('status', '')
    priority_filter = request.GET.get('priority', '')
    search_query = request.GET.get('q', '')
    pending_query = request.GET.get('pending_q', '')

    # Exclude soft-deleted reports
    reports = reports_scope.filter(is_deleted=False)
    if status_filter:
        reports = reports.filter(status=status_filter)
    if priority_filter:
        reports = reports.filter(priority=priority_filter)
    if search_query:
        reports = reports.filter(
            Q(title__icontains=search_query) |
            Q(location__icontains=search_query) |
            Q(user__username__icontains=search_query) |
            Q(user__email__icontains=search_query)
        )

    # Pending registrations search
    pending_qs = scoped_profiles.filter(status=CommunityProfile.STATUS_PENDING).order_by('-created_at')
    if pending_query:
        pending_qs = pending_qs.filter(
            Q(user__username__icontains=pending_query) |
            Q(user__email__icontains=pending_query) |
            Q(address__icontains=pending_query)
        )

    # Export / Reporting - CSV
    export = request.GET.get('export')
    if export in ('reports', 'registrations'):
        # Build filename
        from django.utils import timezone as djtz
        ts = djtz.now().strftime('%Y%m%d_%H%M')
        if export == 'reports':
            filename = f'i-sumbong-reports-{ts}.csv'
            qs = reports.order_by('-created_at')
            rows = qs.values('id', 'title', 'location', 'priority', 'status', 'user__username', 'user__email', 'created_at')
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            writer = csv.writer(response)
            writer.writerow(['ID', 'Title', 'Location', 'Priority', 'Status', 'Username', 'Email', 'Created At'])
            for r in rows:
                writer.writerow([
                    r.get('id'),
                    r.get('title'),
                    r.get('location'),
                    r.get('priority'),
                    r.get('status'),
                    r.get('user__username'),
                    r.get('user__email'),
                    r.get('created_at').strftime('%Y-%m-%d %H:%M') if r.get('created_at') else '',
                ])
            return response

        if export == 'registrations':
            filename = f'i-sumbong-registrations-{ts}.csv'
            qs = scoped_profiles
            # apply status filter if provided
            reg_status = request.GET.get('reg_status') or ''
            if reg_status:
                qs = qs.filter(status=reg_status)
            rows = qs.select_related('user', 'barangay', 'reviewed_by').order_by('-created_at')
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            writer = csv.writer(response)
            writer.writerow(['ID', 'Username', 'Email', 'Barangay', 'Address', 'Phone', 'Status', 'Reviewed By', 'Reviewed At', 'Review Notes', 'Created At'])
            for p in rows:
                writer.writerow([
                    p.id,
                    p.user.username,
                    p.user.email,
                    p.barangay.name if p.barangay else '',
                    p.address,
                    p.phone_number,
                    p.status,
                    p.reviewed_by.username if p.reviewed_by else '',
                    p.reviewed_at.strftime('%Y-%m-%d %H:%M') if p.reviewed_at else '',
                    p.review_notes or '',
                    p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else '',
                ])
            return response

    duplicate_groups = (
        reports_scope
        .annotate(normalized_title=Lower(Trim('title')), normalized_location=Lower(Trim('location')))
        .values('normalized_title', 'normalized_location', 'title', 'location')
        .annotate(duplicate_count=Count('id'))
        .filter(duplicate_count__gt=1)
        .order_by('-duplicate_count', 'title')
    )
    duplicate_map = {
        f"{row['normalized_title']}|{row['normalized_location']}": row['duplicate_count']
        for row in duplicate_groups
    }
    latest_actions = (
        ReportAction.objects
        .filter(report__in=reports)
        .select_related('created_by')
        .order_by('report_id', '-created_at')
    )
    latest_action_map = {}
    for action_entry in latest_actions:
        if action_entry.report_id not in latest_action_map:
            latest_action_map[action_entry.report_id] = action_entry

    reports_list = list(reports)
    for report in reports_list:
        key = f"{report.title.strip().lower()}|{report.location.strip().lower()}"
        report.duplicate_count = duplicate_map.get(key, 1)
        latest_action = latest_action_map.get(report.id)
        if latest_action:
            report.latest_action_label = latest_action.get_action_display()
            report.latest_action_note = latest_action.note
        else:
            report.latest_action_label = ''
            report.latest_action_note = ''

    all_reports = reports_scope
    # Server-side pagination
    reports_per_page = 15
    reports_paginator = Paginator(reports_list, reports_per_page)
    reports_page_number = request.GET.get('reports_page') or 1
    reports_page = reports_paginator.get_page(reports_page_number)

    pending_per_page = 8
    pending_paginator = Paginator(pending_qs, pending_per_page)
    pending_page_number = request.GET.get('pending_page') or 1
    pending_page = pending_paginator.get_page(pending_page_number)

    reviewed_registrations = scoped_profiles.exclude(status=CommunityProfile.STATUS_PENDING).order_by('-reviewed_at', '-created_at')

    # Chart data - reports per day (last 7 days)
    from django.utils import timezone as djtz
    today = djtz.now().date()
    chart_labels = []
    chart_counts = []
    for i in range(6, -1, -1):
        day = today - timezone.timedelta(days=i)
        chart_labels.append(day.strftime('%b %d'))
        cnt = reports_scope.filter(created_at__date=day, is_deleted=False).count()
        chart_counts.append(cnt)
    # Average resolution time (hours) for resolved reports in the scoped reports
    resolved_qs = reports_scope.filter(resolved_at__isnull=False)
    avg_resolution_hours = None
    try:
        total_seconds = 0
        count_resolved = resolved_qs.count()
        if count_resolved:
            for r in resolved_qs:
                if r.resolved_at and r.created_at:
                    total_seconds += (r.resolved_at - r.created_at).total_seconds()
            avg_resolution_hours = (total_seconds / count_resolved) / 3600.0
    except Exception:
        avg_resolution_hours = None
    # Hotspot locations (top locations by report count)
    try:
        hotspot_qs = reports_scope.filter(is_deleted=False).values('location').annotate(count=Count('id')).order_by('-count')[:10]
        hotspots = [{'location': h['location'], 'count': h['count']} for h in hotspot_qs]
    except Exception:
        hotspots = []

    # Admin workload: assigned reports per admin
    try:
        assigned_qs = reports_scope.filter(assigned_to__isnull=False).values('assigned_to__username').annotate(count=Count('id')).order_by('-count')
        admin_workload = [{'user': a['assigned_to__username'], 'count': a['count']} for a in assigned_qs]
    except Exception:
        admin_workload = []

    # Barangay performance (if scoped to a barangay)
    barangay_performance = None
    try:
        if admin_barangay:
            total_reports = reports_scope.filter(user__community_profile__barangay=admin_barangay, is_deleted=False).count()
            resolved_reports = reports_scope.filter(user__community_profile__barangay=admin_barangay, status='resolved', is_deleted=False).count()
            resolved_rate = (resolved_reports / total_reports * 100.0) if total_reports else None
            resolved_qs_b = reports_scope.filter(user__community_profile__barangay=admin_barangay, resolved_at__isnull=False)
            avg_res = None
            if resolved_qs_b.exists():
                total_sec_b = 0
                for r in resolved_qs_b:
                    if r.resolved_at and r.created_at:
                        total_sec_b += (r.resolved_at - r.created_at).total_seconds()
                avg_res = (total_sec_b / resolved_qs_b.count()) / 3600.0 if resolved_qs_b.count() else None
            barangay_performance = {
                'total_reports': total_reports,
                'resolved_reports': resolved_reports,
                'resolved_rate': resolved_rate,
                'avg_resolution_hours': avg_res,
            }
    except Exception:
        barangay_performance = None
    bulletins = bulletin_scope.annotate(seen_count=Count('views'))
    if admin_barangay_name == 'All Barangays':
        bulletin_history = BulletinPostHistory.objects.select_related('barangay', 'changed_by')
    elif admin_barangay:
        bulletin_history = BulletinPostHistory.objects.filter(barangay=admin_barangay).select_related('barangay', 'changed_by')
    else:
        bulletin_history = BulletinPostHistory.objects.none()
    # Activity / Audit Log (recent)
    if admin_barangay:
        activity_log = AuditLog.objects.filter(barangay=admin_barangay).select_related('actor', 'barangay')[:50]
    else:
        activity_log = AuditLog.objects.select_related('actor', 'barangay')[:50]
    # preserve current filters when paginating
    base_qs = request.GET.copy()
    base_qs.pop('reports_page', None)
    base_qs.pop('pending_page', None)
    base_query = base_qs.urlencode()
    allowed_admin_pages = {'dashboard', 'reports', 'analytics', 'bulletin', 'validation', 'users'}
    initial_page = request.GET.get('page', 'dashboard')
    if initial_page not in allowed_admin_pages:
        initial_page = 'dashboard'

    context = {
        'reports': reports_list,
        'reports_page': reports_page,
        'total': all_reports.count(),
        'pending': all_reports.filter(status='pending').count(),
        'in_progress': all_reports.filter(status='in_progress').count(),
        'resolved': all_reports.filter(status='resolved').count(),
        'total_users': scoped_profiles.count(),
        'pending_registrations': pending_qs,
        'pending_page': pending_page,
        'reviewed_registrations': reviewed_registrations[:20],
        'admin_barangay_name': admin_barangay_name,
        'admin_barangay': admin_barangay,
        'bulletins': bulletins,
        'bulletin_categories': BulletinPost.CATEGORY_CHOICES,
        'bulletin_priorities': BulletinPost.PRIORITY_CHOICES,
        'barangays': Barangay.objects.all().order_by('name'),
        'bulletin_history': bulletin_history[:20],
        'activity_log': activity_log,
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'search_query': search_query,
        'pending_query': pending_query,
        'admin_users': admin_users,
        'promotable_users': promotable_users,
        'chart_labels': chart_labels,
        'chart_counts': chart_counts,
        'report_action_choices': ReportAction.ACTION_CHOICES,
        'duplicate_groups': duplicate_groups[:10],
        'last_bulk_action': last_bulk_action,
        'last_deleted_report': last_deleted_report,
        'avg_resolution_hours': avg_resolution_hours,
        'hotspots': hotspots,
        'admin_workload': admin_workload,
        'barangay_performance': barangay_performance,
        'initial_page': initial_page,
    }
    return render(request, 'base/barangayAdmin_dashboard.html', context)
