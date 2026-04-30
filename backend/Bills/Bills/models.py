
from django.db import models
from django.conf import settings


class GmailAccount(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gmail_accounts",
    )

    google_email = models.EmailField()
    token_path = models.TextField(unique=True)

    is_active = models.BooleanField(default=True)

    last_synced_at = models.DateTimeField(blank=True, null=True)

    # New fields
    synced_from = models.DateTimeField(blank=True, null=True)
    synced_until = models.DateTimeField(blank=True, null=True)
    last_sync_window = models.CharField(max_length=32, blank=True, null=True)
    last_sync_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "google_email"],
                name="unique_google_email_per_user",
            )
        ]

    def __str__(self):
        return f"{self.user} -> {self.google_email}"
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
