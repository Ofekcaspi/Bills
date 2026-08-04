export const API_BASE = "http://127.0.0.1:8000";
export const DUE_SOON_DAYS = 14;
export const PAID_STORAGE_KEY = "bills_paid_ids_v1";
export const SUMMARY_DEFAULT = { total: 0, gmail_connected: false, connected_email: "", connected_user: "" };
export const DEFAULT_TIME_WINDOW = "365d";
export const DEFAULT_SORT_MODE = "received_desc";

export const TIME_WINDOW_OPTIONS = [
    { value: "7d", label: "7 ימים" },
    { value: "14d", label: "14 ימים" },
    { value: "30d", label: "30 ימים" },
    { value: "90d", label: "90 ימים (3 חודשים אחרונים)" },
    { value: "180d", label: "180 ימים (6 חודשים אחרונים)" },
    { value: "365d", label: "שנה (12 חודשים אחרונים)" },
];

export const TIME_WINDOW_MONTH_COUNT = {
    "90d": 3,
    "180d": 6,
    "365d": 12,
};

export const STATUS_OPTIONS = [
    { value: "all", label: "הכול" },
    { value: "unpaid", label: "לא שולם" },
    { value: "paid", label: "שולם" },
];

export const QUICK_FILTERS = [
    { value: "all", label: "הכול" },
    { value: "uncategorized", label: "ללא קטגוריה" },
    { value: "missing_amount", label: "ללא סכום" },
    { value: "has_file", label: "עם קובץ" },
];

export const SORT_OPTIONS = [
    { value: "due_asc", label: "מיון: יעד קרוב תחילה" },
    { value: "due_desc", label: "מיון: יעד רחוק תחילה" },
    { value: "amount_desc", label: "מיון: סכום גבוה תחילה" },
    { value: "amount_asc", label: "מיון: סכום נמוך תחילה" },
    { value: "received_desc", label: "מיון: התקבל לאחרונה" },
];

export const CATEGORY_CHART_COLORS = ["#2563eb", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#06b6d4", "#e11d48", "#84cc16"];
export const ANOMALY_MIN_INCREASE_RATIO = 0.5;
export const ANOMALY_MIN_PREVIOUS_AMOUNT = 80;
export const ANOMALY_MIN_DELTA_AMOUNT = 50;
export const ELECTRICITY_CATEGORY = "חשמל";
export const CONTROL_MARKS_REGEX = /[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g;
