#!/usr/bin/env python
#
# Cancel invoices that have passed their auto-cancel time
#
# Copyright (C) 2015, PostgreSQL Europe
#
from django.core.management.base import BaseCommand
from django.db import transaction

from datetime import datetime, timedelta

from postgresqleu.invoices.models import Invoice
from postgresqleu.invoices.util import InvoiceManager


class Command(BaseCommand):
    help = 'Cancel invoices that have passed their auto-cancel time'

    class ScheduledJob:
        scheduled_interval = timedelta(minutes=30)
        internal = True

        @classmethod
        def should_run(self):
            return Invoice.objects.filter(finalized=True, deleted=False, paidat__isnull=True, canceltime__lt=datetime.now()).exists()

    @transaction.atomic
    def handle(self, *args, **options):
        invoices = Invoice.objects.filter(finalized=True, deleted=False, paidat__isnull=True, canceltime__lt=datetime.now())

        manager = InvoiceManager()

        for invoice in invoices:
            self.stdout.write("Canceling invoice {0}, expired".format(invoice.id))

            # The manager will automatically cancel any registrations etc,
            # as well as send an email to the user.
            manager.cancel_invoice(invoice,
                                   "Invoice was automatically canceled because payment was not received on time.")
