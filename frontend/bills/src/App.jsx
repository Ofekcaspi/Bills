import { startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE = "http://127.0.0.1:8000";
const DUE_SOON_DAYS = 14;
const PAID_STORAGE_KEY = "bills_paid_ids_v1";

const TIME_WINDOW_OPTIONS = [
    { value: "7d", label: "7 ימים" },
    { value: "14d", label: "14 ימים" },
    { value: "30d", label: "30 ימים" },
    { value: "90d", label: "90 ימים" },
    { value: "180d", label: "180 ימים" },
    { value: "365d", label: "שנה" },
];

const STATUS_OPTIONS = [
    { value: "all", label: "כל הסטטוסים" },
    { value: "unpaid", label: "לא שולם" },
    { value: "paid", label: "שולם" },
    { value: "due_soon", label: "לתשלום בקרוב" },
    { value: "overdue", label: "באיחור" },
    { value: "no_due", label: "ללא תאריך יעד" },
];

const QUICK_FILTERS = [
    { value: "all", label: "הכול" },
    { value: "high_amount", label: "מעל ₪500" },
    { value: "uncategorized", label: "ללא קטגוריה" },
    { value: "missing_amount", label: "ללא סכום" },
    { value: "has_file", label: "עם קובץ" },
];

function toNumber(value) {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
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

function stableItemId(item) {
    return String(item.message_id ?? item.id ?? item.filename ?? "");
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

function buildCopyText(item) {
    const lines = [
        `נושא: ${item.subject || "-"}`,
        `שולח: ${item.sender || "-"}`,
        `קטגוריה: ${item.category || "-"}`,
        `סכום: ${money(item.amount, item.amount_currency || "₪")}`,
        `תאריך יעד: ${formatDate(item.dueDate)}`,
        `תאריך קבלה: ${formatDate(item.msgDate)}`,
        `קובץ: ${item.filename || "-"}`,
    ];
    return lines.join("\n");
}

function getBillStatus(item) {
    if (item.isPaid) return { tone: "paid", label: "שולם" };
    if (item.isOverdue) return { tone: "overdue", label: `באיחור ${Math.abs(item.daysToDue)} ימים` };
    if (item.isDueSoon) return { tone: "soon", label: `לתשלום בעוד ${item.daysToDue} ימים` };
    if (!item.dueDate) return { tone: "muted", label: "ללא תאריך יעד" };
    return { tone: "open", label: "פתוח" };
}

export default function App() {
    const [items, setItems] = useState([]);
    const [summary, setSummary] = useState({ total: 0 });
    const [upcoming, setUpcoming] = useState({ count: 0, items: [] });
    const [screen, setScreen] = useState("home");

    const [search, setSearch] = useState("");
    const [category, setCategory] = useState("all");
    const [statusFilter, setStatusFilter] = useState("all");
    const [quickFilter, setQuickFilter] = useState("all");
    const [minAmount, setMinAmount] = useState("");
    const [maxAmount, setMaxAmount] = useState("");
    const [monthFilter, setMonthFilter] = useState("");
    const [timeWindow, setTimeWindow] = useState("30d");

    const [paidIds, setPaidIds] = useState(() => new Set());
    const [loading, setLoading] = useState(true);
    const [syncing, setSyncing] = useState(false);
    const [error, setError] = useState("");
    const [toastMessage, setToastMessage] = useState("");

    const deferredSearch = useDeferredValue(search);

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

    async function copyBillDetails(item) {
        try {
            if (!navigator.clipboard) {
                throw new Error("Clipboard API is not available");
            }
            await navigator.clipboard.writeText(buildCopyText(item));
            setToastMessage("הפרטים הועתקו ללוח");
        } catch {
            setToastMessage("לא ניתן להעתיק כרגע");
        }
    }

    function createReminder(item) {
        const subject = item.subject || item.filename || "חשבון";
        const dueText = formatDate(item.dueDate);
        setToastMessage(`תזכורת מקומית נוצרה עבור ${subject} (יעד: ${dueText})`);
    }

    async function loadDashboard() {
        try {
            setLoading(true);
            setError("");

            const [billsRes, sumRes, upRes] = await Promise.all([
                fetch(`${API_BASE}/bills/`, { credentials: "include" }),
                fetch(`${API_BASE}/summary/`, { credentials: "include" }),
                fetch(`${API_BASE}/upcoming/`, { credentials: "include" }),
            ]);

            if (!billsRes.ok) throw new Error(`Bills API error: ${billsRes.status}`);
            if (!sumRes.ok) throw new Error(`Summary API error: ${sumRes.status}`);
            if (!upRes.ok) throw new Error(`Upcoming API error: ${upRes.status}`);

            const [billsData, sumData, upData] = await Promise.all([billsRes.json(), sumRes.json(), upRes.json()]);

            startTransition(() => {
                setItems(Array.isArray(billsData?.items) ? billsData.items : []);
                setSummary(sumData || { total: 0 });
                setUpcoming(upData || { count: 0, items: [] });
            });
        } catch (e) {
            setError(e?.message || "Failed to load data");
        } finally {
            setLoading(false);
        }
    }

    async function syncNow() {
        try {
            setSyncing(true);
            setError("");

            const res = await fetch(`${API_BASE}/sync/`, {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ max_results: 100, time_window: timeWindow }),
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

    function clearFilters() {
        setSearch("");
        setCategory("all");
        setStatusFilter("all");
        setQuickFilter("all");
        setMinAmount("");
        setMaxAmount("");
        setMonthFilter("");
    }

    useEffect(() => {
        loadDashboard();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const normalizedItems = useMemo(() => {
        const now = new Date();

        return items.map((item) => {
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
                isPaid: paidIds.has(id),
            };
        });
    }, [items, paidIds]);

    const categories = useMemo(() => {
        const set = new Set(normalizedItems.map((item) => item.category).filter(Boolean));
        return Array.from(set).sort((a, b) => a.localeCompare(b, "he"));
    }, [normalizedItems]);

    const filteredItems = useMemo(() => {
        const query = deferredSearch.trim().toLowerCase();
        const min = toNumber(minAmount);
        const max = toNumber(maxAmount);

        const filtered = normalizedItems.filter((item) => {
            if (category !== "all" && item.category !== category) return false;

            if (statusFilter === "unpaid" && item.isPaid) return false;
            if (statusFilter === "paid" && !item.isPaid) return false;
            if (statusFilter === "due_soon" && (!item.isDueSoon || item.isPaid)) return false;
            if (statusFilter === "overdue" && (!item.isOverdue || item.isPaid)) return false;
            if (statusFilter === "no_due" && item.dueDate) return false;

            if (quickFilter === "high_amount" && (item.amount === null || item.amount < 500)) return false;
            if (quickFilter === "uncategorized" && item.category) return false;
            if (quickFilter === "missing_amount" && item.amount !== null) return false;
            if (quickFilter === "has_file" && !item.saved_path) return false;

            if (min !== null && (item.amount === null || item.amount < min)) return false;
            if (max !== null && (item.amount === null || item.amount > max)) return false;

            if (monthFilter) {
                const key = monthKey(item.msgDate || item.dueDate);
                if (key !== monthFilter) return false;
            }

            if (query) {
                const haystack = `${item.subject || ""} ${item.sender || ""} ${item.filename || ""} ${item.category || ""}`.toLowerCase();
                if (!haystack.includes(query)) return false;
            }

            return true;
        });

        return filtered.sort((a, b) => {
            if (a.isPaid !== b.isPaid) return a.isPaid ? 1 : -1;
            if (a.isOverdue !== b.isOverdue) return a.isOverdue ? -1 : 1;
            if (a.isDueSoon !== b.isDueSoon) return a.isDueSoon ? -1 : 1;

            const aDue = a.dueDate ? a.dueDate.getTime() : Number.MAX_SAFE_INTEGER;
            const bDue = b.dueDate ? b.dueDate.getTime() : Number.MAX_SAFE_INTEGER;
            return aDue - bDue;
        });
    }, [
        normalizedItems,
        deferredSearch,
        category,
        statusFilter,
        quickFilter,
        minAmount,
        maxAmount,
        monthFilter,
    ]);

    const stats = useMemo(() => {
        const visibleAmount = filteredItems.reduce((acc, item) => acc + (item.amount ?? 0), 0);
        const unpaidAmount = filteredItems.reduce((acc, item) => acc + (!item.isPaid ? item.amount ?? 0 : 0), 0);
        const dueSoonCount = filteredItems.filter((item) => item.isDueSoon && !item.isPaid).length;
        const overdueCount = filteredItems.filter((item) => item.isOverdue && !item.isPaid).length;
        const paidCount = filteredItems.filter((item) => item.isPaid).length;
        const paidRate = filteredItems.length ? Math.round((paidCount / filteredItems.length) * 100) : 0;

        return {
            visibleAmount,
            unpaidAmount,
            dueSoonCount,
            overdueCount,
            paidRate,
            apiTotal: Number(summary?.total || 0),
        };
    }, [filteredItems, summary]);

    const monthlySeries = useMemo(() => {
        const totals = new Map();

        normalizedItems.forEach((item) => {
            if (item.amount === null) return;
            const anchor = item.msgDate || item.dueDate;
            if (!anchor) return;
            const key = monthKey(anchor);
            totals.set(key, (totals.get(key) || 0) + item.amount);
        });

        const keys = Array.from(totals.keys()).sort();
        const recent = keys.slice(-8);

        return recent.map((key) => ({
            key,
            label: monthLabel(key),
            total: totals.get(key) || 0,
        }));
    }, [normalizedItems]);

    const maxChartValue = useMemo(() => {
        if (!monthlySeries.length) return 0;
        return monthlySeries.reduce((max, bucket) => Math.max(max, bucket.total), 0);
    }, [monthlySeries]);

    const alerts = useMemo(() => {
        const results = [];

        normalizedItems.forEach((item) => {
            if (item.isPaid || !item.dueDate) return;

            if (item.isOverdue) {
                results.push({
                    stableId: item.stableId,
                    type: "danger",
                    priority: 0,
                    title: item.subject || item.filename || "חיוב ללא כותרת",
                    subtitle: `באיחור ${Math.abs(item.daysToDue)} ימים`,
                });
                return;
            }

            if (item.isDueSoon) {
                results.push({
                    stableId: item.stableId,
                    type: "warning",
                    priority: 1,
                    title: item.subject || item.filename || "חיוב ללא כותרת",
                    subtitle: `לתשלום בעוד ${item.daysToDue} ימים`,
                });
            }
        });

        return results
            .sort((a, b) => a.priority - b.priority)
            .slice(0, 6);
    }, [normalizedItems]);

    const upcomingServerCount = Number(upcoming?.count || 0);
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

        filteredItems.forEach((item) => {
            const key = item.category || "ללא קטגוריה";
            const current = grouped.get(key) || { category: key, total: 0, count: 0 };
            current.total += item.amount ?? 0;
            current.count += 1;
            grouped.set(key, current);
        });

        return Array.from(grouped.values())
            .sort((a, b) => b.total - a.total)
            .slice(0, 8);
    }, [filteredItems]);

    const maxCategoryTotal = useMemo(() => {
        if (!categorySeries.length) return 0;
        return categorySeries.reduce((max, entry) => Math.max(max, entry.total), 0);
    }, [categorySeries]);

    return (
        <div className="page" dir="rtl" lang="he">
            <header className="topbar">
                <div className="container topbarInner">
                    <div>
                        <div className="eyebrow">Finance Workflow</div>
                        <h1 className="title">Dashboard חשבונות אינטראקטיבי</h1>
                        <p className="subtitle">KPI בזמן אמת, גרף מגמה, פילטרים חכמים, פעולות מהירות והתראות</p>
                        <h1 className="projectTitle">Bliis</h1>
                        <div className="viewTabs" role="tablist" aria-label="Main screens">
                            <button
                                className={`viewTab ${screen === "home" ? "active" : ""}`}
                                onClick={() => setScreen("home")}
                                role="tab"
                                aria-selected={screen === "home"}
                            >
                                בית
                            </button>
                            <button
                                className={`viewTab ${screen === "analysis" ? "active" : ""}`}
                                onClick={() => setScreen("analysis")}
                                role="tab"
                                aria-selected={screen === "analysis"}
                            >
                                ניתוח הוצאות
                            </button>
                        </div>
                    </div>

                    <div className="topActions">
                        <button className="btnSecondary" onClick={loadDashboard} disabled={loading || syncing}>
                            רענון
                        </button>
                        <button className="btnPrimary" onClick={syncNow} disabled={syncing}>
                            {syncing ? "מסנכרן..." : "סנכרון מייל"}
                        </button>
                    </div>
                </div>
            </header>

            <main className="container main">
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
                        {screen === "home" && (
                            <>
                                <section className="kpiGrid">
                                    <article className="kpiCard">
                                        <div className="kpiLabel">סה״כ חשבונות</div>
                                        <div className="kpiValue">{normalizedItems.length}</div>
                                    </article>
                                    <article className="kpiCard">
                                        <div className="kpiLabel">סכום כולל במערכת</div>
                                        <div className="kpiValue">{money(stats.apiTotal, "₪")}</div>
                                    </article>
                                    <article className="kpiCard">
                                        <div className="kpiLabel">תשלומים קרובים</div>
                                        <div className="kpiValue">{upcomingServerCount}</div>
                                    </article>
                                    <article className="kpiCard">
                                        <div className="kpiLabel">באיחור כרגע</div>
                                        <div className="kpiValue">{stats.overdueCount}</div>
                                    </article>
                                    <article className="kpiCard">
                                        <div className="kpiLabel">לא שולם</div>
                                        <div className="kpiValue">{money(stats.unpaidAmount, "₪")}</div>
                                    </article>
                                    <article className="kpiCard">
                                        <div className="kpiLabel">שיעור שולם</div>
                                        <div className="kpiValue">{stats.paidRate}%</div>
                                    </article>
                                </section>

                                <section className="homeLayout">
                                    <article className="card homeQuickCard">
                                        <div className="sectionHeader">
                                            <h2>פעולות מהירות</h2>
                                        </div>
                                        <p className="hint">סנכרון, מעבר למסך ניתוח והכנה מהירה לתשלום החשבונות הקרובים.</p>
                                        <div className="homeActionsRow">
                                            <button className="btnPrimary" onClick={() => setScreen("analysis")}>
                                                מעבר לניתוח הוצאות
                                            </button>
                                            <button className="btnSecondary" onClick={syncNow} disabled={syncing}>
                                                {syncing ? "מסנכרן..." : "סנכרון מייל"}
                                            </button>
                                            <button className="btnGhost" onClick={loadDashboard}>
                                                רענון נתונים
                                            </button>
                                        </div>
                                    </article>

                                    <article className="card alertsCard">
                                        <div className="sectionHeader">
                                            <h2>התראות מיידיות</h2>
                                            <span className="alertCounter">{alerts.length}</span>
                                        </div>

                                        {alerts.length === 0 && <div className="emptyState">אין התראות דחופות כרגע.</div>}

                                        {alerts.map((alert) => (
                                            <div key={alert.stableId} className={`alertItem ${alert.type}`}>
                                                <div>
                                                    <div className="alertTitle">{alert.title}</div>
                                                    <div className="alertSubtitle">{alert.subtitle}</div>
                                                </div>
                                                <button
                                                    className="tinyButton"
                                                    onClick={() => togglePaidById(alert.stableId, alert.title)}
                                                >
                                                    סמן כשולם
                                                </button>
                                            </div>
                                        ))}
                                    </article>
                                </section>

                                <section className="card recentCard">
                                    <div className="sectionHeader">
                                        <h2>חשבונות אחרונים</h2>
                                        <span className="hint">מציג {recentItems.length} חשבונות אחרונים</span>
                                    </div>

                                    {recentItems.length === 0 && <div className="emptyState">עדיין אין חשבונות להצגה.</div>}

                                    {recentItems.length > 0 && (
                                        <div className="recentList">
                                            {recentItems.map((item) => {
                                                const status = getBillStatus(item);
                                                const subject = item.subject || item.filename || "ללא נושא";
                                                const fileUrl = fileUrlFromSavedPath(item.saved_path);

                                                return (
                                                    <div key={`recent-${item.stableId}-${item.id}`} className="recentItem">
                                                        <div className="recentMain">
                                                            <div className="recentSubject">{subject}</div>
                                                            <div className="recentMeta">
                                                                {item.sender || "שולח לא זוהה"} • התקבל: {formatDate(item.msgDate)}
                                                            </div>
                                                        </div>

                                                        <div className="recentAmount">{money(item.amount, item.amount_currency || "₪")}</div>
                                                        <span className={`statusBadge ${status.tone}`}>{status.label}</span>

                                                        <div className="recentRowActions">
                                                            {item.saved_path ? (
                                                                <a className="btnSecondary small" href={fileUrl} target="_blank" rel="noreferrer">
                                                                    קובץ
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
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                </section>
                            </>
                        )}

                        {screen === "analysis" && (
                            <>
                                <section className="kpiGrid">
                            <article className="kpiCard">
                                <div className="kpiLabel">חשבונות מוצגים</div>
                                <div className="kpiValue">{filteredItems.length}</div>
                            </article>
                            <article className="kpiCard">
                                <div className="kpiLabel">סה"כ סכום מוצג</div>
                                <div className="kpiValue">{money(stats.visibleAmount, "₪")}</div>
                            </article>
                            <article className="kpiCard">
                                <div className="kpiLabel">לתשלום בקרוב</div>
                                <div className="kpiValue">{stats.dueSoonCount}</div>
                            </article>
                            <article className="kpiCard">
                                <div className="kpiLabel">באיחור</div>
                                <div className="kpiValue">{stats.overdueCount}</div>
                            </article>
                            <article className="kpiCard">
                                <div className="kpiLabel">שיעור שולם</div>
                                <div className="kpiValue">{stats.paidRate}%</div>
                            </article>
                            <article className="kpiCard">
                                <div className="kpiLabel">סה"כ מערכת (API)</div>
                                <div className="kpiValue">{money(stats.apiTotal, "₪")}</div>
                            </article>
                        </section>

                        <section className="insightsGrid">
                            <article className="card chartCard">
                                <div className="sectionHeader">
                                    <h2>מגמת הוצאות חודשית</h2>
                                    <button
                                        className="textButton"
                                        onClick={() => setMonthFilter("")}
                                        disabled={!monthFilter}
                                    >
                                        נקה סינון חודש
                                    </button>
                                </div>

                                {monthlySeries.length === 0 && <div className="emptyState">אין מספיק נתונים להצגת גרף.</div>}

                                {monthlySeries.length > 0 && (
                                    <div className="chartBars">
                                        {monthlySeries.map((bucket) => {
                                            const height = maxChartValue ? Math.max(12, (bucket.total / maxChartValue) * 100) : 12;
                                            const active = monthFilter === bucket.key;

                                            return (
                                                <button
                                                    key={bucket.key}
                                                    className={`barButton ${active ? "active" : ""}`}
                                                    onClick={() => setMonthFilter((prev) => (prev === bucket.key ? "" : bucket.key))}
                                                    title={`${bucket.label}: ${money(bucket.total, "₪")}`}
                                                >
                                                    <span className="barValue">{money(bucket.total, "₪")}</span>
                                                    <span className="barTrack">
                                                        <span className="barFill" style={{ height: `${height}%` }} />
                                                    </span>
                                                    <span className="barLabel">{bucket.label}</span>
                                                </button>
                                            );
                                        })}
                                    </div>
                                )}
                            </article>

                            <article className="card categoryCard">
                                <div className="sectionHeader">
                                    <h2>פילוח הוצאות לפי קטגוריה</h2>
                                    <span className="hint">{categorySeries.length} קטגוריות מוצגות</span>
                                </div>

                                {categorySeries.length === 0 && <div className="emptyState">אין מספיק נתונים להצגת פילוח.</div>}

                                {categorySeries.length > 0 && (
                                    <div className="categoryList">
                                        {categorySeries.map((entry) => {
                                            const width = maxCategoryTotal ? Math.max(8, (entry.total / maxCategoryTotal) * 100) : 8;

                                            return (
                                                <div key={entry.category} className="categoryItem">
                                                    <div className="categoryTop">
                                                        <strong>{entry.category}</strong>
                                                        <span>{entry.count} פריטים</span>
                                                    </div>
                                                    <div className="categoryBar">
                                                        <span style={{ width: `${width}%` }} />
                                                    </div>
                                                    <div className="categoryAmount">{money(entry.total, "₪")}</div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </article>
                        </section>

                        <section className="card filtersCard">
                            <div className="sectionHeader">
                                <h2>פילטרים חכמים וחיפוש מהיר</h2>
                                <span className="hint">
                                    מציג {filteredItems.length} מתוך {normalizedItems.length}
                                </span>
                            </div>

                            <div className="filtersGrid">
                                <input
                                    className="input"
                                    value={search}
                                    onChange={(event) => setSearch(event.target.value)}
                                    placeholder="חיפוש לפי נושא, שולח, שם קובץ או קטגוריה"
                                />

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

                                <input
                                    type="number"
                                    className="input"
                                    value={minAmount}
                                    onChange={(event) => setMinAmount(event.target.value)}
                                    placeholder="סכום מינימלי"
                                />

                                <input
                                    type="number"
                                    className="input"
                                    value={maxAmount}
                                    onChange={(event) => setMaxAmount(event.target.value)}
                                    placeholder="סכום מקסימלי"
                                />

                                <select
                                    className="select"
                                    value={timeWindow}
                                    onChange={(event) => setTimeWindow(event.target.value)}
                                >
                                    {TIME_WINDOW_OPTIONS.map((option) => (
                                        <option key={option.value} value={option.value}>
                                            חלון סנכרון: {option.label}
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

                        <section className="cardsGrid">
                            {filteredItems.map((item, index) => {
                                const status = getBillStatus(item);
                                const fileUrl = fileUrlFromSavedPath(item.saved_path);
                                const subject = item.subject || item.filename || "ללא נושא";

                                return (
                                    <article
                                        key={`${item.stableId}-${item.id || index}`}
                                        className={`billCard ${status.tone}`}
                                        style={{ animationDelay: `${Math.min(index * 35, 300)}ms` }}
                                    >
                                        <div className="billTopRow">
                                            <span className="categoryBadge">{item.category || "ללא קטגוריה"}</span>
                                            <span className={`statusBadge ${status.tone}`}>{status.label}</span>
                                        </div>

                                        <h3 className="billSubject">{subject}</h3>
                                        <p className="billSender">{item.sender || "שולח לא זוהה"}</p>

                                        <div className="billAmount">{money(item.amount, item.amount_currency || "₪")}</div>

                                        <div className="billDates">
                                            <span>יעד: {formatDate(item.dueDate)}</span>
                                            <span>התקבל: {formatDate(item.msgDate)}</span>
                                        </div>

                                        <div className="billActions">
                                            {item.saved_path ? (
                                                <a className="btnSecondary small" href={fileUrl} target="_blank" rel="noreferrer">
                                                    פתח קובץ
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

                                            <button
                                                className="btnGhost small"
                                                onClick={() => {
                                                    void copyBillDetails(item);
                                                }}
                                            >
                                                העתק
                                            </button>
                                        </div>
                                    </article>
                                );
                            })}
                        </section>

                                {filteredItems.length === 0 && (
                                    <section className="card emptyState">לא נמצאו חשבונות לפי הסינון הנוכחי.</section>
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
