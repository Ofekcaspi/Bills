from django.db import models


class Bill(models.Model):

    category = models.CharField(max_length=100, null=True, blank=True)
    subject = models.TextField(null=True, blank=True)
    sender = models.TextField(null=True, blank=True)
    filename = models.TextField(null=True, blank=True)

    amount_value = models.FloatField(null=True, blank=True)
    amount_currency = models.CharField(max_length=10, null=True, blank=True)

    due_date_iso = models.DateField(null=True, blank=True)

    # פה תשמור נתיב יחסי בתוך downloads/, למשל "2026/01/bill.pdf"
    saved_path = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.category or '—'} | {self.subject or '—'}"
class Attachment(models.Model):
    file_hash = models.CharField(max_length=64, unique=True, db_index=True)

    message_id = models.CharField(max_length=128, db_index=True)
    attachment_id = models.CharField(max_length=256)
    thread_id = models.CharField(max_length=128, blank=True, null=True)

    subject = models.TextField(blank=True, null=True)
    sender = models.TextField(blank=True, null=True)
    msg_date = models.TextField(blank=True, null=True)
    snippet = models.TextField(blank=True, null=True)

    filename = models.TextField(blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    mime_type = models.CharField(max_length=200, blank=True, null=True)

    # שמור נתיב יחסי מתחת ל-download_root (מומלץ), למשל "חשמל/a.pdf"
    saved_path = models.TextField(blank=True, null=True)

    extracted_text_len = models.IntegerField(default=0)

    amount_value = models.FloatField(blank=True, null=True)
    amount_currency = models.CharField(max_length=10, blank=True, null=True)
    amount_source = models.CharField(max_length=50, blank=True, null=True)

    # עדיף DateField, אבל אתה מחזיר ISO string - נוח להמיר
    due_date_iso = models.DateField(blank=True, null=True, db_index=True)
    due_date_source = models.CharField(max_length=50, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)