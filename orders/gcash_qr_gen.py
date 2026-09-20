"""
Generates a fresh GCash payment QR image per transaction.

This does NOT talk to GCash's servers and moves no money — it encodes the
site's GCash account info + the exact order amount + a unique reference
number into a QR code image, using the free `qrcode` library. The buyer
still pays by opening their own GCash app and sending money manually; this
QR only (a) shows the correct account, (b) locks in the amount so it can't
be misread, and (c) gives staff a reference number to match against the
buyer's uploaded receipt screenshot during manual verification.

The real GCash account name/number are read from Django settings
(GCASH_ACCOUNT_NAME / GCASH_ACCOUNT_NUMBER), which should be set from
environment variables — never hardcode real account details directly in
this file.
"""
from io import BytesIO
import qrcode
from django.conf import settings


def build_gcash_qr_payload(amount, reference):
    account_name = getattr(settings, 'GCASH_ACCOUNT_NAME', 'LIKHALAYA PDL MARKET')
    account_number = getattr(settings, 'GCASH_ACCOUNT_NUMBER', '0900 000 0000')
    return (
        f"GCASH-PAY\n"
        f"To: {account_name}\n"
        f"Number: {account_number}\n"
        f"Amount: PHP {amount:.2f}\n"
        f"Ref: {reference}"
    )


def generate_gcash_qr_png(amount, reference):
    """Returns raw PNG bytes for a QR encoding this amount + reference."""
    payload = build_gcash_qr_payload(amount, reference)
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0071CE", back_color="white")
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.getvalue()