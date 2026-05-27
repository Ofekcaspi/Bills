import { startTransition, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

const API_BASE = "http://127.0.0.1:8000";
const DUE_SOON_DAYS = 14;
const PAID_STORAGE_KEY = "bills_paid_ids_v1";
const SUMMARY_DEFAULT = { total: 0, gmail_connected: false, connected_email: "", connected_user: "" };
const DEFAULT_TIME_WINDOW = "365d";
const DEFAULT_SORT_MODE = "received_desc";

const TIME_WINDOW_OPTIONS = [
    { value: "7d", label: "7 ימים" },
    { value: "14d", label: "14 ימים" },
    { value: "30d", label: "30 ימים" },
    { value: "90d", label: "90 ימים (3 חודשים אחרונים)" },
    { value: "180d", label: "180 ימים (6 חודשים אחרונים)" },
    { value: "365d", label: "שנה (12 חודשים אחרונים)" },
];

const TIME_WINDOW_MONTH_COUNT = {
    "90d": 3,
    "180d": 6,
    "365d": 12,
};

const STATUS_OPTIONS = [
    { value: "all", label: "הכול" },
    { value: "unpaid", label: "לא שולם" },
    { value: "paid", label: "שולם" },
];

const QUICK_FILTERS = [
    { value: "all", label: "הכול" },
    { value: "uncategorized", label: "ללא קטגוריה" },
    { value: "missing_amount", label: "ללא סכום" },
    { value: "has_file", label: "עם קובץ" },
];

const SORT_OPTIONS = [
    { value: "due_asc", label: "מיון: יעד קרוב תחילה" },
    { value: "due_desc", label: "מיון: יעד רחוק תחילה" },
    { value: "amount_desc", label: "מיון: סכום גבוה תחילה" },
    { value: "amount_asc", label: "מיון: סכום נמוך תחילה" },
    { value: "received_desc", label: "מיון: התקבל לאחרונה" },
];

const CATEGORY_CHART_COLORS = ["#2563eb", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#06b6d4", "#e11d48", "#84cc16"];
const ANOMALY_MIN_INCREASE_RATIO = 0.5;
const ANOMALY_MIN_PREVIOUS_AMOUNT = 80;
const ANOMALY_MIN_DELTA_AMOUNT = 50;
const ELECTRICITY_CATEGORY = "\u05d7\u05e9\u05de\u05dc";
const CONTROL_MARKS_REGEX = /[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g;

function toNumber(value) {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function timeWindowDays(value) {
    const match = /^(\d+)d$/.exec(String(value || ""));
    if (!match) return null;
    const days = Number(match[1]);
    return Number.isFinite(days) && days > 0 ? days : null;
}

function parseDate(value) {
    if (!value) return null;
    const date = value instanceof Date ? value : new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
}

function formatDate(value) {
    if (!value) return "—";
    const date = parseDate(value);
    if (!date) return String(value);
    return date.toLocaleDateString("he-IL");
}

function daysBetween(fromDate, toDate) {
    const msPerDay = 1000 * 60 * 60 * 24;
    return Math.ceil((toDate.getTime() - fromDate.getTime()) / msPerDay);
}

function monthKey(date) {
    if (!date) return "";
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function monthLabel(key) {
    if (!key) return "";
    const [year, month] = key.split("-").map(Number);
    const date = new Date(year, month - 1, 1);
    return date.toLocaleDateString("he-IL", { month: "short", year: "2-digit" });
}

function buildRecentMonthKeys(count) {
    const safeCount = Math.max(0, Number(count) || 0);
    const now = new Date();
    return Array.from({ length: safeCount }, (_, index) => {
        const shift = safeCount - index - 1;
        const date = new Date(now.getFullYear(), now.getMonth() - shift, 1);
        return monthKey(date);
    });
}

function stableItemId(item) {
    return String(item.message_id ?? item.id ?? item.filename ?? "");
}

function filenameFromContentDisposition(headerValue) {
    if (!headerValue) return "";

    const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(headerValue);
    if (utf8Match?.[1]) {
        try {
            return decodeURIComponent(utf8Match[1]);
        } catch {
            return utf8Match[1];
        }
    }

    const fallbackMatch = /filename="?([^"]+)"?/i.exec(headerValue);
    return fallbackMatch?.[1] || "";
}

function money(value, currency = "") {
    if (value === null || value === undefined || value === "") return "—";
    const num = Number(value);
    if (!Number.isFinite(num)) return `${value} ${currency}`.trim();
    const formatted = new Intl.NumberFormat("he-IL", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(num);
    return `${formatted} ${currency}`.trim();
}

function fileUrlFromSavedPath(savedPath) {
    if (!savedPath) return "";
    const normalized = savedPath.replaceAll("\\", "/");
    const relative = normalized.replace(/^downloads\//, "");
    return `${API_BASE}/files/${encodeURI(relative)}`;
}

function getBillStatus(item) {
    if (item.isPaid) return { tone: "paid", label: "שולם" };
    return { tone: "unpaid", label: "לא שולם" };
}

function senderDisplay(value) {
    if (!value) return "שולח לא זוהה";
    const cleaned = String(value).replace(/<[^>]+>/g, "").trim();
    return cleaned || String(value);
}

function senderInitials(value) {
    const label = senderDisplay(value);
    const tokens = label
        .split(/[\s._-]+/)
        .filter(Boolean)
        .slice(0, 2);
    if (!tokens.length) return "?";
    return tokens.map((token) => token[0]).join("").toUpperCase();
}

function normalizeCategoryLabel(value) {
    return String(value || "").replace(CONTROL_MARKS_REGEX, "").trim();
}

function isElectricityCategory(value) {
    return normalizeCategoryLabel(value) === ELECTRICITY_CATEGORY;
}

function useAnimatedNumber(target, { duration = 700, decimals = 0 } = {}) {
    const safeTarget = Number.isFinite(target) ? target : 0;
    const [value, setValue] = useState(safeTarget);
    const previousTarget = useRef(safeTarget);

    useEffect(() => {
        const from = Number.isFinite(previousTarget.current) ? previousTarget.current : 0;
        const to = safeTarget;
        previousTarget.current = to;

        if (Math.abs(to - from) < 0.001) {
            setValue(to);
            return undefined;
        }

        let rafId = 0;
        let startTs = 0;

        const tick = (ts) => {
            if (!startTs) startTs = ts;
            const elapsed = ts - startTs;
            const progress = Math.min(elapsed / duration, 1);
            const eased = 1 - (1 - progress) * (1 - progress);
            const nextValue = from + (to - from) * eased;
            setValue(nextValue);
            if (progress < 1) {
                rafId = window.requestAnimationFrame(tick);
            }
        };

        rafId = window.requestAnimationFrame(tick);
        return () => window.cancelAnimationFrame(rafId);
    }, [safeTarget, duration]);

    if (decimals > 0) return Number(value.toFixed(decimals));
    return Math.round(value);
}

export default function App() {
    const [items, setItems] = useState([]);
    const [summary, setSummary] = useState(SUMMARY_DEFAULT);
    const [screen, setScreen] = useState("home");

    const [search, setSearch] = useState("");
    const [category, setCategory] = useState("all");
    const [statusFilter, setStatusFilter] = useState("all");
    const [quickFilter, setQuickFilter] = useState("all");
    const [sortMode, setSortMode] = useState(DEFAULT_SORT_MODE);
    const [timeWindow, setTimeWindow] = useState(DEFAULT_TIME_WINDOW);
    const [reportSearch, setReportSearch] = useState("");
    const [reportCategory, setReportCategory] = useState("all");
    const [reportStatusFilter, setReportStatusFilter] = useState("all");
    const [reportQuickFilter, setReportQuickFilter] = useState("all");
    const [reportSortMode, setReportSortMode] = useState(DEFAULT_SORT_MODE);
    const [reportTimeWindow, setReportTimeWindow] = useState(DEFAULT_TIME_WINDOW);
    const [analysisCategory, setAnalysisCategory] = useState("all");
    const [analysisMonthFilter, setAnalysisMonthFilter] = useState("");
    const [analysisTimeWindow, setAnalysisTimeWindow] = useState(DEFAULT_TIME_WINDOW);

    const [paidIds, setPaidIds] = useState(() => new Set());
    const [loading, setLoading] = useState(true);
    const [syncing, setSyncing] = useState(false);
    const [exportingReport, setExportingReport] = useState(false);
    const [isSyncModalOpen, setIsSyncModalOpen] = useState(false);
    const [syncTimeWindow, setSyncTimeWindow] = useState(DEFAULT_TIME_WINDOW);
    const [error, setError] = useState("");
    const [reportError, setReportError] = useState("");
    const [toastMessage, setToastMessage] = useState("");
    const [chatInput, setChatInput] = useState("");
    const [chatSending, setChatSending] = useState(false);
    const [chatError, setChatError] = useState("");
    const [chatPreviousResponseId, setChatPreviousResponseId] = useState("");
    const [isPageScrolled, setIsPageScrolled] = useState(false);
    const [chatMessages, setChatMessages] = useState([
        {
            role: "assistant",
            text: "אפשר לשאול אותי על ההוצאות שלך. לדוגמה: כמה הוצאתי החודש על חשמל לעומת החודש הקודם?",
        },
    ]);
    const syncPopoverRef = useRef(null);
    const chatMessagesRef = useRef(null);

    const deferredSearch = useDeferredValue(search);
    const deferredReportSearch = useDeferredValue(reportSearch);
    const isHomeScreen = screen === "home";
    const isAnalysisChartsScreen = screen === "analysis_charts";
    const isAnalysisBillsScreen = screen === "analysis_bills";
    const isReportsScreen = screen === "reports";

    useEffect(() => {
        try {
            const saved = localStorage.getItem(PAID_STORAGE_KEY);
            if (!saved) return;
            const parsed = JSON.parse(saved);
            if (Array.isArray(parsed)) {
                setPaidIds(new Set(parsed.map(String)));
            }
        } catch {
            // ignore localStorage parsing issues
        }
    }, []);

    useEffect(() => {
        if (!toastMessage) return undefined;
        const timer = window.setTimeout(() => setToastMessage(""), 2800);
        return () => window.clearTimeout(timer);
    }, [toastMessage]);

    useEffect(() => {
        if (!chatMessagesRef.current) return;
        chatMessagesRef.current.scrollTop = chatMessagesRef.current.scrollHeight;
    }, [chatMessages, chatSending]);

    useEffect(() => {
        if (!isSyncModalOpen) return undefined;

        const handlePointerDown = (event) => {
            if (syncPopoverRef.current && !syncPopoverRef.current.contains(event.target)) {
                closeSyncModal();
            }
        };

        const handleKeyDown = (event) => {
            if (event.key === "Escape") {
                closeSyncModal();
            }
        };

        document.addEventListener("mousedown", handlePointerDown);
        document.addEventListener("keydown", handleKeyDown);
        return () => {
            document.removeEventListener("mousedown", handlePointerDown);
            document.removeEventListener("keydown", handleKeyDown);
        };
    }, [isSyncModalOpen, syncing]);

    function updatePaidIds(updater) {
        setPaidIds((prev) => {
            const next = updater(prev);
            try {
                localStorage.setItem(PAID_STORAGE_KEY, JSON.stringify(Array.from(next)));
            } catch {
                // ignore localStorage write issues
            }
            return next;
        });
    }

    function togglePaidById(itemId, subject) {
        const isNowPaid = !paidIds.has(itemId);

        updatePaidIds((prev) => {
            const next = new Set(prev);
            if (next.has(itemId)) {
                next.delete(itemId);
            } else {
                next.add(itemId);
            }
            return next;
        });

        setToastMessage(isNowPaid ? `סומן כשולם: ${subject || "ללא נושא"}` : `בוטל סטטוס שולם: ${subject || "ללא נושא"}`);
    }

    function createReminder(item) {
        const subject = item.subject || item.filename || "חשבון";
        const dueText = formatDate(item.dueDate);
        setToastMessage(`תזכורת מקומית נוצרה עבור ${subject} (יעד: ${dueText})`);
    }

    async function sendChatMessage() {
        const message = chatInput.trim();
        if (!message || chatSending) return;

        setChatInput("");
        setChatError("");
        setChatMessages((prev) => [...prev, { role: "user", text: message }]);
        setChatSending(true);

        try {
            const res = await fetch(`${API_BASE}/chat/`, {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message,
                    previous_response_id: chatPreviousResponseId || null,
                }),
            });

            let payload = null;
            try {
                payload = await res.json();
            } catch {
                payload = null;
            }

            if (!res.ok || !payload?.ok) {
                const messageText = payload?.error || `Chat API error: ${res.status}`;
                throw new Error(messageText);
            }

            const answer = String(payload.answer || "").trim() || "לא התקבלה תשובה.";
            setChatMessages((prev) => [...prev, { role: "assistant", text: answer }]);
            setChatPreviousResponseId(payload.response_id || "");
        } catch (e) {
            const messageText = e?.message || "שליחת הודעה נכשלה";
            setChatError(messageText);
            setChatMessages((prev) => [
                ...prev,
                { role: "assistant", text: `אירעה שגיאה: ${messageText}` },
            ]);
        } finally {
            setChatSending(false);
        }
    }

    async function loadDashboard() {
        try {
            setLoading(true);
            setError("");

            const [billsRes, sumRes] = await Promise.all([
                fetch(`${API_BASE}/bills/`, { credentials: "include" }),
                fetch(`${API_BASE}/summary/`, { credentials: "include" }),
            ]);

            if (!billsRes.ok) throw new Error(`Bills API error: ${billsRes.status}`);
            if (!sumRes.ok) throw new Error(`Summary API error: ${sumRes.status}`);

            const [billsData, sumData] = await Promise.all([billsRes.json(), sumRes.json()]);

            startTransition(() => {
                setItems(Array.isArray(billsData?.items) ? billsData.items : []);
                setSummary({ ...SUMMARY_DEFAULT, ...(sumData || {}) });
            });
        } catch (e) {
            setError(e?.message || "Failed to load data");
        } finally {
            setLoading(false);
        }
    }

    function openSyncModal() {
        setSyncTimeWindow(timeWindow || DEFAULT_TIME_WINDOW);
        setIsSyncModalOpen(true);
    }

    function closeSyncModal() {
        if (syncing) return;
        setIsSyncModalOpen(false);
    }

    async function syncNow(windowValue = timeWindow) {
        try {
            setSyncing(true);
            setError("");

            const res = await fetch(`${API_BASE}/sync/`, {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ max_results: 100, time_window: windowValue }),
            });

            if (res.status === 401) {
                window.location.href = `${API_BASE}/connect-email/`;
                return;
            }

            if (!res.ok) {
                const text = await res.text().catch(() => "");
                throw new Error(`Sync failed: ${res.status} ${text}`);
            }

            setToastMessage("הסנכרון הסתיים בהצלחה");
            await loadDashboard();
        } catch (e) {
            setError(e?.message || "Sync failed");
        } finally {
            setSyncing(false);
        }
    }

    async function confirmSyncNow() {
        const selectedWindow = syncTimeWindow || DEFAULT_TIME_WINDOW;
        setIsSyncModalOpen(false);
        await syncNow(selectedWindow);
    }

    async function cleanDatabase() {
        const confirmed = window.confirm("פעולה זו תמחק את הנתונים בטבלת החשבונות. להמשיך?");
        if (!confirmed) return;

        try {
            const res = await fetch(`${API_BASE}/clean-db/`, {
                method: "DELETE",
                credentials: "include",
            });

            const payload = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(payload?.error || `Clean DB failed: ${res.status}`);
            }

            setToastMessage("המסד נוקה בהצלחה");
            await loadDashboard();
        } catch (e) {
            setError(e?.message || "Clean DB failed");
        }
    }

    async function exportReceiptsReport() {
        const selectedIds = reportExportableFilteredItems
            .map((item) => Number(item.id))
            .filter((id) => Number.isFinite(id));

        if (!selectedIds.length) {
            setReportError("לא נמצאו קבצים להפקה לפי החיפוש הנוכחי.");
            return;
        }

        try {
            setExportingReport(true);
            setReportError("");

            const res = await fetch(`${API_BASE}/reports/export/`, {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ document_ids: selectedIds }),
            });

            if (!res.ok) {
                let message = `Report export failed: ${res.status}`;
                try {
                    const payload = await res.json();
                    if (payload?.error) {
                        message = payload.error;
                    }
                } catch {
                    const text = await res.text().catch(() => "");
                    if (text) message = text;
                }
                throw new Error(message);
            }

            const blob = await res.blob();
            const disposition = res.headers.get("Content-Disposition");
            const downloadName = filenameFromContentDisposition(disposition) || `receipts_report_${Date.now()}.zip`;

            const objectUrl = window.URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = objectUrl;
            link.download = downloadName;
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(objectUrl);

            setToastMessage(`הדוח הופק בהצלחה (${selectedIds.length} קבצים).`);
        } catch (e) {
            setReportError(e?.message || "הפקת הדוח נכשלה.");
        } finally {
            setExportingReport(false);
        }
    }

    function clearFilters() {
        setSearch("");
        setCategory("all");
        setStatusFilter("all");
        setQuickFilter("all");
        setSortMode(DEFAULT_SORT_MODE);
        setTimeWindow(DEFAULT_TIME_WINDOW);
    }

    function clearReportFilters() {
        setReportSearch("");
        setReportCategory("all");
        setReportStatusFilter("all");
        setReportQuickFilter("all");
        setReportSortMode(DEFAULT_SORT_MODE);
        setReportTimeWindow(DEFAULT_TIME_WINDOW);
    }

    useEffect(() => {
        loadDashboard();
    }, []);

    useEffect(() => {
        const handleScroll = () => {
            setIsPageScrolled(window.scrollY > 8);
        };

        handleScroll();
        window.addEventListener("scroll", handleScroll, { passive: true });

        return () => {
            window.removeEventListener("scroll", handleScroll);
        };
    }, []);

    useEffect(() => {
        if (!isReportsScreen) {
            setReportError("");
        }
    }, [isReportsScreen]);

    const normalizedItems = useMemo(() => {
        const now = new Date();

        const mappedItems = items.map((item) => {
            const amount = toNumber(item.amount_value);
            const dueDate = parseDate(item.due_date_iso);
            const msgDate = parseDate(item.msg_date);
            const daysToDue = dueDate ? daysBetween(now, dueDate) : null;
            const id = stableItemId(item);

            return {
                ...item,
                stableId: id,
                amount,
                dueDate,
                msgDate,
                daysToDue,
                isOverdue: daysToDue !== null && daysToDue < 0,
                isDueSoon: daysToDue !== null && daysToDue >= 0 && daysToDue <= DUE_SOON_DAYS,
                isPaid: item.document_type === "receipt",
            };
        });

        const seenElectricityBills = new Set();
        return mappedItems.filter((item) => {
            if (!isElectricityCategory(item.category)) return true;
            if (item.document_type !== "bill") return true;
            if (item.amount === null) return true;

            const duplicateKey = `${item.amount.toFixed(2)}|${item.amount_currency || ""}`;
            if (seenElectricityBills.has(duplicateKey)) {
                return false;
            }

            seenElectricityBills.add(duplicateKey);
            return true;
        });
    }, [items, paidIds]);

    const categories = useMemo(() => {
        const set = new Set(normalizedItems.map((item) => item.category).filter(Boolean));
        return Array.from(set).sort((a, b) => a.localeCompare(b, "he"));
    }, [normalizedItems]);

    const filteredItems = useMemo(() => {
        const query = deferredSearch.trim().toLowerCase();
        const windowDays = timeWindowDays(timeWindow);
        const nowTs = Date.now();
        const cutoffTs = windowDays === null ? null : nowTs - windowDays * 24 * 60 * 60 * 1000;

        const filtered = normalizedItems.filter((item) => {
            if (category !== "all" && item.category !== category) return false;

            if (statusFilter === "unpaid" && item.isPaid) return false;
            if (statusFilter === "paid" && !item.isPaid) return false;

            if (quickFilter === "high_amount" && (item.amount === null || item.amount < 500)) return false;
            if (quickFilter === "uncategorized" && item.category) return false;
            if (quickFilter === "missing_amount" && item.amount !== null) return false;
            if (quickFilter === "has_file" && !item.saved_path) return false;

            if (cutoffTs !== null) {
                const anchor = item.msgDate || item.dueDate;
                if (!anchor) return false;
                const anchorTs = anchor.getTime();
                if (anchorTs < cutoffTs || anchorTs > nowTs) return false;
            }

            if (query) {
                const haystack = `${item.subject || ""} ${item.sender || ""} ${item.filename || ""} ${item.category || ""}`.toLowerCase();
                if (!haystack.includes(query)) return false;
            }

            return true;
        });

        return filtered.sort((a, b) => {
            if (sortMode === "amount_desc" || sortMode === "amount_asc") {
                const aAmount = a.amount ?? (sortMode === "amount_desc" ? -Infinity : Infinity);
                const bAmount = b.amount ?? (sortMode === "amount_desc" ? -Infinity : Infinity);
                return sortMode === "amount_desc" ? bAmount - aAmount : aAmount - bAmount;
            }

            if (sortMode === "received_desc") {
                const aDate = a.msgDate ? a.msgDate.getTime() : 0;
                const bDate = b.msgDate ? b.msgDate.getTime() : 0;
                return bDate - aDate;
            }

            if (a.isPaid !== b.isPaid) return a.isPaid ? 1 : -1;
            if (a.isOverdue !== b.isOverdue) return a.isOverdue ? -1 : 1;
            if (a.isDueSoon !== b.isDueSoon) return a.isDueSoon ? -1 : 1;

            const aDue = a.dueDate ? a.dueDate.getTime() : Number.MAX_SAFE_INTEGER;
            const bDue = b.dueDate ? b.dueDate.getTime() : Number.MAX_SAFE_INTEGER;
            return sortMode === "due_desc" ? bDue - aDue : aDue - bDue;
        });
    }, [
        normalizedItems,
        deferredSearch,
        category,
        statusFilter,
        quickFilter,
        sortMode,
        timeWindow,
    ]);

    const reportFilteredItems = useMemo(() => {
        const query = deferredReportSearch.trim().toLowerCase();
        const windowDays = timeWindowDays(reportTimeWindow);
        const nowTs = Date.now();
        const cutoffTs = windowDays === null ? null : nowTs - windowDays * 24 * 60 * 60 * 1000;

        const filtered = normalizedItems.filter((item) => {
            if (reportCategory !== "all" && item.category !== reportCategory) return false;

            if (reportStatusFilter === "unpaid" && item.isPaid) return false;
            if (reportStatusFilter === "paid" && !item.isPaid) return false;

            if (reportQuickFilter === "high_amount" && (item.amount === null || item.amount < 500)) return false;
            if (reportQuickFilter === "uncategorized" && item.category) return false;
            if (reportQuickFilter === "missing_amount" && item.amount !== null) return false;
            if (reportQuickFilter === "has_file" && !item.saved_path) return false;

            if (cutoffTs !== null) {
                const anchor = item.msgDate || item.dueDate;
                if (!anchor) return false;
                const anchorTs = anchor.getTime();
                if (anchorTs < cutoffTs || anchorTs > nowTs) return false;
            }

            if (query) {
                const haystack = `${item.subject || ""} ${item.sender || ""} ${item.filename || ""} ${item.category || ""}`.toLowerCase();
                if (!haystack.includes(query)) return false;
            }

            return true;
        });

        return filtered.sort((a, b) => {
            if (reportSortMode === "amount_desc" || reportSortMode === "amount_asc") {
                const aAmount = a.amount ?? (reportSortMode === "amount_desc" ? -Infinity : Infinity);
                const bAmount = b.amount ?? (reportSortMode === "amount_desc" ? -Infinity : Infinity);
                return reportSortMode === "amount_desc" ? bAmount - aAmount : aAmount - bAmount;
            }

            if (reportSortMode === "received_desc") {
                const aDate = a.msgDate ? a.msgDate.getTime() : 0;
                const bDate = b.msgDate ? b.msgDate.getTime() : 0;
                return bDate - aDate;
            }

            if (a.isPaid !== b.isPaid) return a.isPaid ? 1 : -1;
            if (a.isOverdue !== b.isOverdue) return a.isOverdue ? -1 : 1;
            if (a.isDueSoon !== b.isDueSoon) return a.isDueSoon ? -1 : 1;

            const aDue = a.dueDate ? a.dueDate.getTime() : Number.MAX_SAFE_INTEGER;
            const bDue = b.dueDate ? b.dueDate.getTime() : Number.MAX_SAFE_INTEGER;
            return reportSortMode === "due_desc" ? bDue - aDue : aDue - bDue;
        });
    }, [
        normalizedItems,
        deferredReportSearch,
        reportCategory,
        reportStatusFilter,
        reportQuickFilter,
        reportSortMode,
        reportTimeWindow,
    ]);

    const reportExportableFilteredItems = useMemo(
        () => reportFilteredItems.filter((item) => item.saved_path),
        [reportFilteredItems],
    );

    const stats = useMemo(() => {
        const visibleAmount = filteredItems.reduce((acc, item) => acc + (item.amount ?? 0), 0);
        const pendingCount = filteredItems.filter((item) => !item.isPaid).length;
        const paidCount = filteredItems.filter((item) => item.isPaid).length;

        return {
            visibleAmount,
            pendingCount,
            paidCount,
            apiTotal: Number(summary?.total || 0),
        };
    }, [filteredItems, summary]);

    const homeStats = useMemo(() => {
        const pendingCount = normalizedItems.filter((item) => !item.isPaid).length;
        const paidCount = normalizedItems.filter((item) => item.isPaid).length;

        return {
            pendingCount,
            paidCount,
            apiTotal: Number(summary?.total || 0),
        };
    }, [normalizedItems, summary]);

    const monthlySourceItems = useMemo(() => {
        const windowDays = timeWindowDays(analysisTimeWindow);
        const nowTs = Date.now();
        const cutoffTs = windowDays === null ? null : nowTs - windowDays * 24 * 60 * 60 * 1000;

        return normalizedItems.filter((item) => {
            if (analysisCategory !== "all" && item.category !== analysisCategory) return false;

            if (cutoffTs === null) return true;
            const anchor = item.msgDate || item.dueDate;
            if (!anchor) return false;
            const anchorTs = anchor.getTime();
            return anchorTs >= cutoffTs && anchorTs <= nowTs;
        });
    }, [normalizedItems, analysisCategory, analysisTimeWindow]);

    const monthlySeries = useMemo(() => {
        const totals = new Map();

        monthlySourceItems.forEach((item) => {
            if (item.amount === null) return;
            const anchor = item.msgDate || item.dueDate;
            if (!anchor) return;
            const key = monthKey(anchor);
            totals.set(key, (totals.get(key) || 0) + item.amount);
        });

        const fixedMonthCount = TIME_WINDOW_MONTH_COUNT[analysisTimeWindow] ?? null;
        const keys = fixedMonthCount ? buildRecentMonthKeys(fixedMonthCount) : Array.from(totals.keys()).sort();

        return keys.map((key) => ({
            key,
            label: monthLabel(key),
            total: totals.get(key) || 0,
        }));
    }, [monthlySourceItems, analysisTimeWindow]);

    const maxChartValue = useMemo(() => {
        if (!monthlySeries.length) return 0;
        return monthlySeries.reduce((max, bucket) => Math.max(max, bucket.total), 0);
    }, [monthlySeries]);

    const chartPoints = useMemo(() => {
        if (!monthlySeries.length) {
            return [];
        }

        const maxValue = maxChartValue || 1;
        const minX = 6;
        const maxX = 94;
        const minY = 12;
        const maxY = 88;
        const spanX = maxX - minX;
        const spanY = maxY - minY;

        return monthlySeries.map((bucket, index) => {
            const x =
                monthlySeries.length === 1
                    ? 50
                    : maxX - (index / (monthlySeries.length - 1)) * spanX;
            const ratio = Math.max(0, Math.min(1, bucket.total / maxValue));
            const y = maxY - ratio * spanY;

            return { ...bucket, x, y };
        });
    }, [monthlySeries, maxChartValue]);

    const chartLinePath = useMemo(() => {
        if (!chartPoints.length) return "";
        return chartPoints
            .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
            .join(" ");
    }, [chartPoints]);

    const chartAreaPath = useMemo(() => {
        if (!chartPoints.length) return "";
        const first = chartPoints[0];
        const last = chartPoints[chartPoints.length - 1];
        return `${chartLinePath} L ${last.x} 88 L ${first.x} 88 Z`;
    }, [chartPoints, chartLinePath]);

    const chartCanvasHeight = useMemo(() => {
        if (!chartPoints.length) return 220;
        if (chartPoints.length >= 12) return 250;
        if (chartPoints.length >= 9) return 236;
        return Math.max(210, Math.min(248, 188 + chartPoints.length * 7));
    }, [chartPoints]);

    const isDenseMonthlyChart = chartPoints.length >= 10;

    const chartAxisStep = useMemo(() => {
        if (chartPoints.length >= 12) return 2;
        if (chartPoints.length >= 9) return 2;
        return 1;
    }, [chartPoints.length]);

    const visibleAxisPoints = useMemo(() => {
        if (!chartPoints.length) return [];
        if (chartAxisStep === 1) return chartPoints;

        return chartPoints.filter((point, index) => {
            if (analysisMonthFilter === point.key) return true;
            if (index === 0 || index === chartPoints.length - 1) return true;
            return index % chartAxisStep === 0;
        });
    }, [chartPoints, chartAxisStep, analysisMonthFilter]);

    const analysisFilteredItems = useMemo(() => {
        if (!analysisMonthFilter) return monthlySourceItems;
        return monthlySourceItems.filter((item) => {
            const key = monthKey(item.msgDate || item.dueDate);
            return key === analysisMonthFilter;
        });
    }, [monthlySourceItems, analysisMonthFilter]);

    const analysisStats = useMemo(() => {
        const visibleAmount = analysisFilteredItems.reduce((acc, item) => acc + (item.amount ?? 0), 0);
        const pendingCount = analysisFilteredItems.filter((item) => !item.isPaid).length;
        const paidCount = analysisFilteredItems.filter((item) => item.isPaid).length;

        return {
            visibleAmount,
            pendingCount,
            paidCount,
            apiTotal: Number(summary?.total || 0),
        };
    }, [analysisFilteredItems, summary]);

    useEffect(() => {
        if (!analysisMonthFilter) return;
        if (monthlySeries.some((bucket) => bucket.key === analysisMonthFilter)) return;
        setAnalysisMonthFilter("");
    }, [monthlySeries, analysisMonthFilter]);

    const recentItems = useMemo(() => {
        return [...normalizedItems]
            .sort((a, b) => {
                const aDate = a.msgDate ? a.msgDate.getTime() : 0;
                const bDate = b.msgDate ? b.msgDate.getTime() : 0;
                return bDate - aDate;
            })
            .slice(0, 8);
    }, [normalizedItems]);

    const categorySeries = useMemo(() => {
        const grouped = new Map();

        analysisFilteredItems.forEach((item) => {
            const key = item.category || "ללא קטגוריה";
            const current = grouped.get(key) || { category: key, total: 0, count: 0 };
            current.total += item.amount ?? 0;
            current.count += 1;
            grouped.set(key, current);
        });

        return Array.from(grouped.values())
            .sort((a, b) => b.total - a.total)
            .slice(0, 8);
    }, [analysisFilteredItems]);

    const categoryChart = useMemo(() => {
        const slicesSource = categorySeries.filter((entry) => entry.total > 0);
        const total = slicesSource.reduce((sum, entry) => sum + entry.total, 0);

        if (!total) {
            return { total: 0, slices: [] };
        }

        const radius = 70;
        const circumference = 2 * Math.PI * radius;
        let offset = 0;

        const slices = slicesSource.map((entry, index) => {
            const ratio = entry.total / total;
            const segment = circumference * ratio;

            const slice = {
                ...entry,
                color: CATEGORY_CHART_COLORS[index % CATEGORY_CHART_COLORS.length],
                percent: ratio * 100,
                dasharray: `${segment} ${Math.max(circumference - segment, 0)}`,
                dashoffset: -offset,
            };
            offset += segment;
            return slice;
        });

        return { total, slices };
    }, [categorySeries]);

    const categoryLegendItems = useMemo(() => {
        return categoryChart.slices.map((slice) => ({
            category: slice.category,
            count: slice.count,
            total: slice.total,
            percent: slice.percent,
            color: slice.color,
        }));
    }, [categoryChart]);

    const anomalyInsight = useMemo(() => {
        const groupedByCategory = new Map();

        monthlySourceItems.forEach((item) => {
            if (!item.category) return;
            if (item.amount === null || item.amount <= 0) return;

            const anchor = item.msgDate || item.dueDate;
            if (!anchor) return;

            const categoryItems = groupedByCategory.get(item.category) || [];
            categoryItems.push({ amount: item.amount, anchor });
            groupedByCategory.set(item.category, categoryItems);
        });

        let bestCandidate = null;

        groupedByCategory.forEach((entries, categoryName) => {
            if (entries.length < 2) return;

            const sorted = [...entries].sort((a, b) => b.anchor.getTime() - a.anchor.getTime());
            const latest = sorted[0];
            const previous = sorted[1];

            if (!latest || !previous) return;

            const delta = latest.amount - previous.amount;
            if (delta <= 0) return;
            if (previous.amount < ANOMALY_MIN_PREVIOUS_AMOUNT) return;
            if (delta < ANOMALY_MIN_DELTA_AMOUNT) return;

            const ratio = delta / previous.amount;
            if (ratio < ANOMALY_MIN_INCREASE_RATIO) return;

            const candidate = {
                category: categoryName,
                latestAmount: latest.amount,
                previousAmount: previous.amount,
                latestDate: latest.anchor,
                previousDate: previous.anchor,
                delta,
                ratio,
            };

            if (
                !bestCandidate ||
                candidate.ratio > bestCandidate.ratio ||
                (candidate.ratio === bestCandidate.ratio && candidate.delta > bestCandidate.delta)
            ) {
                bestCandidate = candidate;
            }
        });

        return bestCandidate;
    }, [monthlySourceItems]);

    const analysisViewItems = isAnalysisBillsScreen ? filteredItems : analysisFilteredItems;
    const analysisViewStats = isAnalysisBillsScreen ? stats : analysisStats;
    const animatedHomeBillsCount = useAnimatedNumber(normalizedItems.length);
    const animatedHomeTotal = useAnimatedNumber(homeStats.apiTotal, { decimals: 2 });
    const animatedHomePaidCount = useAnimatedNumber(homeStats.paidCount);
    const animatedHomePendingCount = useAnimatedNumber(homeStats.pendingCount);
    const animatedAnalysisBillsCount = useAnimatedNumber(analysisViewItems.length);
    const animatedAnalysisVisibleAmount = useAnimatedNumber(analysisViewStats.visibleAmount, { decimals: 2 });
    const animatedAnalysisPaidCount = useAnimatedNumber(analysisViewStats.paidCount);
    const animatedAnalysisPendingCount = useAnimatedNumber(analysisViewStats.pendingCount);

    return (
        <div
            className={`page ${isPageScrolled ? "isScrolled" : ""} ${isAnalysisChartsScreen ? "analysisChartsPage" : ""}`}
            dir="rtl"
            lang="he"
        >
            <header className="topbar">
                <div className="container topbarInner">
                    <div className="projectLogoWrap">
                        <img className="projectLogo" src="/BILLSLOGO.jpg" alt="Bills logo" />
                    </div>

                    <div className="topActions" ref={syncPopoverRef}>
                        <button className="btnPrimary syncMainButton" onClick={openSyncModal} disabled={syncing}>
                            {syncing ? "מסנכרן..." : "🔄 סנכרן חשבוניות"}
                        </button>

                        {isSyncModalOpen && (
                            <section className="syncPopover" role="dialog" aria-label="בחירת תקופת סנכרון">
                                <label className="syncPopoverField">
                                    <span>תקופת זמן</span>
                                    <select
                                        className="select"
                                        value={syncTimeWindow}
                                        onChange={(event) => setSyncTimeWindow(event.target.value)}
                                        disabled={syncing}
                                    >
                                        {TIME_WINDOW_OPTIONS.map((option) => (
                                            <option key={`sync-time-${option.value}`} value={option.value}>
                                                {option.label}
                                            </option>
                                        ))}
                                    </select>
                                </label>

                                <div className="syncPopoverActions">
                                    <button className="btnGhost small" onClick={closeSyncModal} disabled={syncing}>
                                        ביטול
                                    </button>
                                    <button className="btnPrimary small" onClick={confirmSyncNow} disabled={syncing}>
                                        סנכרן
                                    </button>
                                </div>
                            </section>
                        )}
                    </div>
                </div>
            <aside className="sideNav" aria-label="ניווט ראשי">
                <button
                    className={`sideNavButton ${isHomeScreen ? "active" : ""}`}
                    onClick={() => setScreen("home")}
                    aria-current={isHomeScreen ? "page" : undefined}
                >
                    <span className="sideNavIcon" aria-hidden="true">
                        <svg className="sideNavIconSvg" viewBox="0 0 24 24">
                            <path d="M3 10.5L12 3l9 7.5" />
                            <path d="M5 9.5V21h14V9.5" />
                            <path d="M10 21v-6h4v6" />
                        </svg>
                    </span>
                    <span className="sideNavLabel">בית</span>
                </button>

                <button
                    className={`sideNavButton ${isAnalysisBillsScreen ? "active" : ""}`}
                    onClick={() => setScreen("analysis_bills")}
                    aria-current={isAnalysisBillsScreen ? "page" : undefined}
                >
                    <span className="sideNavIcon" aria-hidden="true">
                        <svg className="sideNavIconSvg" viewBox="0 0 24 24">
                            <path d="M7 3h7l5 5v13H7z" />
                            <path d="M14 3v5h5" />
                            <path d="M10 13h6" />
                            <path d="M10 17h6" />
                        </svg>
                    </span>
                    <span className="sideNavLabel">החשבוניות שלי</span>
                </button>

                <button
                    className={`sideNavButton ${isAnalysisChartsScreen ? "active" : ""}`}
                    onClick={() => setScreen("analysis_charts")}
                    aria-current={isAnalysisChartsScreen ? "page" : undefined}
                >
                    <span className="sideNavIcon" aria-hidden="true">
                        <svg className="sideNavIconSvg" viewBox="0 0 24 24">
                            <path d="M5 20V9" />
                            <path d="M12 20V5" />
                            <path d="M19 20v-8" />
                            <path d="M3 20h18" />
                        </svg>
                    </span>
                    <span className="sideNavLabel">ניתוח הוצאות</span>
                </button>

                <button
                    className={`sideNavButton ${isReportsScreen ? "active" : ""}`}
                    onClick={() => setScreen("reports")}
                    aria-current={isReportsScreen ? "page" : undefined}
                >
                    <span className="sideNavIcon" aria-hidden="true">
                        <svg className="sideNavIconSvg" viewBox="0 0 24 24">
                            <path d="M7 3h10v18H7z" />
                            <path d="M10 7h4" />
                            <path d="M10 11h6" />
                            <path d="M10 15h6" />
                        </svg>
                    </span>
                    <span className="sideNavLabel">הפקת דוחות</span>
                </button>
            </aside>
            </header>

            <main className={`container main withSideNav ${isAnalysisChartsScreen ? "analysisChartsMain" : ""}`}>
                {loading && <section className="card center">טוען נתונים...</section>}
                {!loading && error && (
                    <section className="card errorBox">
                        <h2>שגיאה בטעינת הנתונים</h2>
                        <p>{error}</p>
                        <p className="hint">בדוק שהשרת פעיל בכתובת {API_BASE} ונסה שוב.</p>
                    </section>
                )}

                {!loading && !error && (
                    <>
                        {isHomeScreen && (
                            <>
                                <section className="kpiGrid fadeIn">
                                    <article className="kpiCard bills">
                                        <div className="kpiLabel">
                                            <span className="kpiLabelIcon" aria-hidden="true">📄</span>
                                            <span>סה״כ חשבוניות</span>
                                        </div>
                                        <div className="kpiValue">{animatedHomeBillsCount}</div>
                                    </article>
                                    <article className="kpiCard amount">
                                        <div className="kpiLabel">
                                            <span className="kpiLabelIcon" aria-hidden="true">₪</span>
                                            <span>סכום כולל</span>
                                        </div>
                                        <div className="kpiValue">{money(animatedHomeTotal, "₪")}</div>
                                    </article>
                                    <article className="kpiCard paid">
                                        <div className="kpiLabel">
                                            <span className="kpiLabelIcon" aria-hidden="true">✅</span>
                                            <span>חשבוניות ששולמו</span>
                                        </div>
                                        <div className="kpiValue">{animatedHomePaidCount}</div>
                                    </article>
                                    <article className="kpiCard pending">
                                        <div className="kpiLabel">
                                            <span className="kpiLabelIcon" aria-hidden="true">🧾</span>
                                            <span>ממתין לתשלום</span>
                                        </div>
                                        <div className="kpiValue">{animatedHomePendingCount}</div>
                                    </article>
                                </section>

                                <section className="card recentCard fadeIn interactiveCard">
                                    <div className="sectionHeader">
                                        <h2>חשבוניות אחרונות</h2>
                                        <span className="hint">מציג {recentItems.length} חשבוניות אחרונות</span>
                                    </div>

                                    {recentItems.length === 0 && <div className="emptyState">עדיין אין חשבוניות להצגה.</div>}

                                    {recentItems.length > 0 && (
                                        <div className="recentList">
                                            {recentItems.map((item) => {
                                                const status = getBillStatus(item);
                                                const subject = item.subject || item.filename || "ללא נושא";
                                                const fileUrl = fileUrlFromSavedPath(item.saved_path);
                                                const receivedDateText = item.msgDate ? formatDate(item.msgDate) : "—";
                                                const dueDateText = item.dueDate ? formatDate(item.dueDate) : "—";

                                                return (
                                                    <article key={`recent-${item.stableId}-${item.id}`} className={`recentItem ${status.tone}`}>
                                                        <div className="recentItemTop">
                                                            <div className="recentSubjectWrap">
                                                                <div className="recentSubject">{subject}</div>
                                                                <div className="recentCompanyName">{senderDisplay(item.sender)}</div>
                                                            </div>
                                                            <span className={`statusBadge ${status.tone}`}>{status.label}</span>
                                                        </div>

                                                        <div className="recentItemBody">
                                                            <div className="recentFields">
                                                                <div className="recentFieldRow">
                                                                    <span className="recentFieldLabel">סכום:</span>
                                                                    <span className="recentFieldValue">{money(item.amount, item.amount_currency || "₪")}</span>
                                                                </div>
                                                                <div className="recentFieldRow">
                                                                    <span className="recentFieldLabel">התקבל:</span>
                                                                    <span className="recentFieldValue">{receivedDateText}</span>
                                                                </div>
                                                                <div className="recentFieldRow">
                                                                    <span className="recentFieldLabel">יעד:</span>
                                                                    <span className="recentFieldValue">{dueDateText}</span>
                                                                </div>
                                                            </div>
                                                        </div>

                                                        <div className="recentRowActions">
                                                            {item.saved_path ? (
                                                                <a className="btnSecondary small" href={fileUrl} target="_blank" rel="noreferrer">
                                                                    צפייה
                                                                </a>
                                                            ) : (
                                                                <button className="btnSecondary small" disabled>
                                                                    אין קובץ
                                                                </button>
                                                            )}
                                                            <button
                                                                className="btnPrimary small"
                                                                onClick={() => togglePaidById(item.stableId, subject)}
                                                            >
                                                                {item.isPaid ? "בטל שולם" : "סמן כשולם"}
                                                            </button>
                                                        </div>
                                                    </article>
                                                );
                                            })}
                                        </div>
                                    )}
                                </section>
                            </>
                        )}

                        {(isAnalysisChartsScreen || isAnalysisBillsScreen || isReportsScreen) && (
                            <>
                                {(isAnalysisChartsScreen || isAnalysisBillsScreen) && (
                                    <section className={`kpiGrid fadeIn ${isAnalysisChartsScreen ? "analysisChartsKpiGrid" : ""}`}>
                                        <article className="kpiCard bills">
                                            <div className="kpiLabel">
                                                <span className="kpiLabelIcon" aria-hidden="true">📄</span>
                                                <span>סה״כ חשבוניות</span>
                                            </div>
                                            <div className="kpiValue">{animatedAnalysisBillsCount}</div>
                                        </article>
                                        <article className="kpiCard amount">
                                            <div className="kpiLabel">
                                                <span className="kpiLabelIcon" aria-hidden="true">₪</span>
                                                <span>סכום כולל</span>
                                            </div>
                                            <div className="kpiValue">{money(animatedAnalysisVisibleAmount, "₪")}</div>
                                        </article>
                                        <article className="kpiCard paid">
                                            <div className="kpiLabel">
                                                <span className="kpiLabelIcon" aria-hidden="true">✅</span>
                                                <span>חשבוניות ששולמו</span>
                                            </div>
                                            <div className="kpiValue">{animatedAnalysisPaidCount}</div>
                                        </article>
                                        <article className="kpiCard pending">
                                            <div className="kpiLabel">
                                                <span className="kpiLabelIcon" aria-hidden="true">🧾</span>
                                                <span>ממתין לתשלום</span>
                                            </div>
                                            <div className="kpiValue">{animatedAnalysisPendingCount}</div>
                                        </article>
                                    </section>
                                )}

                                {isAnalysisChartsScreen && (
                                    <>
                                        <section className="card chartTimeWindowCard analysisChartsFiltersCard">
                                            <div className="filtersGrid chartFiltersGrid">
                                                <select
                                                    className="select"
                                                    value={analysisTimeWindow}
                                                    onChange={(event) => setAnalysisTimeWindow(event.target.value)}
                                                >
                                                    {TIME_WINDOW_OPTIONS.map((option) => (
                                                        <option key={`charts-time-${option.value}`} value={option.value}>
                                                            תקופת זמן: {option.label}
                                                        </option>
                                                    ))}
                                                </select>

                                                <select className="select" value={analysisCategory} onChange={(event) => setAnalysisCategory(event.target.value)}>
                                                    <option value="all">קטגוריות: כל הקטגוריות</option>
                                                    {categories.map((option) => (
                                                        <option key={`charts-category-${option}`} value={option}>
                                                            קטגוריה: {option}
                                                        </option>
                                                    ))}
                                                </select>
                                            </div>
                                        </section>

                                        {anomalyInsight && (
                                            <section className="card anomalyInsightCard" role="status" aria-live="polite">
                                                <div className="anomalyInsightRow">
                                                    <div className="anomalyInsightIcon" aria-hidden="true">
                                                        <svg className="anomalyInsightIconSvg" viewBox="0 0 24 24" focusable="false">
                                                            <circle cx="12" cy="12" r="9" />
                                                            <path d="M12 7.5v6" />
                                                            <path d="M12 16.8h.01" />
                                                        </svg>
                                                    </div>
                                                    <div className="anomalyInsightContent">
                                                        <p className="anomalyInsightText">
                                                            חשבון {anomalyInsight.category} האחרון עומד על {money(anomalyInsight.latestAmount, "₪")} והוא גבוה
                                                            ב-{Math.round(anomalyInsight.ratio * 100)}% לעומת החשבון הקודם ({money(anomalyInsight.previousAmount, "₪")}).
                                                        </p>
                                                        <p className="anomalyInsightMeta">
                                                            פער: +{money(anomalyInsight.delta, "₪")} בין {formatDate(anomalyInsight.previousDate)} ל-{formatDate(anomalyInsight.latestDate)}.
                                                        </p>
                                                    </div>
                                                </div>
                                            </section>
                                        )}

                                        <section className="insightsGrid analysisChartsInsightsGrid">
                                            <article className="card chartCard analysisChartsPanelCard">
                                                <div className="sectionHeader">
                                                    <h2>מגמת הוצאות</h2>
                                                    <button
                                                        className="textButton"
                                                        onClick={() => setAnalysisMonthFilter("")}
                                                        disabled={!analysisMonthFilter}
                                                    >
                                                        נקה סינון חודש
                                                    </button>
                                                </div>

                                                {monthlySeries.length === 0 && <div className="emptyState">אין מספיק נתונים להצגת גרף.</div>}

                                                {monthlySeries.length > 0 && (
                                                    <div className="lineChart">
                                                        <div className="lineChartViewport">
                                                            <div
                                                                className={`lineChartTrack ${isDenseMonthlyChart ? "dense" : ""}`}
                                                            >
                                                                <div className="lineChartCanvas" style={{ height: `${chartCanvasHeight}px` }}>
                                                                    <svg className="lineChartSvg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                                                                        {[12, 31, 50, 69, 88].map((y) => (
                                                                            <line key={y} x1="6" y1={y} x2="94" y2={y} className="lineChartGrid" />
                                                                        ))}
                                                                        <path d={chartAreaPath} className="lineChartArea" />
                                                                        <path d={chartLinePath} className="lineChartStroke" />
                                                                    </svg>

                                                                    <div className="lineChartPoints">
                                                                        {chartPoints.map((point) => {
                                                                            const active = analysisMonthFilter === point.key;

                                                                            return (
                                                                                <button
                                                                                    key={point.key}
                                                                                    className={`lineChartPoint ${active ? "active" : ""}`}
                                                                                    onClick={() =>
                                                                                        setAnalysisMonthFilter((prev) => (prev === point.key ? "" : point.key))
                                                                                    }
                                                                                    style={{ left: `${point.x}%`, top: `${point.y}%` }}
                                                                                    title={`${point.label}: ${money(point.total)}`}
                                                                                    aria-label={`${point.label}: ${money(point.total)}`}
                                                                                />
                                                                            );
                                                                        })}
                                                                    </div>
                                                                </div>

                                                                <div className="lineChartAxis">
                                                                    {visibleAxisPoints.map((point) => {
                                                                        const active = analysisMonthFilter === point.key;

                                                                        return (
                                                                            <button
                                                                                key={`axis-${point.key}`}
                                                                                className={`lineChartAxisLabel ${active ? "active" : ""}`}
                                                                                onClick={() =>
                                                                                    setAnalysisMonthFilter((prev) => (prev === point.key ? "" : point.key))
                                                                                }
                                                                                style={{ left: `${point.x}%` }}
                                                                                title={`${point.label}: ${money(point.total)}`}
                                                                                aria-label={`${point.label}: ${money(point.total)}`}
                                                                            >
                                                                                <span className="lineChartAxisMonth">{point.label}</span>
                                                                                {(!isDenseMonthlyChart || active) && (
                                                                                    <span className="lineChartAxisAmount">{money(point.total, "₪")}</span>
                                                                                )}
                                                                            </button>
                                                                        );
                                                                    })}
                                                                </div>
                                                            </div>
                                                        </div>
                                                    </div>
                                                )}
                                            </article>

                                            <article className="card categoryCard analysisChartsPanelCard">
                                                <div className="sectionHeader">
                                                    <h2>פילוח הוצאות לפי קטגוריה</h2>
                                                    <span className="hint">{categoryChart.slices.length} קטגוריות מוצגות</span>
                                                </div>

                                                {categoryChart.slices.length === 0 && <div className="emptyState">אין מספיק נתונים להצגת פילוח.</div>}

                                                {categoryChart.slices.length > 0 && (
                                                    <div className="categoryDonutLayout">
                                                        <div className="categoryDonutWrap">
                                                            <svg
                                                                className="categoryDonutSvg"
                                                                viewBox="0 0 220 220"
                                                                role="img"
                                                                aria-label="פילוח הוצאות לפי קטגוריות"
                                                            >
                                                                <circle className="categoryDonutTrack" cx="110" cy="110" r="70" transform="rotate(-90 110 110)" />
                                                                {categoryChart.slices.map((slice) => (
                                                                    <circle
                                                                        key={slice.category}
                                                                        className="categoryDonutSlice"
                                                                        cx="110"
                                                                        cy="110"
                                                                        r="70"
                                                                        transform="rotate(-90 110 110)"
                                                                        stroke={slice.color}
                                                                        strokeDasharray={slice.dasharray}
                                                                        strokeDashoffset={slice.dashoffset}
                                                                    />
                                                                ))}
                                                            </svg>

                                                            <div className="categoryDonutCenter">
                                                                <span>סה"כ בתקופה</span>
                                                                <strong>{money(categoryChart.total, "₪")}</strong>
                                                            </div>
                                                        </div>

                                                        <div className="categoryLegendList">
                                                            {categoryLegendItems.map((entry) => (
                                                                <div key={`legend-${entry.category}`} className="categoryLegendItem">
                                                                    <span className="categoryLegendSwatch" style={{ backgroundColor: entry.color }} />
                                                                    <div className="categoryLegendMain">
                                                                        <strong>{entry.category}</strong>
                                                                        <span>{entry.count} פריטים</span>
                                                                    </div>
                                                                    <div className="categoryLegendValues">
                                                                        <span>{entry.percent.toFixed(1)}%</span>
                                                                        <strong>{money(entry.total, "₪")}</strong>
                                                                    </div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                )}
                                            </article>
                                        </section>

                                        <section className="card chatAssistantCard fadeIn analysisChartsChatDock">
                                            <div className="sectionHeader">
                                                <h2>צ׳אט תובנות</h2>
                                                <span className="hint">שאל שאלות על הנתונים שלך</span>
                                            </div>

                                            <div className="chatThread" ref={chatMessagesRef}>
                                                {chatMessages.map((msg, index) => (
                                                    <div
                                                        key={`chat-${index}`}
                                                        className={`chatBubble ${msg.role === "user" ? "user" : "assistant"}`}
                                                    >
                                                        {msg.text}
                                                    </div>
                                                ))}
                                                {chatSending && <div className="chatBubble assistant pending">חושב...</div>}
                                            </div>

                                            {chatError && <div className="chatError">{chatError}</div>}

                                            <div className="chatComposer">
                                        <textarea
                                            className="chatInput"
                                            value={chatInput}
                                            onChange={(event) => setChatInput(event.target.value)}
                                            onKeyDown={(event) => {
                                                if (event.key === "Enter" && !event.shiftKey) {
                                                    event.preventDefault();
                                                    sendChatMessage();
                                                }
                                            }}
                                            placeholder="לדוגמה: באיזה קטגוריה הייתה העלייה הגדולה ביותר החודש?"
                                            rows={2}
                                        />
                                                <button
                                                    className="btnPrimary"
                                                    onClick={sendChatMessage}
                                                    disabled={chatSending || !chatInput.trim()}
                                                >
                                                    {chatSending ? "שולח..." : "שלח"}
                                                </button>
                                            </div>
                                        </section>
                                    </>
                                )}

                                {isAnalysisBillsScreen && (
                                    <>
                                        <section className="card filtersCard fadeIn">

                                            <div className="filtersGrid">
                                                <label className="searchField prominentSearch">
                                                    <span className="searchIcon" aria-hidden="true">🔎</span>
                                                    <input
                                                        className="input searchInput"
                                                        value={search}
                                                        onChange={(event) => setSearch(event.target.value)}
                                                        placeholder="חיפוש לפי נושא, שולח, שם קובץ או קטגוריה"
                                                    />
                                                </label>

                                                <select className="select" value={category} onChange={(event) => setCategory(event.target.value)}>
                                                    <option value="all">כל הקטגוריות</option>
                                                    {categories.map((option) => (
                                                        <option key={option} value={option}>
                                                            {option}
                                                        </option>
                                                    ))}
                                                </select>

                                                <select
                                                    className="select"
                                                    value={statusFilter}
                                                    onChange={(event) => setStatusFilter(event.target.value)}
                                                >
                                                    {STATUS_OPTIONS.map((option) => (
                                                        <option key={option.value} value={option.value}>
                                                            {option.label}
                                                        </option>
                                                    ))}
                                                </select>

                                                <select
                                                    className="select"
                                                    value={timeWindow}
                                                    onChange={(event) => setTimeWindow(event.target.value)}
                                                >
                                                    {TIME_WINDOW_OPTIONS.map((option) => (
                                                        <option key={option.value} value={option.value}>
                                                            תקופת זמן: {option.label}
                                                        </option>
                                                    ))}
                                                </select>

                                                <select className="select" value={sortMode} onChange={(event) => setSortMode(event.target.value)}>
                                                    {SORT_OPTIONS.map((option) => (
                                                        <option key={option.value} value={option.value}>
                                                            {option.label}
                                                        </option>
                                                    ))}
                                                </select>
                                            </div>

                                            <div className="chipRow">
                                                {QUICK_FILTERS.map((filter) => (
                                                    <button
                                                        key={filter.value}
                                                        className={`chipButton ${quickFilter === filter.value ? "active" : ""}`}
                                                        onClick={() => setQuickFilter(filter.value)}
                                                    >
                                                        {filter.label}
                                                    </button>
                                                ))}
                                            </div>

                                            <div className="filtersActions">
                                                <button className="btnGhost" onClick={clearFilters}>
                                                    נקה פילטרים
                                                </button>
                                                <button className="btnDanger" onClick={cleanDatabase}>
                                                    נקה מסד נתונים
                                                </button>
                                            </div>
                                        </section>

                                        <section className="card tableCard fadeIn">
                                            <div className="sectionHeader">
                                                <h2>טבלת חשבוניות</h2>
                                                <span className="hint">מציג {filteredItems.length} חשבוניות</span>
                                            </div>

                                            {filteredItems.length === 0 && (
                                                <div className="emptyState">לא נמצאו חשבונות לפי הסינון הנוכחי.</div>
                                            )}

                                            {filteredItems.length > 0 && (
                                                <div className="tableWrap">
                                                    <table className="billsTable">
                                                        <thead>
                                                        <tr>
                                                            <th>חשבונית</th>
                                                            <th>קטגוריה</th>
                                                            <th>סטטוס</th>
                                                            <th>סכום</th>
                                                            <th>התקבל</th>
                                                            <th>פעולות</th>
                                                        </tr>
                                                        </thead>
                                                        <tbody>
                                                        {filteredItems.map((item, index) => {
                                                            const status = getBillStatus(item);
                                                            const fileUrl = fileUrlFromSavedPath(item.saved_path);
                                                            const subject = item.subject || item.filename || "ללא נושא";

                                                            return (
                                                                <tr
                                                                    key={`${item.stableId}-${item.id || index}`}
                                                                    className={`tableRow ${status.tone}`}
                                                                    style={{ animationDelay: `${Math.min(index * 25, 240)}ms` }}
                                                                >
                                                                    <td>
                                                                        <div className="tableMainCell">
                                                                            <strong className="tableSubject">{subject}</strong>
                                                                            <span className="tableSender">{senderDisplay(item.sender)}</span>
                                                                        </div>
                                                                    </td>
                                                                    <td>
                                                                        <span className="categoryBadge tableBadge">{item.category || "ללא קטגוריה"}</span>
                                                                    </td>
                                                                    <td>
                                                                        <span className={`statusBadge ${status.tone}`}>{status.label}</span>
                                                                    </td>
                                                                    <td className="tableAmount">{money(item.amount, item.amount_currency || "₪")}</td>
                                                                    <td className="tableDate">{formatDate(item.msgDate)}</td>
                                                                    <td>
                                                                        <div className="tableActions">
                                                                            {item.saved_path ? (
                                                                                <a className="btnSecondary small" href={fileUrl} target="_blank" rel="noreferrer">
                                                                                    צפייה
                                                                                </a>
                                                                            ) : (
                                                                                <button className="btnSecondary small" disabled>
                                                                                    אין קובץ
                                                                                </button>
                                                                            )}
                                                                            <button
                                                                                className="btnPrimary small"
                                                                                onClick={() => togglePaidById(item.stableId, subject)}
                                                                            >
                                                                                {item.isPaid ? "בטל שולם" : "סמן כשולם"}
                                                                            </button>
                                                                            <button className="btnGhost small" onClick={() => createReminder(item)}>
                                                                                תזכורת
                                                                            </button>
                                                                        </div>
                                                                    </td>
                                                                </tr>
                                                            );
                                                        })}
                                                        </tbody>
                                                    </table>
                                                </div>
                                            )}
                                        </section>
                                    </>
                                )}

                                {isReportsScreen && (
                                    <>
                                        <section className="card filtersCard fadeIn">
                                            <div className="filtersGrid">
                                                <label className="searchField prominentSearch">
                                                    <span className="searchIcon" aria-hidden="true">🔎</span>
                                                    <input
                                                        className="input searchInput"
                                                        value={reportSearch}
                                                        onChange={(event) => setReportSearch(event.target.value)}
                                                        placeholder="חיפוש לפי נושא, שולח, שם קובץ או קטגוריה"
                                                    />
                                                </label>

                                                <select className="select" value={reportCategory} onChange={(event) => setReportCategory(event.target.value)}>
                                                    <option value="all">כל הקטגוריות</option>
                                                    {categories.map((option) => (
                                                        <option key={`report-category-${option}`} value={option}>
                                                            {option}
                                                        </option>
                                                    ))}
                                                </select>

                                                <select
                                                    className="select"
                                                    value={reportStatusFilter}
                                                    onChange={(event) => setReportStatusFilter(event.target.value)}
                                                >
                                                    {STATUS_OPTIONS.map((option) => (
                                                        <option key={`report-status-${option.value}`} value={option.value}>
                                                            {option.label}
                                                        </option>
                                                    ))}
                                                </select>

                                                <select
                                                    className="select"
                                                    value={reportTimeWindow}
                                                    onChange={(event) => setReportTimeWindow(event.target.value)}
                                                >
                                                    {TIME_WINDOW_OPTIONS.map((option) => (
                                                        <option key={`report-time-${option.value}`} value={option.value}>
                                                            תקופת זמן: {option.label}
                                                        </option>
                                                    ))}
                                                </select>

                                                <select className="select" value={reportSortMode} onChange={(event) => setReportSortMode(event.target.value)}>
                                                    {SORT_OPTIONS.map((option) => (
                                                        <option key={`report-sort-${option.value}`} value={option.value}>
                                                            {option.label}
                                                        </option>
                                                    ))}
                                                </select>
                                            </div>

                                            <div className="chipRow">
                                                {QUICK_FILTERS.map((filter) => (
                                                    <button
                                                        key={`report-chip-${filter.value}`}
                                                        className={`chipButton ${reportQuickFilter === filter.value ? "active" : ""}`}
                                                        onClick={() => setReportQuickFilter(filter.value)}
                                                    >
                                                        {filter.label}
                                                    </button>
                                                ))}
                                            </div>

                                            <div className="filtersActions">
                                                <button className="btnGhost" onClick={clearReportFilters}>
                                                    נקה פילטרים
                                                </button>
                                                <button
                                                    className="btnPrimary"
                                                    onClick={exportReceiptsReport}
                                                    disabled={exportingReport || reportExportableFilteredItems.length === 0}
                                                >
                                                    {exportingReport ? "מכין דוח..." : "הפק דוח קבלות"}
                                                </button>
                                            </div>
                                            {reportError && <div className="reportErrorBox">{reportError}</div>}
                                        </section>

                                        <section className="card tableCard fadeIn">
                                            <div className="sectionHeader">
                                                <h2>קבצים בדוח: {reportExportableFilteredItems.length}</h2>
                                            </div>

                                            {reportExportableFilteredItems.length === 0 && (
                                                <div className="emptyState">אין קבלות זמינות להפקה לפי הסינון הנוכחי.</div>
                                            )}

                                            {reportExportableFilteredItems.length > 0 && (
                                                <div className="tableWrap">
                                                    <table className="billsTable">
                                                        <thead>
                                                        <tr>
                                                            <th>חשבונית</th>
                                                            <th>סוג מסמך</th>
                                                            <th>קטגוריה</th>
                                                            <th>סכום</th>
                                                            <th>התקבל</th>
                                                            <th>קובץ</th>
                                                        </tr>
                                                        </thead>
                                                        <tbody>
                                                        {reportExportableFilteredItems.map((item, index) => {
                                                            const fileUrl = fileUrlFromSavedPath(item.saved_path);
                                                            const subject = item.subject || item.filename || "ללא נושא";
                                                            return (
                                                                <tr
                                                                    key={`report-${item.stableId}-${item.id || index}`}
                                                                    className="tableRow"
                                                                    style={{ animationDelay: `${Math.min(index * 20, 180)}ms` }}
                                                                >
                                                                    <td>
                                                                        <div className="tableMainCell">
                                                                            <strong className="tableSubject">{subject}</strong>
                                                                            <span className="tableSender">{senderDisplay(item.sender)}</span>
                                                                        </div>
                                                                    </td>
                                                                    <td>
                                                                        <span className="statusBadge unpaid">{item.document_type === "receipt" ? "קבלה" : "חשבונית"}</span>
                                                                    </td>
                                                                    <td>
                                                                        <span className="categoryBadge tableBadge">{item.category || "ללא קטגוריה"}</span>
                                                                    </td>
                                                                    <td className="tableAmount">{money(item.amount, item.amount_currency || "₪")}</td>
                                                                    <td className="tableDate">{formatDate(item.msgDate)}</td>
                                                                    <td>
                                                                        <div className="tableActions">
                                                                            <a className="btnSecondary small" href={fileUrl} target="_blank" rel="noreferrer">
                                                                                צפייה
                                                                            </a>
                                                                        </div>
                                                                    </td>
                                                                </tr>
                                                            );
                                                        })}
                                                        </tbody>
                                                    </table>
                                                </div>
                                            )}
                                        </section>
                                    </>
                                )}
                            </>
                        )}
                    </>
                )}
            </main>

            {toastMessage && <div className="toast">{toastMessage}</div>}
        </div>
    );
}
