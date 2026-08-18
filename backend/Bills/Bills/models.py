"""The database tables: connected Gmail accounts, the bills/receipts found in them, and chat history."""
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

    # Which date range of emails we've already checked, so a future sync only
    # has to fetch what's new instead of re-scanning everything.
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
    """Every bill/receipt starts as one of these; Bill and Receipt below add their own extra fields on top."""

    class DocumentType(models.TextChoices):
        BILL = "bill", "Bill"
        RECEIPT = "receipt", "Receipt"

    gmail_account = models.ForeignKey(
        GmailAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bill_documents",
    )

    document_type = models.CharField(
        max_length=16,
        choices=DocumentType.choices,
    )

    message_id = models.CharField(max_length=128)
    attachment_id = models.CharField(max_length=256, blank=True, null=True)

    subject = models.TextField(blank=True, null=True)
    sender = models.TextField(blank=True, null=True)
    msg_date = models.DateTimeField(blank=True, null=True)

    filename = models.TextField(blank=True, null=True)
    saved_path = models.TextField(blank=True, null=True)

    vendor = models.TextField(blank=True, null=True)
    category = models.CharField(max_length=64, blank=True, null=True)

    amount_value = models.FloatField(blank=True, null=True)
    amount_currency = models.CharField(max_length=8, blank=True, null=True)

    document_date = models.DateField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["gmail_account", "message_id", "attachment_id"],
                name="unique_document_per_gmail_account",
            )
        ]

    @property
    def user(self):
        return self.gmail_account.user if self.gmail_account else None

    # Django automatically adds .bill / .receipt once a row's type is set below;
    # these just return None instead of raising if it isn't that type yet.
    def get_bill_instance(self):
        try:
            return self.bill
        except Bill.DoesNotExist:
            return None

    def get_receipt_instance(self):
        try:
            return self.receipt
        except Receipt.DoesNotExist:
            return None

    def to_dict(self):
        bill = self.get_bill_instance()
        receipt = self.get_receipt_instance()

        due_date = bill.due_date if bill else None
        paid_at = receipt.paid_at if receipt else None
        payment_method = receipt.payment_method if receipt else None

        return {
            "id": self.id,
            "gmail_account": self.gmail_account.google_email if self.gmail_account else None,
            "user_id": self.user.id if self.user else None,
            "document_type": self.document_type,

            "message_id": self.message_id,
            "attachment_id": self.attachment_id,

            "subject": self.subject,
            "sender": self.sender,
            "msg_date": self.msg_date.isoformat() if self.msg_date else None,

            "filename": self.filename,
            "saved_path": self.saved_path,

            "vendor": self.vendor,
            "category": self.category,

            "amount_value": self.amount_value,
            "amount_currency": self.amount_currency,

            "document_date": self.document_date.isoformat() if self.document_date else None,

            # backwards-compatible keys
            "due_date": due_date.isoformat() if due_date else None,
            "paid_at": paid_at.isoformat() if paid_at else None,
            "payment_method": payment_method,
            "due_date_iso": due_date.isoformat() if due_date else None,
        }


class Bill(BillDocument):
    due_date = models.DateField(blank=True, null=True)

    class Meta:
        verbose_name = "Bill"
        verbose_name_plural = "Bills"

    def save(self, *args, **kwargs):
        # Always stamp the type, so this row knows it's a Bill even if it was created directly.
        self.document_type = BillDocument.DocumentType.BILL
        super().save(*args, **kwargs)

    def to_dict(self):
        data = super().to_dict()

        data.update({
            "document_type": BillDocument.DocumentType.BILL,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "due_date_iso": self.due_date.isoformat() if self.due_date else None,
        })

        return data


class Receipt(BillDocument):
    paid_at = models.DateField(blank=True, null=True)
    payment_method = models.CharField(max_length=64, blank=True, null=True)

    class Meta:
        verbose_name = "Receipt"
        verbose_name_plural = "Receipts"

    def save(self, *args, **kwargs):
        # Always stamp the type, so this row knows it's a Receipt even if it was created directly.
        self.document_type = BillDocument.DocumentType.RECEIPT
        super().save(*args, **kwargs)

    def to_dict(self):
        data = super().to_dict()

        data.update({
            "document_type": BillDocument.DocumentType.RECEIPT,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "payment_method": self.payment_method,
        })

        return data


class ChatConversation(models.Model):
    session_key = models.CharField(max_length=64, unique=True)
    # Which OpenAI reply this conversation should continue from next time.
    previous_response_id = models.CharField(max_length=128, blank=True, null=True)
    model_name = models.CharField(max_length=64, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"session={self.session_key}"


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        SYSTEM = "system", "System"

    conversation = models.ForeignKey(
        ChatConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    text = models.TextField()
    openai_response_id = models.CharField(max_length=128, blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.role} #{self.id} (conv={self.conversation_id})"
