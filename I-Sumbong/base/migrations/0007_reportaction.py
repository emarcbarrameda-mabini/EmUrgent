from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('base', '0006_bulletinposthistory'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReportAction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('acknowledged', 'Acknowledged'), ('for_verification', 'For Verification'), ('dispatched_team', 'Dispatched Team'), ('scheduled_repair', 'Scheduled Repair/Cleanup'), ('need_more_info', 'Need More Info'), ('duplicate_report', 'Duplicate Report'), ('outside_scope', 'Outside Scope'), ('resolved', 'Resolved')], max_length=30)),
                ('note', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='report_actions', to='auth.user')),
                ('report', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='actions', to='base.report')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
