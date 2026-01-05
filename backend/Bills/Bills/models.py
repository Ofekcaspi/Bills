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