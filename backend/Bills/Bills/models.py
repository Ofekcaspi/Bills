from django.db import models


class BillDocument(models.Model):
    # Gmail identifiers
    message_id = models.CharField(max_length=128, unique=True)
    attachment_id = models.CharField(max_length=256, blank=True, null=True)

    # Metadata
    subject = models.TextField(blank=True, null=True)
    sender = models.TextField(blank=True, null=True)
    msg_date = models.DateTimeField(blank=True, null=True)

    filename = models.TextField(blank=True, null=True)
    saved_path = models.TextField(blank=True, null=True)  # e.g. downloads/xxx.pdf

    category = models.CharField(max_length=64, blank=True, null=True)

    # Optional fields for later extraction
    amount_value = models.FloatField(blank=True, null=True)
    amount_currency = models.CharField(max_length=8, blank=True, null=True)
    due_date_iso = models.CharField(max_length=32, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def to_dict(self):
        return {
            "id": self.id,
            "message_id": self.message_id,
            "attachment_id": self.attachment_id,
            "subject": self.subject,
            "sender": self.sender,
            "msg_date": self.msg_date.isoformat() if self.msg_date else None,
            "filename": self.filename,
            "saved_path": self.saved_path,
            "category": self.category,
            "amount_value": self.amount_value,
            "amount_currency": self.amount_currency,
            "due_date_iso": self.due_date_iso,
        }
