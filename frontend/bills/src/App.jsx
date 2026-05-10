import { startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE = "http://127.0.0.1:8000";
const DUE_SOON_DAYS = 14;
const PAID_STORAGE_KEY = "bills_paid_ids_v1";

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
    { value: "all", label: "כל הסטטוסים" },
    { value: "unpaid", label: "לא שולם" },
    { value: "paid", label: "שולם" },
    { value: "due_soon", label: "ממתין לתשום" },
    { value: "overdue", label: "באיחור" },
    { value: "no_due", label: "ללא תאריך יעד" },
];

const QUICK_FILTERS = [
    { value: "all", label: "הכול" },
    { value: "uncategorized", label: "ללא קטגוריה" },
    { value: "missing_amount", label: "ללא סכום" },
    { value: "has_file", label: "עם קובץ" },
];

const CATEGORY_CHART_COLORS = ["#155b45", "#1f7a5d", "#2e8b57", "#c2872f", "#a56b0f", "#9d7a45", "#7b8b52", "#4f7f5d"];

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
    const [timeWindow, setTimeWindow] = useState("30d");
    const [analysisCategory, setAnalysisCategory] = useState("all");
    const [analysisMonthFilter, setAnalysisMonthFilter] = useState("");
    const [analysisTimeWindow, setAnalysisTimeWindow] = useState("30d");

    const [paidIds, setPaidIds] = useState(() => new Set());
    const [loading, setLoading] = useState(true);
    const [syncing, setSyncing] = useState(false);
    const [error, setError] = useState("");
    const [toastMessage, setToastMessage] = useState("");

    const deferredSearch = useDeferredValue(search);
    const isHomeScreen = screen === "home";
    const isAnalysisChartsScreen = screen === "analysis_charts";
    const isAnalysisBillsScreen = screen === "analysis_bills";

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
        setTimeWindow("30d");
    }

    useEffect(() => {
        loadDashboard();
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
        const windowDays = timeWindowDays(timeWindow);
        const nowTs = Date.now();
        const cutoffTs = windowDays === null ? null : nowTs - windowDays * 24 * 60 * 60 * 1000;

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
        timeWindow,
    ]);

    const stats = useMemo(() => {
        const visibleAmount = filteredItems.reduce((acc, item) => acc + (item.amount ?? 0), 0);
        const unpaidAmount = filteredItems.reduce((acc, item) => acc + (!item.isPaid ? item.amount ?? 0 : 0), 0);
        const dueSoonCount = filteredItems.filter((item) => item.isDueSoon && !item.isPaid).length;
        const overdueCount = filteredItems.filter((item) => item.isOverdue && !item.isPaid).length;

        return {
            visibleAmount,
            unpaidAmount,
            dueSoonCount,
            overdueCount,
            apiTotal: Number(summary?.total || 0),
        };
    }, [filteredItems, summary]);

    const homeStats = useMemo(() => {
        const pendingCount = normalizedItems.filter((item) => !item.isPaid).length;
        const overdueCount = normalizedItems.filter((item) => item.isOverdue && !item.isPaid).length;

        return {
            pendingCount,
            overdueCount,
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
        return Math.max(200, Math.min(320, 180 + chartPoints.length * 8));
    }, [chartPoints]);

    const analysisFilteredItems = useMemo(() => {
        if (!analysisMonthFilter) return monthlySourceItems;
        return monthlySourceItems.filter((item) => {
            const key = monthKey(item.msgDate || item.dueDate);
            return key === analysisMonthFilter;
        });
    }, [monthlySourceItems, analysisMonthFilter]);

    const analysisStats = useMemo(() => {
        const visibleAmount = analysisFilteredItems.reduce((acc, item) => acc + (item.amount ?? 0), 0);
        const unpaidAmount = analysisFilteredItems.reduce((acc, item) => acc + (!item.isPaid ? item.amount ?? 0 : 0), 0);
        const dueSoonCount = analysisFilteredItems.filter((item) => item.isDueSoon && !item.isPaid).length;
        const overdueCount = analysisFilteredItems.filter((item) => item.isOverdue && !item.isPaid).length;

        return {
            visibleAmount,
            unpaidAmount,
            dueSoonCount,
            overdueCount,
            apiTotal: Number(summary?.total || 0),
        };
    }, [analysisFilteredItems, summary]);

    useEffect(() => {
        if (!analysisMonthFilter) return;
        if (monthlySeries.some((bucket) => bucket.key === analysisMonthFilter)) return;
        setAnalysisMonthFilter("");
    }, [monthlySeries, analysisMonthFilter]);

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

    const analysisViewItems = isAnalysisBillsScreen ? filteredItems : analysisFilteredItems;
    const analysisViewStats = isAnalysisBillsScreen ? stats : analysisStats;

    return (
        <div className="page" dir="rtl" lang="he">
            <header className="topbar">
                <div className="container topbarInner">
                    <div>
                        <div className="eyebrow">Finance Workflow</div>
                        <h1 className="title">Dashboard חשבונות אינטראקטיבי</h1>
                        <p className="subtitle">KPI בזמן אמת, גרף מגמה, פילטרים חכמים, פעולות מהירות והתראות</p>
                        <div className="projectLogoWrap">
                            <img className="projectLogo" src="/logo-concept-b-header.png" alt="Bills logo" />
                            <p className="projectLogoTagline">עושים לך סדר בחשבוניות</p>
                        </div>
                    </div>

                    <div className="topActions">
                        <button className="btnPrimary" onClick={syncNow} disabled={syncing}>
                            {syncing ? "מסנכרן..." : "סנכרון מייל"}
                        </button>
                    </div>
                </div>
            </header>

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
            </aside>

            <main className="container main withSideNav">
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
                                <section className="kpiGrid">
                                    <article className="kpiCard">
                                        <div className="kpiLabel">סה״כ חשבוניות</div>
                                        <div className="kpiValue">{normalizedItems.length}</div>
                                    </article>
                                    <article className="kpiCard">
                                        <div className="kpiLabel">סכום כולל</div>
                                        <div className="kpiValue">{money(homeStats.apiTotal, "₪")}</div>
                                    </article>
                                   <article className="kpiCard">
                                        <div className="kpiLabel">תשלומים קרובים</div>
                                        <div className="kpiValue">{upcomingServerCount}</div>
                                    </article>
                                    <article className="kpiCard">
                                        <div className="kpiLabel">באיחור כרגע</div>
                                        <div className="kpiValue">{homeStats.overdueCount}</div>
                                    </article>
                                    <article className="kpiCard">
                                        <div className="kpiLabel">ממתין לתשלום</div>
                                        <div className="kpiValue">{homeStats.pendingCount} חשבוניות</div>
                                    </article>
                                </section>

                                <section className="homeLayout">
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

                        {(isAnalysisChartsScreen || isAnalysisBillsScreen) && (
                            <>
                                <section className="kpiGrid">
                            <article className="kpiCard">
                                <div className="kpiLabel">סה"כ חשבוניות</div>
                                <div className="kpiValue">{analysisViewItems.length}</div>
                            </article>
                            <article className="kpiCard">
                                <div className="kpiLabel">סכום כולל</div>
                                <div className="kpiValue">{money(analysisViewStats.visibleAmount, "₪")}</div>
                            </article>
                            <article className="kpiCard">
                                <div className="kpiLabel">ממתין לתשלום</div>
                                <div className="kpiValue">{analysisViewStats.dueSoonCount}</div>
                            </article>
                            <article className="kpiCard">
                                <div className="kpiLabel">באיחור</div>
                                <div className="kpiValue">{analysisViewStats.overdueCount}</div>
                            </article>
                        </section>

                        {isAnalysisChartsScreen && (
                            <>
                                <section className="card chartTimeWindowCard">
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

                                <section className="insightsGrid">
                            <article className="card chartCard">
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
                                            <div className="lineChartTrack">
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
                                                        {chartPoints.map((point) => {
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
                                                                <span className="lineChartAxisAmount">{money(point.total, "₪")}</span>
                                                            </button>
                                                        );
                                                    })}
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </article>

                            <article className="card categoryCard">
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
                            </>
                        )}

                        {isAnalysisBillsScreen && (
                            <>
                                <section className="card filtersCard">

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
                    </>
                )}
            </main>

            {toastMessage && <div className="toast">{toastMessage}</div>}
        </div>
    );
}
