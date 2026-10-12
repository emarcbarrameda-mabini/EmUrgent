from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('base', '0005_communityprofile_phone_number'),
    ]

    operations = [
        migrations.CreateModel(
            name='BulletinPostHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('created', 'Created'), ('updated', 'Updated'), ('pin_toggled', 'Pin Toggled'), ('urgent_resent', 'Urgent Resent'), ('deleted', 'Deleted')], max_length=20)),
                ('title_snapshot', models.CharField(max_length=200)),
                ('category_snapshot', models.CharField(max_length=30)),
                ('priority_snapshot', models.CharField(max_length=10)),
                ('content_snapshot', models.TextField()),
                ('is_pinned_snapshot', models.BooleanField(default=False)),
                ('expires_at_snapshot', models.DateTimeField(blank=True, null=True)),
                ('attachment_name', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('barangay', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='bulletin_history', to='base.barangay')),
                ('bulletin', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='history', to='base.bulletinpost')),
                ('changed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bulletin_history_actions', to='auth.user')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
