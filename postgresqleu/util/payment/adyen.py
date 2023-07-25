from django.conf import settings
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

import re

from postgresqleu.util.db import exec_to_list, exec_to_scalar
from postgresqleu.util.widgets import StaticTextWidget
from postgresqleu.invoices.models import Invoice, InvoicePaymentMethod
from postgresqleu.invoices.util import diff_workdays
from postgresqleu.invoices.backendforms import BackendInvoicePaymentMethodForm
from postgresqleu.accounting.util import get_account_choices
from postgresqleu.adyen.models import TransactionStatus
from postgresqleu.adyen.util import AdyenAPI

from . import BasePayment


class BackendAdyenCreditCardForm(BackendInvoicePaymentMethodForm):
    merchantaccount = forms.CharField(required=True, label="Merchant account")
    test = forms.BooleanField(required=False, label="Testing system")

    apibaseurl = forms.CharField(required=True, label="API Base URL",
                                 help_text="For test, use https://pal-test.adyen.com/. For prod, find in Adyen CA -> Account -> API Urls")
    checkoutbaseurl = forms.CharField(required=False, label="Checkout API Base Url",
                                      help_text="For test, use https://checkout-test.adyen.com/. For prod, find in Adyen CA -> Developers -> API URLs")
    ws_user = forms.CharField(required=True, label="Web Service user",
                              help_text="Web Service user with Merchant PAL Webservice role")
    ws_password = forms.CharField(required=True, label="Web Service user password", widget=forms.widgets.PasswordInput(render_value=True))
    ws_apikey = forms.CharField(required=True, label="Web Service API key", widget=forms.widgets.PasswordInput(render_value=True))
    report_user = forms.CharField(required=True, label="Report user",
                                  help_text="Report user with Merchant Report Download role")
    report_password = forms.CharField(required=True, label="Report user password", widget=forms.widgets.PasswordInput(render_value=True))
    notify_user = forms.CharField(required=True, label="Notify User",
                                  help_text="User Adyen will use to post notifications with")
    notify_password = forms.CharField(required=True, label="Notify user password", widget=forms.widgets.PasswordInput(render_value=True))

    notification_receiver = forms.EmailField(required=True)
    merchantref_prefix = forms.CharField(required=True, label="Merchant Reference prefix",
                                         help_text="Prefixed to invoice number for all invoices")
    merchantref_refund_prefix = forms.CharField(required=True, label="Merchant Refund prefix",
                                                help_text="Prefixed to refund number for all refunds")

    accounting_authorized = forms.ChoiceField(required=True, choices=get_account_choices,
                                              label="Authorized payments account")
    accounting_payable = forms.ChoiceField(required=True, choices=get_account_choices,
                                           label="Payable balance account")
    accounting_merchant = forms.ChoiceField(required=True, choices=get_account_choices,
                                            label="Merchant account")
    accounting_fee = forms.ChoiceField(required=True, choices=get_account_choices,
                                       label="Fees account")
    accounting_refunds = forms.ChoiceField(required=True, choices=get_account_choices,
                                           label="Pending refunds account")
    accounting_payout = forms.ChoiceField(required=True, choices=get_account_choices,
                                          label="Payout account")

    notifications = forms.CharField(widget=StaticTextWidget)
    returnurl = forms.CharField(label="Return URL", widget=StaticTextWidget)

    config_fields = ['merchantaccount', 'test',
                     'apibaseurl', 'checkoutbaseurl', 'ws_user', 'ws_password', 'ws_apikey',
                     'report_user', 'report_password',
                     'notify_user', 'notify_password',
                     'notification_receiver', 'merchantref_prefix', 'merchantref_refund_prefix',
                     'accounting_authorized', 'accounting_payable', 'accounting_merchant',
                     'accounting_fee', 'accounting_refunds', 'accounting_payout',
                     'notifications', 'returnurl', ]
    config_readonly = ['notifications', 'returnurl', ]

    config_fieldsets = [
        {
            'id': 'adyen',
            'legend': 'Adyen',
            'fields': ['merchantaccount', 'test', ],
        },
        {
            'id': 'api',
            'legend': 'API and users',
            'fields': ['apibaseurl', 'checkoutbaseurl', 'ws_user', 'ws_password', 'ws_apikey', 'report_user', 'report_password',
                       'notify_user', 'notify_password', ],
        },
        {
            'id': 'integration',
            'legend': 'Integration',
            'fields': ['notification_receiver', 'merchantref_prefix', 'merchantref_refund_prefix', ],
        },
        {
            'id': 'accounting',
            'legend': 'Accounting',
            'fields': ['accounting_authorized', 'accounting_payable', 'accounting_merchant',
                       'accounting_fee', 'accounting_refunds', 'accounting_payout'],
        },
        {
            'id': 'adyenconf',
            'legend': 'Adyen configuration',
            'fields': ['notifications', 'returnurl', ],
        }
    ]

    def fix_fields(self):
        super(BackendAdyenCreditCardForm, self).fix_fields()
        if self.instance.id:
            self.initial.update({
                'notifications': """
In Adyen setup, select the merchant account (not the master account),
then click Notifications in the account menu. In the field for URL, enter
<code>{0}/p/adyen_notify/{1}/</code>, and pick format <code>HTTP POST</code>.""".format(
                    settings.SITEBASE,
                    self.instance.id,
                ),
                'returnurl': """
In Adyen Test setup, edit the skin, and in the field for <i>Result URL</i>
(production or test) enter <code>{0}/p/adyen_return/{1}/</code>.
If this is a production setup, you also have to <i>publish</i>
a new version of the skin.
""".format(
                    settings.SITEBASE,
                    self.instance.id,
                ),
            })


