from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.db import transaction
from django.core.management import get_commands, load_command_class
from django.conf import settings

from .util import reschedule_job


def handle_post_migrate(sender, **kwargs):
    ScheduledJob = sender.get_model('ScheduledJob')

    with transaction.atomic():
        jobs = []
        for name, app in get_commands().items():
            if app.startswith('django'):
                continue
            cmd = load_command_class(app, name)
            if hasattr(cmd, 'ScheduledJob'):
                job, created = ScheduledJob.objects.get_or_create(app=app, command=name)

                dirty = False

                def _update_field(jobfield, cmdfield, obj=cmd.ScheduledJob, default=None):
                    if getattr(job, jobfield) != getattr(obj, cmdfield, default):
                        setattr(job, jobfield, getattr(obj, cmdfield, default))
                        return True
                    return False

                dirty += _update_field('description', 'help', obj=cmd)
                dirty += _update_field('scheduled_interval', 'scheduled_interval')
                dirty += _update_field('scheduled_times', 'scheduled_times')
                if dirty:
                    job.full_clean()
                    if created:
                        reschedule_job(job, save=False)
                    job.save()
                    if created:
                        print("Created scheduled job for {}".format(job.description))
                    else:
                        print("Updated scheduled job for {}".format(job.description))
                jobs.append(job.pk)

        for dj in ScheduledJob.objects.exclude(pk__in=jobs):
            print("Deleted scheduled job for {}".format(dj.description))
            dj.delete()


class SchedulerAppConfig(AppConfig):
    name = 'postgresqleu.scheduler'

    def ready(self):
        post_migrate.connect(handle_post_migrate, sender=self)
