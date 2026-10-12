from django.shortcuts import render, redirect
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from django import forms
from .models import Report, Notification


class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'placeholder': 'Email Address',
            'class': 'form-input'
        })
    )
    terms_accepted = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        label='I agree to the Terms and Conditions'
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2', 'terms_accepted')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'placeholder': 'Username', 'class': 'form-input'})
        self.fields['password1'].widget.attrs.update({'placeholder': 'Password', 'class': 'form-input'})
        self.fields['password2'].widget.attrs.update({'placeholder': 'Confirm Password', 'class': 'form-input'})

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('This email is already registered.')
        return email

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


def register(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = CustomUserCreationForm()
    return render(request, 'base/register.html', {'form': form})


@login_required
def home(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'submit_report':
            title = request.POST.get('title', '').strip()
            location = request.POST.get('location', '').strip()
            priority = request.POST.get('priority', 'low')
            description = request.POST.get('description', '').strip()
            photo = request.FILES.get('photo')

            if title and location and description:
                Report.objects.create(
                    user=request.user,
                    title=title,
                    location=location,
                    priority=priority,
                    description=description,
                    photo=photo,
                )
                messages.success(request, 'Your report has been submitted successfully!')
                return redirect(reverse('home') + '?page=home')
            else:
                messages.error(request, 'Please fill in all required fields.')

        elif action == 'edit_report':
            report_id = request.POST.get('report_id')
            try:
                report = Report.objects.get(id=report_id, user=request.user)
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
            try:
                report = Report.objects.get(id=report_id, user=request.user)
                report.delete()
                messages.success(request, 'Report deleted successfully.')
            except Report.DoesNotExist:
                messages.error(request, 'Report not found.')
            return redirect(reverse('home') + '?page=my-reports')

    my_reports = Report.objects.filter(user=request.user)
    community_reports = Report.objects.all()
    notifications = Notification.objects.filter(user=request.user)
    unread_count = notifications.filter(is_read=False).count()

    context = {
        'my_reports': my_reports,
        'community_reports': community_reports,
        'my_reports_count': my_reports.count(),
        'pending_count': my_reports.filter(status='pending').count(),
        'inprogress_count': my_reports.filter(status='in_progress').count(),
        'resolved_count': my_reports.filter(status='resolved').count(),
        'notifications': notifications,
        'unread_count': unread_count,
    }
    return render(request, 'base/home.html', context)


@login_required
def mark_notifications_read(request):
    if request.method == 'POST':
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)


@login_required
def admin_dashboard(request):
    if not request.user.is_staff:
        return redirect('home')

    # Handle status update
    if request.method == 'POST':
        action = request.POST.get('action')
        report_id = request.POST.get('report_id')

        if action == 'update_status' and report_id:
            try:
                report = Report.objects.get(id=report_id)
                new_status = request.POST.get('status')
                if new_status in ['pending', 'in_progress', 'resolved']:
                    report.status = new_status
                    report.save()
                    messages.success(request, f'Status updated to {report.get_status_display()}.')
            except Report.DoesNotExist:
                messages.error(request, 'Report not found.')

        elif action == 'delete_report' and report_id:
            try:
                Report.objects.get(id=report_id).delete()
                messages.success(request, 'Report deleted.')
            except Report.DoesNotExist:
                messages.error(request, 'Report not found.')

        return redirect(reverse('admin_dashboard'))

    # Filters
    status_filter = request.GET.get('status', '')
    priority_filter = request.GET.get('priority', '')
    search_query = request.GET.get('q', '')

    reports = Report.objects.all().select_related('user')
    if status_filter:
        reports = reports.filter(status=status_filter)
    if priority_filter:
        reports = reports.filter(priority=priority_filter)
    if search_query:
        reports = reports.filter(title__icontains=search_query) | reports.filter(location__icontains=search_query) | reports.filter(user__username__icontains=search_query)

    all_reports = Report.objects.all()
    context = {
        'reports': reports,
        'total': all_reports.count(),
        'pending': all_reports.filter(status='pending').count(),
        'in_progress': all_reports.filter(status='in_progress').count(),
        'resolved': all_reports.filter(status='resolved').count(),
        'total_users': User.objects.count(),
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'search_query': search_query,
    }
    return render(request, 'base/admin_dashboard.html', context)