def _get_merchantaccount_choices():
    # Get all possible merchant accounts off creditcard settings
    return [('', '---')] + exec_to_list("SELECT DISTINCT config->>'merchantaccount',config->>'merchantaccount' FROM invoices_invoicepaymentmethod where classname='postgresqleu.util.payment.adyen.AdyenCreditcard'")


class BackendAdyenBanktransferForm(BackendInvoicePaymentMethodForm):
    merchantaccount = forms.ChoiceField(required=True, choices=_get_merchantaccount_choices,
                                        label="Merchant account")

    config_fields = ['merchantaccount', ]
    config_fieldsets = [
        {
            'id': 'adyen',
            'legend': 'Adyen',
            'fields': ['merchantaccount', ],
        },
    ]

    def clean_merchantaccount(self):
        n = exec_to_scalar("SELECT count(1) FROM invoices_invoicepaymentmethod WHERE classname='postgresqleu.util.payment.adyen.AdyenBanktransfer' AND config->>'merchantaccount' = %(account)s AND (id != %(self)s OR %(self)s IS NULL)", {
            'account': self.cleaned_data['merchantaccount'],
            'self': self.instance.id,
        })
        if n > 0:
            raise ValidationError("Sorry, there is already a bank transfer entry for this merchant account")
        return self.cleaned_data['merchantaccount']


