# -*- coding: utf-8 -*-
# Generated by Django 1.11.17 on 2019-02-06 13:07
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('confreg', '0042_paymethods'),
    ]

    operations = [
        migrations.AlterField(
            model_name='conference',
            name='startdate',
            field=models.DateField(db_index=True, verbose_name='Start date'),
        ),
        migrations.RunSQL("CREATE INDEX IF NOT EXISTS confreg_conferenceregistration_id_unpaid ON confreg_conferenceregistration(id) WHERE payconfirmedat IS NULL"),
        migrations.RunSQL("CREATE INDEX IF NOT EXISTS confreg_conferenceregistration_additionaloptions_options ON confreg_conferenceregistration_additionaloptions (conferenceadditionaloption_id)"),
        migrations.RunSQL("CREATE INDEX IF NOT EXISTS confreg_conferencesession_speaker_speaker_id ON confreg_conferencesession_speaker (speaker_id)"),
    ]
