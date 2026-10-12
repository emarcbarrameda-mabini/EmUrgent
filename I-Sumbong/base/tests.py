from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from django.utils import timezone

from .models import (
	Barangay,
	BarangayAdminProfile,
	BulletinPost,
	BulletinPostHistory,
	CommunityProfile,
	Notification,
	Report,
	ReportAction,
    AuditLog,
)


def create_test_image(name='proof.jpg'):
	# Minimal valid 1x1 GIF bytes for ImageField tests.
	return SimpleUploadedFile(
		name,
		b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x4c\x01\x00\x3b',
		content_type='image/gif',
	)


class AuthenticationTests(TestCase):
	def setUp(self):
		self.barangay = Barangay.objects.create(name='Barangay Uno')

	def test_register_success(self):
		response = self.client.post(reverse('register'), {
			'username': 'newuser',
			'email': 'newuser@example.com',
			'address': 'Purok 1, Barangay Uno',
			'phone_number': '09171234567',
			'barangay': str(self.barangay.id),
			'proof_of_residency': create_test_image('new-proof.gif'),
			'password1': 'StrongPass123!',
			'password2': 'StrongPass123!',
			'terms_accepted': 'on',
		})

		self.assertRedirects(response, reverse('login'))
		self.assertTrue(User.objects.filter(username='newuser').exists())

		user = User.objects.get(username='newuser')
		profile = CommunityProfile.objects.get(user=user)
		self.assertEqual(profile.barangay, self.barangay)
		self.assertEqual(profile.phone_number, '+639171234567')
		self.assertEqual(profile.status, CommunityProfile.STATUS_PENDING)

	def test_register_invalid_phone_number(self):
		response = self.client.post(reverse('register'), {
			'username': 'badphone',
			'email': 'badphone@example.com',
			'address': 'Purok 9, Barangay Uno',
			'phone_number': '12345',
			'barangay': str(self.barangay.id),
			'proof_of_residency': create_test_image('badphone-proof.gif'),
			'password1': 'StrongPass123!',
			'password2': 'StrongPass123!',
			'terms_accepted': 'on',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Please use a valid Philippine mobile number')

	def test_register_duplicate_email_validation(self):
		User.objects.create_user(
			username='existing',
			email='same@example.com',
			password='StrongPass123!'
		)

		response = self.client.post(reverse('register'), {
			'username': 'otheruser',
			'email': 'same@example.com',
			'address': 'Purok 2, Barangay Uno',
			'barangay': str(self.barangay.id),
			'proof_of_residency': create_test_image('duplicate-proof.gif'),
			'password1': 'StrongPass123!',
			'password2': 'StrongPass123!',
			'terms_accepted': 'on',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'This email is already registered.')
		self.assertEqual(User.objects.filter(email='same@example.com').count(), 1)

	def test_login_pending_user_sees_waiting_screen(self):
		user = User.objects.create_user(
			username='pendinguser',
			email='pending@example.com',
			password='StrongPass123!'
		)
		CommunityProfile.objects.create(
			user=user,
			barangay=self.barangay,
			address='Purok 1, Barangay Uno',
			proof_of_residency=create_test_image('pending-proof.gif'),
			status=CommunityProfile.STATUS_PENDING,
		)

		response = self.client.post(reverse('login'), {
			'username': 'pendinguser',
			'password': 'StrongPass123!',
		})
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Please wait for your barangay admin to accept your account')

	def test_login_approved_user_and_logout(self):
		user = User.objects.create_user(
			username='authuser',
			email='auth@example.com',
			password='StrongPass123!'
		)
		CommunityProfile.objects.create(
			user=user,
			barangay=self.barangay,
			address='Purok 1, Barangay Uno',
			proof_of_residency=create_test_image('approved-proof.gif'),
			status=CommunityProfile.STATUS_APPROVED,
		)

		login_response = self.client.post(reverse('login'), {
			'username': 'authuser',
			'password': 'StrongPass123!',
		})
		self.assertRedirects(login_response, reverse('home'))

		dashboard_response = self.client.get(reverse('home'))
		self.assertIn('no-store', dashboard_response.headers['Cache-Control'])

		logout_response = self.client.post(reverse('logout'))
		self.assertRedirects(logout_response, reverse('login'))
		self.assertIn('no-store', logout_response.headers['Cache-Control'])

		self.assertFalse('_auth_user_id' in self.client.session)
		self.assertEqual(user.username, 'authuser')
		back_navigation_response = self.client.get(reverse('home'))
		self.assertRedirects(back_navigation_response, reverse('login') + '?next=/home/')

	def test_login_switches_to_submitted_account(self):
		current_user = User.objects.create_user(
			username='currentuser',
			email='current@example.com',
			password='StrongPass123!',
		)
		target_user = User.objects.create_user(
			username='targetuser',
			email='target@example.com',
			password='StrongPass123!',
		)
		CommunityProfile.objects.create(
			user=target_user,
			barangay=self.barangay,
			address='Purok 2, Barangay Uno',
			proof_of_residency=create_test_image('target-proof.gif'),
			status=CommunityProfile.STATUS_APPROVED,
		)
		self.client.force_login(current_user)

		response = self.client.post(reverse('login'), {
			'login-username': 'targetuser',
			'login-password': 'StrongPass123!',
		})

		self.assertRedirects(response, reverse('home'))
		self.assertEqual(
			int(self.client.session['_auth_user_id']),
			target_user.id,
		)

	def test_registration_clears_previous_authenticated_account(self):
		current_user = User.objects.create_user(
			username='currentuser',
			email='current@example.com',
			password='StrongPass123!',
		)
		self.client.force_login(current_user)

		response = self.client.post(reverse('register'), {
			'register-username': 'newregistereduser',
			'register-email': 'newregistereduser@example.com',
			'register-address': 'Purok 1, Barangay Uno',
			'register-phone_number': '09171234567',
			'register-barangay': str(self.barangay.id),
			'register-proof_of_residency': create_test_image('new-registered-proof.gif'),
			'register-password1': 'StrongPass123!',
			'register-password2': 'StrongPass123!',
			'register-terms_accepted': 'on',
		})

		self.assertRedirects(response, reverse('login'))
		self.assertTrue(User.objects.filter(username='newregistereduser').exists())
		self.assertNotIn('_auth_user_id', self.client.session)


class ReportFlowTests(TestCase):
	def setUp(self):
		self.barangay = Barangay.objects.create(name='Barangay Dos')
		self.user = User.objects.create_user(
			username='reporter',
			email='reporter@example.com',
			password='StrongPass123!'
		)
		CommunityProfile.objects.create(
			user=self.user,
			barangay=self.barangay,
			address='Purok 3, Barangay Dos',
			proof_of_residency=create_test_image('reporter-proof.gif'),
			status=CommunityProfile.STATUS_APPROVED,
		)
		self.client.login(username='reporter', password='StrongPass123!')

	@override_settings(GOOGLE_MAPS_API_KEY='test-google-maps-key')
	def test_report_form_loads_google_maps_with_configured_key(self):
		response = self.client.get(reverse('home'), {'page': 'submit'})
		self.assertContains(response, 'maps.googleapis.com/maps/api/js')
		self.assertContains(response, 'key=test-google-maps-key')
		self.assertContains(response, 'callback=initGoogleReportLocationMaps')
		self.assertNotContains(response, 'tile.openstreetmap.org')

	@override_settings(GOOGLE_MAPS_API_KEY='')
	def test_report_form_explains_missing_google_maps_key(self):
		response = self.client.get(reverse('home'), {'page': 'submit'})
		self.assertContains(response, 'Google Maps API key is not configured')
		self.assertNotContains(response, 'maps.googleapis.com/maps/api/js')

	def test_report_create_edit_delete(self):
		create_response = self.client.post(reverse('home'), {
			'action': 'submit_report',
			'title': 'Open Drainage',
			'location': 'Main Street',
			'priority': 'high',
			'description': 'Drainage is blocked.',
		})
		self.assertRedirects(create_response, f"{reverse('home')}?page=home")

		report = Report.objects.get(title='Open Drainage', user=self.user)
		self.assertEqual(report.location, 'Main Street')
		self.assertEqual(report.priority, 'high')

		edit_response = self.client.post(reverse('home'), {
			'action': 'edit_report',
			'report_id': report.id,
			'title': 'Open Drainage Updated',
			'location': 'Main Street Corner',
			'priority': 'medium',
			'description': 'Drainage still blocked after rain.',
		})
		self.assertRedirects(edit_response, f"{reverse('home')}?page=my-reports")

		report.refresh_from_db()
		self.assertEqual(report.title, 'Open Drainage Updated')
		self.assertEqual(report.location, 'Main Street Corner')
		self.assertEqual(report.priority, 'medium')

		delete_response = self.client.post(reverse('home'), {
			'action': 'delete_report',
			'report_id': report.id,
		})
		self.assertRedirects(delete_response, f"{reverse('home')}?page=my-reports")
		self.assertFalse(Report.objects.filter(id=report.id).exists())

	def test_same_barangay_member_can_view_details_but_not_edit_report(self):
		report = Report.objects.create(
			user=self.user,
			title='Broken Streetlight',
			location='Purok 2',
			priority='medium',
			description='Streetlight has been out for two nights.',
		)
		neighbor = User.objects.create_user(
			username='neighbor',
			email='neighbor@example.com',
			password='StrongPass123!',
		)
		CommunityProfile.objects.create(
			user=neighbor,
			barangay=self.barangay,
			address='Purok 4, Barangay Dos',
			proof_of_residency=create_test_image('neighbor-proof.gif'),
			status=CommunityProfile.STATUS_APPROVED,
		)
		other_barangay = Barangay.objects.create(name='Barangay Labas')
		outsider = User.objects.create_user(
			username='outsider',
			email='outsider@example.com',
			password='StrongPass123!',
		)
		CommunityProfile.objects.create(
			user=outsider,
			barangay=other_barangay,
			address='Outside Barangay',
			proof_of_residency=create_test_image('outsider-proof.gif'),
			status=CommunityProfile.STATUS_APPROVED,
		)

		self.client.logout()
		self.client.login(username='neighbor', password='StrongPass123!')
		detail_response = self.client.get(reverse('report_detail', args=[report.id]))
		self.assertEqual(detail_response.status_code, 200)
		self.assertContains(detail_response, 'Broken Streetlight')
		self.assertContains(detail_response, 'Post Comment')

		comment_response = self.client.post(
			reverse('post_report_comment', args=[report.id]),
			{'message': 'I saw this too.'},
		)
		self.assertEqual(comment_response.status_code, 200)
		self.assertTrue(report.comments.filter(user=neighbor, message='I saw this too.').exists())
		self.assertTrue(
			Notification.objects.filter(
				user=self.user,
				report=report,
				notif_type='admin_action',
				message__contains='neighbor commented on your report "Broken Streetlight"',
			).exists()
		)

		edit_response = self.client.post(reverse('home'), {
			'action': 'edit_report',
			'report_id': report.id,
			'title': 'Changed by neighbor',
			'location': 'Changed location',
			'priority': 'high',
			'description': 'Changed description.',
		})
		self.assertRedirects(edit_response, f"{reverse('home')}?page=my-reports")
		report.refresh_from_db()
		self.assertEqual(report.title, 'Broken Streetlight')
		self.assertEqual(report.location, 'Purok 2')

		self.client.logout()
		self.client.login(username='outsider', password='StrongPass123!')
		outsider_response = self.client.get(reverse('report_detail', args=[report.id]))
		self.assertRedirects(outsider_response, reverse('home'))

	@override_settings(GOOGLE_MAPS_API_KEY='test-google-maps-key')
	def test_report_detail_loads_google_maps_with_configured_key(self):
		report = Report.objects.create(
			user=self.user,
			title='Mapped Report',
			location='Purok 2',
			priority='medium',
			description='Map integration check.',
			latitude=14.5995,
			longitude=120.9842,
		)
		response = self.client.get(reverse('report_detail', args=[report.id]))
		self.assertContains(response, 'maps.googleapis.com/maps/api/js')
		self.assertContains(response, 'key=test-google-maps-key')
		self.assertContains(response, 'callback=initGoogleReportDetailMap')
		self.assertNotContains(response, 'tile.openstreetmap.org')

	def test_notification_link_marks_read_and_opens_report_detail(self):
		report = Report.objects.create(
			user=self.user,
			title='Fallen Branch',
			location='Purok 5',
			priority='low',
			description='A branch is blocking part of the walkway.',
		)
		notification = Notification.objects.create(
			user=self.user,
			report=report,
			notif_type='report_submitted',
			message='Your report "Fallen Branch" has been submitted successfully.',
		)

		response = self.client.get(reverse('notification_detail', args=[notification.id]))

		self.assertRedirects(response, reverse('report_detail', args=[report.id]))
		notification.refresh_from_db()
		self.assertTrue(notification.is_read)


class AdminAndNotificationTests(TestCase):
	def setUp(self):
		self.barangay = Barangay.objects.create(name='Barangay Tres')
		self.admin_user = User.objects.create_user(
			username='adminuser',
			email='admin@example.com',
			password='StrongPass123!',
			is_staff=True,
		)
		BarangayAdminProfile.objects.create(user=self.admin_user, barangay=self.barangay)

		self.report_owner = User.objects.create_user(
			username='owner',
			email='owner@example.com',
			password='StrongPass123!',
		)
		CommunityProfile.objects.create(
			user=self.report_owner,
			barangay=self.barangay,
			address='Purok 4, Barangay Tres',
			proof_of_residency=create_test_image('owner-proof.gif'),
			status=CommunityProfile.STATUS_APPROVED,
		)

	def test_admin_can_approve_pending_member_in_same_barangay(self):
		new_member = User.objects.create_user(
			username='forapproval',
			email='forapproval@example.com',
			password='StrongPass123!'
		)
		pending_profile = CommunityProfile.objects.create(
			user=new_member,
			barangay=self.barangay,
			address='Purok 5, Barangay Tres',
			proof_of_residency=create_test_image('forapproval-proof.gif'),
			status=CommunityProfile.STATUS_PENDING,
		)

		self.client.login(username='adminuser', password='StrongPass123!')
		response = self.client.post(reverse('admin_dashboard'), {
			'action': 'approve_user',
			'profile_id': pending_profile.id,
		})

		self.assertRedirects(response, reverse('admin_dashboard'))
		pending_profile.refresh_from_db()
		self.assertEqual(pending_profile.status, CommunityProfile.STATUS_APPROVED)
		self.assertEqual(pending_profile.reviewed_by, self.admin_user)
		self.assertEqual(len(mail.outbox), 1)
		self.assertIn('approved', mail.outbox[0].subject.lower())

	def test_admin_reject_requires_reason(self):
		new_member = User.objects.create_user(
			username='noreason',
			email='noreason@example.com',
			password='StrongPass123!'
		)
		pending_profile = CommunityProfile.objects.create(
			user=new_member,
			barangay=self.barangay,
			address='Purok 6, Barangay Tres',
			proof_of_residency=create_test_image('noreason-proof.gif'),
			status=CommunityProfile.STATUS_PENDING,
		)

		self.client.login(username='adminuser', password='StrongPass123!')
		response = self.client.post(reverse('admin_dashboard'), {
			'action': 'reject_user',
			'profile_id': pending_profile.id,
			'review_notes': '',
		})

		self.assertRedirects(response, reverse('admin_dashboard'))
		pending_profile.refresh_from_db()
		self.assertEqual(pending_profile.status, CommunityProfile.STATUS_PENDING)
		self.assertEqual(len(mail.outbox), 0)

	def test_rejected_user_can_resubmit_proof(self):
		rejected_user = User.objects.create_user(
			username='rejecteduser',
			email='rejected@example.com',
			password='StrongPass123!'
		)
		rejected_profile = CommunityProfile.objects.create(
			user=rejected_user,
			barangay=self.barangay,
			address='Old Address',
			proof_of_residency=create_test_image('old-proof.gif'),
			status=CommunityProfile.STATUS_REJECTED,
			review_notes='Address did not match records.',
			reviewed_by=self.admin_user,
		)

		self.client.login(username='rejecteduser', password='StrongPass123!')
		response = self.client.post(
			reverse('resubmit_proof'),
			{
				'address': 'Updated Address, Barangay Tres',
				'barangay': str(self.barangay.id),
				'proof_of_residency': create_test_image('resubmitted-proof.gif'),
			},
		)

		self.assertEqual(response.status_code, 200)
		rejected_profile.refresh_from_db()
		self.assertEqual(rejected_profile.status, CommunityProfile.STATUS_PENDING)
		self.assertEqual(rejected_profile.address, 'Updated Address, Barangay Tres')
		self.assertEqual(rejected_profile.review_notes, '')
		self.assertIsNone(rejected_profile.reviewed_by)

	def test_admin_can_update_report_status(self):
		report = Report.objects.create(
			user=self.report_owner,
			title='Broken Street Light',
			location='Purok 1',
			priority='low',
			description='Street light not functioning.',
		)

		self.client.login(username='adminuser', password='StrongPass123!')
		response = self.client.post(reverse('admin_dashboard'), {
			'action': 'update_status',
			'report_id': report.id,
			'status': 'in_progress',
		})

		self.assertRedirects(response, reverse('admin_dashboard'))
		report.refresh_from_db()
		self.assertEqual(report.status, 'in_progress')

	def test_admin_action_creates_log_and_notifies_user(self):
		report = Report.objects.create(
			user=self.report_owner,
			title='Fallen Tree',
			location='Purok 7',
			priority='high',
			description='Tree blocking the road.',
		)

		self.client.login(username='adminuser', password='StrongPass123!')
		response = self.client.post(reverse('admin_dashboard'), {
			'action': 'add_report_action',
			'report_id': report.id,
			'report_action': 'dispatched_team',
			'action_note': 'Clean-up team dispatched at 9AM.',
		})

		self.assertRedirects(response, reverse('admin_dashboard'))
		report.refresh_from_db()
		self.assertEqual(report.status, 'in_progress')
		self.assertTrue(ReportAction.objects.filter(report=report, action='dispatched_team').exists())
		self.assertTrue(
			Notification.objects.filter(user=self.report_owner, report=report, notif_type='admin_action').exists()
		)

	def test_notification_created_on_report_submit_and_status_change(self):
		self.client.login(username='owner', password='StrongPass123!')

		submit_response = self.client.post(reverse('home'), {
			'action': 'submit_report',
			'title': 'Flooded Pathway',
			'location': 'Sitio Uno',
			'priority': 'medium',
			'description': 'Pathway is flooded and slippery.',
		})
		self.assertRedirects(submit_response, f"{reverse('home')}?page=home")

		report = Report.objects.get(title='Flooded Pathway', user=self.report_owner)
		self.assertTrue(
			Notification.objects.filter(
				user=self.report_owner,
				report=report,
				notif_type='report_submitted'
			).exists()
		)

		self.client.logout()
		self.client.login(username='adminuser', password='StrongPass123!')

		update_response = self.client.post(reverse('admin_dashboard'), {
			'action': 'update_status',
			'report_id': report.id,
			'status': 'resolved',
		})
		self.assertRedirects(update_response, reverse('admin_dashboard'))

		self.assertTrue(
			Notification.objects.filter(
				user=self.report_owner,
				report=report,
				notif_type='resolved'
			).exists()
		)


class BulletinTests(TestCase):
	def setUp(self):
		self.barangay_a = Barangay.objects.create(name='Barangay Quatro')
		self.barangay_b = Barangay.objects.create(name='Barangay Singko')
		self.admin_user = User.objects.create_user(
			username='bulletinadmin',
			email='bulletinadmin@example.com',
			password='StrongPass123!'
		)
		self.admin_user.is_staff = True
		self.admin_user.save()
		BarangayAdminProfile.objects.create(user=self.admin_user, barangay=self.barangay_a)

		self.member_a = User.objects.create_user(
			username='membera',
			email='membera@example.com',
			password='StrongPass123!'
		)
		CommunityProfile.objects.create(
			user=self.member_a,
			barangay=self.barangay_a,
			address='Purok 1',
			proof_of_residency=create_test_image('membera-proof.gif'),
			status=CommunityProfile.STATUS_APPROVED,
		)

		self.member_b = User.objects.create_user(
			username='memberb',
			email='memberb@example.com',
			password='StrongPass123!'
		)
		CommunityProfile.objects.create(
			user=self.member_b,
			barangay=self.barangay_b,
			address='Purok 2',
			proof_of_residency=create_test_image('memberb-proof.gif'),
			status=CommunityProfile.STATUS_APPROVED,
		)



	def test_admin_can_publish_urgent_bulletin_and_email_sent(self):
		self.client.login(username='bulletinadmin', password='StrongPass123!')
		response = self.client.post(
			reverse('admin_dashboard'),
			{
				'action': 'create_bulletin',
				'title': 'Emergency Water Interruption',
				'category': 'advisory',
				'priority': 'urgent',
				'content': 'Water supply will be interrupted tonight from 9PM to 5AM.',
			},
		)
		self.assertRedirects(response, reverse('admin_dashboard'))
		self.assertTrue(BulletinPost.objects.filter(title='Emergency Water Interruption').exists())
		self.assertEqual(len(mail.outbox), 1)
		self.assertIn('urgent', mail.outbox[0].subject.lower())
		self.assertTrue(
			BulletinPostHistory.objects.filter(action='created', title_snapshot='Emergency Water Interruption').exists()
		)

	def test_bulk_resend_creates_history_for_urgent(self):
		urgent_post = BulletinPost.objects.create(
			barangay=self.barangay_a,
			title='Urgent Cleanup Notice',
			category='public_safety',
			priority='urgent',
			content='Cleanup drive starts at 7AM tomorrow.',
			created_by=self.admin_user,
		)

		self.client.login(username='bulletinadmin', password='StrongPass123!')
		response = self.client.post(
			reverse('admin_dashboard'),
			{
				'action': 'resend_urgent_bulk',
				'bulletin_ids': [str(urgent_post.id)],
			},
		)

		self.assertRedirects(response, reverse('admin_dashboard'))
		self.assertTrue(
			BulletinPostHistory.objects.filter(action='urgent_resent', bulletin=urgent_post).exists()
		)

	def test_bulletins_visible_only_to_same_barangay_and_not_expired(self):
		BulletinPost.objects.create(
			barangay=self.barangay_a,
			title='Barangay A Notice',
			category='announcement',
			priority='normal',
			content='This is for barangay A only.',
			created_by=self.admin_user,
		)
		BulletinPost.objects.create(
			barangay=self.barangay_b,
			title='Barangay B Notice',
			category='announcement',
			priority='normal',
			content='This is for barangay B only.',
			created_by=self.admin_user,
		)
		BulletinPost.objects.create(
			barangay=self.barangay_a,
			title='Expired Notice',
			category='announcement',
			priority='normal',
			content='Expired bulletin.',
			expires_at=timezone.now() - timedelta(days=1),
			created_by=self.admin_user,
		)

		self.client.login(username='membera', password='StrongPass123!')
		response = self.client.get(reverse('home'))
		self.assertContains(response, 'Barangay A Notice')
		self.assertNotContains(response, 'Barangay B Notice')
		self.assertNotContains(response, 'Expired Notice')


class PromoteDemoteTests(TestCase):
	def setUp(self):
		self.barangay = Barangay.objects.create(name='Barangay Promote')
		# admin who will perform promotions
		self.admin = User.objects.create_user(username='promoter', email='promoter@example.com', password='pass', is_staff=True)
		BarangayAdminProfile.objects.create(user=self.admin, barangay=self.barangay)

		# target user within same barangay
		self.target = User.objects.create_user(username='targetuser', email='target@example.com', password='pass')
		CommunityProfile.objects.create(user=self.target, barangay=self.barangay, address='Addr', proof_of_residency=create_test_image('t.gif'), status=CommunityProfile.STATUS_APPROVED)

	def test_promote_creates_profile_and_audit(self):
		self.client.login(username='promoter', password='pass')
		response = self.client.post(reverse('admin_dashboard'), {
			'action': 'promote_to_barangay_admin',
			'user_id': str(self.target.id),
			'barangay_id': str(self.barangay.id),
		})
		self.assertRedirects(response, reverse('admin_dashboard'))
		self.target.refresh_from_db()
		self.assertTrue(self.target.is_staff)
		self.assertTrue(BarangayAdminProfile.objects.filter(user=self.target, barangay=self.barangay).exists())
		self.assertTrue(AuditLog.objects.filter(target_type='User', target_id=self.target.id, action__contains='promote').exists())

	def test_demote_removes_profile_and_unsets_staff(self):
		# first promote via model
		self.target.is_staff = True
		self.target.save()
		BarangayAdminProfile.objects.create(user=self.target, barangay=self.barangay)

		self.client.login(username='promoter', password='pass')
		response = self.client.post(reverse('admin_dashboard'), {
			'action': 'demote_barangay_admin',
			'user_id': str(self.target.id),
		})
		self.assertRedirects(response, reverse('admin_dashboard'))
		self.target.refresh_from_db()
		self.assertFalse(self.target.is_staff)
		self.assertFalse(BarangayAdminProfile.objects.filter(user=self.target).exists())
		self.assertTrue(AuditLog.objects.filter(target_type='User', target_id=self.target.id, action__contains='demote').exists())


class AjaxSmokeTests(TestCase):
	"""Smoke tests for admin AJAX endpoints: promote/demote, bulletin CRUD, assign/status, approve/reject."""

	def setUp(self):
		self.barangay = Barangay.objects.create(name='SmokeTestBarangay')
		self.super = User.objects.create_superuser('admin', 'admin@local', 'pass')
		self.staff = User.objects.create_user('staff', 'staff@local', 'pass')
		self.user = User.objects.create_user('user1', 'user1@local', 'pass')
		CommunityProfile.objects.create(user=self.user, barangay=self.barangay, status=CommunityProfile.STATUS_APPROVED, address='addr')
		self.client.login(username='admin', password='pass')

	def ajax_post(self, data):
		return self.client.post(reverse('admin_dashboard'), data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

	def test_promote_and_demote_user(self):
		# promote
		resp = self.ajax_post({'action': 'promote_to_barangay_admin', 'user_id': str(self.user.id), 'barangay_id': str(self.barangay.id)})
		self.assertEqual(resp.status_code, 200)
		jr = resp.json()
		self.assertEqual(jr.get('status'), 'ok')
		u = User.objects.get(id=self.user.id)
		self.assertTrue(u.is_staff)
		# demote
		resp = self.ajax_post({'action': 'demote_barangay_admin', 'user_id': str(self.user.id)})
		self.assertEqual(resp.status_code, 200)
		jr = resp.json()
		self.assertEqual(jr.get('status'), 'ok')
		u.refresh_from_db()
		self.assertFalse(u.is_staff)

	def test_bulletin_lifecycle_toggle_delete(self):
		# create
		resp = self.ajax_post({'action': 'create_bulletin', 'title': 'Smoke', 'category': 'announcement', 'content': 'Hello', 'priority': 'normal', 'barangay_id': str(self.barangay.id)})
		self.assertEqual(resp.status_code, 200)
		jr = resp.json()
		self.assertEqual(jr.get('status'), 'ok')
		bid = jr.get('bulletin_id')
		self.assertIsNotNone(bid)
		b = BulletinPost.objects.get(id=bid)
		# toggle
		resp = self.ajax_post({'action': 'toggle_bulletin_pin', 'bulletin_id': str(b.id)})
		self.assertEqual(resp.status_code, 200)
		jr = resp.json(); self.assertEqual(jr.get('status'), 'ok')
		b.refresh_from_db()
		# delete
		resp = self.ajax_post({'action': 'delete_bulletin', 'bulletin_id': str(b.id)})
		self.assertEqual(resp.status_code, 200)
		jr = resp.json(); self.assertEqual(jr.get('status'), 'ok')
		self.assertFalse(BulletinPost.objects.filter(id=b.id).exists())

	def test_assign_and_update_status(self):
		r = Report.objects.create(user=self.user, title='R', location='L', priority='low', description='d')
		# assign to staff (create staff as is_staff)
		self.staff.is_staff = True; self.staff.save()
		resp = self.ajax_post({'action': 'assign_report', 'report_id': str(r.id), 'assignee_id': str(self.staff.id)})
		self.assertEqual(resp.status_code, 200)
		jr = resp.json(); self.assertEqual(jr.get('status'), 'ok')
		r.refresh_from_db(); self.assertEqual(r.assigned_to_id, self.staff.id)
		# update status
		resp = self.ajax_post({'action': 'update_status', 'report_id': str(r.id), 'status': 'in_progress'})
		self.assertEqual(resp.status_code, 200)
		jr = resp.json(); self.assertEqual(jr.get('status'), 'ok')
		r.refresh_from_db(); self.assertEqual(r.status, 'in_progress')

	def test_approve_and_reject_profile(self):
		puser = User.objects.create_user('pending', 'p@local', 'pass')
		prof = CommunityProfile.objects.create(user=puser, barangay=self.barangay, status=CommunityProfile.STATUS_PENDING, address='x')
		resp = self.ajax_post({'action': 'approve_user', 'profile_id': str(prof.id)})
		self.assertEqual(resp.status_code, 200)
		jr = resp.json(); self.assertEqual(jr.get('status'), 'ok')
		prof.refresh_from_db(); self.assertEqual(prof.status, CommunityProfile.STATUS_APPROVED)
		# create another pending and reject
		p2 = User.objects.create_user('pending2', 'p2@local', 'pass')
		prof2 = CommunityProfile.objects.create(user=p2, barangay=self.barangay, status=CommunityProfile.STATUS_PENDING, address='x')
		resp = self.ajax_post({'action': 'reject_user', 'profile_id': str(prof2.id), 'review_notes': 'nope'})
		self.assertEqual(resp.status_code, 200)
		jr = resp.json(); self.assertEqual(jr.get('status'), 'ok')
		prof2.refresh_from_db(); self.assertEqual(prof2.status, CommunityProfile.STATUS_REJECTED)