class _AdyenBase(BasePayment):
    def build_payment_url(self, invoicestr, invoiceamount, invoiceid, returnurl=None):
        i = Invoice.objects.get(pk=invoiceid)
        if i.recipient_secret:
            return "/invoices/adyenpayment/{0}/{1}/{2}/".format(self.id, invoiceid, i.recipient_secret)
        else:
            return "/invoices/adyenpayment/{0}/{1}/".format(self.id, invoiceid)

    _re_adyen = re.compile('^Adyen id ([A-Z0-9]+)$')

    def _find_invoice_transaction(self, invoice):
        m = self._re_adyen.match(invoice.paymentdetails)
        if m:
            try:
                # For the IBAN method, the transaction is actually booked on our "Parent account"
                # (but the invoice is listed s paid by the banktransfer properly)
                # We still allow it to be booked on our own account directly as well, as this was
                # done in the old system.
                if isinstance(self, AdyenBanktransfer):
                    methods = (self.id,
                               InvoicePaymentMethod.objects.filter(classname="postgresqleu.util.payment.adyen.AdyenCreditcard").extra(
                                   where=["config->>'merchantaccount' = %s"],
                                   params=[self.config('merchantaccount')],
                               )[0].id,
                    )
                else:
                    methods = (self.id, )

                return (TransactionStatus.objects.get(pspReference=m.groups(1)[0], paymentmethod__in=methods), None)
            except TransactionStatus.DoesNotExist:
                return (None, "not found")
            except InvoicePaymentMethod.DoesNotExist:
                return (None, "parent not found")
        else:
            return (None, "unknown format")

    def payment_fees(self, invoice):
        (trans, reason) = self._find_invoice_transaction(invoice)
        if not trans:
            return reason

        if trans.settledamount:
            return trans.amount - trans.settledamount
        else:
            return "not settled yet"

    def autorefund(self, refund):
        (trans, reason) = self._find_invoice_transaction(refund.invoice)
        if not trans:
            raise Exception(reason)

        api = AdyenAPI(self)
        refund.payment_reference = api.refund_transaction(
            refund.id,
            trans.pspReference,
            refund.fullamount,
        )
        # At this point, we succeeded. Anything that failed will bubble
        # up as an exception.
        return True


class AdyenCreditcard(_AdyenBase):
    backend_form_class = BackendAdyenCreditCardForm
    description = """
Pay using your credit card, including Mastercard, VISA and American Express.
"""

    def used_method_details(self, invoice):
        # For credit card payments we try to figure out which type of
        # card it is as well.
        (trans, reason) = self._find_invoice_transaction(invoice)
        if not trans:
            raise Exception(reason)
        return "Credit Card ({0})".format(trans.method)


class AdyenBanktransfer(_AdyenBase):
    backend_form_class = BackendAdyenBanktransferForm
    description = """
Pay using a direct IBAN bank transfer. Due to the unreliable and slow processing
of these payments, this method is <b>not recommended</b> unless it is the only
option possible. In particular, we strongly advise not using this method if
making a payment from an account in a different currency, as amounts must be exact
and all fees covered by sender.
"""

    def __init__(self, id, method=None):
        super(AdyenBanktransfer, self).__init__(id, method)
        self.parentmethod = InvoicePaymentMethod.objects.filter(
            classname='postgresqleu.util.payment.adyen.AdyenCreditcard'
        ).extra(
            where=["config->>'merchantaccount' = %s"],
            params=[super(AdyenBanktransfer, self).config('merchantaccount')]
        )[0]
        self.parent = self.parentmethod.get_implementation()

    def config(self, param, default=None):
        # Override the config parameter, because we want to get everything *except* for the
        # payment processor id from the "parent" instead.
        if param == 'merchantaccount':
            return super(AdyenBanktransfer, self).config(param, default)
        return self.parent.config(param, default)

    def build_payment_url(self, invoicestr, invoiceamount, invoiceid, returnurl=None):
        i = Invoice.objects.get(pk=invoiceid)
        if i.recipient_secret:
            return "/invoices/adyen_bank/{0}/{1}/{2}/".format(self.id, invoiceid, i.recipient_secret)
        else:
            return "/invoices/adyen_bank/{0}/{1}/".format(self.id, invoiceid)

    def build_adyen_payment_url(self, invoicestr, invoiceamount, invoiceid):
        return super(AdyenBanktransfer, self).build_payment_url(invoicestr, invoiceamount, invoiceid) + 'iban/'

    # Override availability for direct bank transfers. We hide it if the invoice will be
    # automatically canceled in less than 4 working days.
    def available(self, invoice):
        if invoice.canceltime:
            if diff_workdays(timezone.now(), invoice.canceltime) < 5:
                return False
        return True

    def unavailable_reason(self, invoice):
        if invoice.canceltime:
            if diff_workdays(timezone.now(), invoice.canceltime) < 5:
                return "Since this invoice will be automatically canceled in less than 5 working days, it requires the use of a faster payment method."

    def used_method_details(self, invoice):
        # Bank transfers don't need any extra information
        return "IBAN bank transfers"
