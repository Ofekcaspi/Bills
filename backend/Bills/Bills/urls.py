from django.contrib import admin
from django.urls import path

from .views import (
    gmail_connect,
    sync_gmail,
    bills_list,
    bills_summary,
    bills_upcoming,
    serve_file,
    clean_db, update_bill_status,
)

urlpatterns = [
    path("admin/", admin.site.urls),

    # OAuth connect
    path("connect-email/", gmail_connect),

    # API
    path("sync/", sync_gmail),
    path("bills/", bills_list),
    path("summary/", bills_summary),
    path("upcoming/", bills_upcoming),
    path("clean-db/", clean_db),
    path("update-bill/", update_bill_status),
    # Files
    path("files/<path:path>", serve_file),
]
