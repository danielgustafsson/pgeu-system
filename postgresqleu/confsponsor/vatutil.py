from datetime import datetime, timedelta
import requests

from postgresqleu.invoices.models import VatValidationCache


def validate_eu_vat_number(number):
    if VatValidationCache.objects.filter(vatnumber=number, checkedat__gt=datetime.now() - timedelta(days=90)).exists():
        return None

    country = number[:2]
    numberonly = number[2:]

    try:
        r = requests.post('http://ec.europa.eu/taxation_customs/vies/vatResponse.html', data={
            'memberStateCode': country,
            'number': numberonly,
            'traderName': '',
            'traderCompanyType': '',
            'traderStreet': '',
            'traderPostalCode': '',
        }, timeout=15)
        if '<span class="validStyle">Yes, valid VAT number</span>' in r.text:
            VatValidationCache(vatnumber=number).save()
            return None
        return "Invalid VAT number according to validation service"
    except:
        return "Unable to reach validation service"
