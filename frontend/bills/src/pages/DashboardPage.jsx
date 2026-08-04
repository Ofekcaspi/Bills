import { startTransition, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import {
    ANOMALY_MIN_DELTA_AMOUNT,
    ANOMALY_MIN_INCREASE_RATIO,
    ANOMALY_MIN_PREVIOUS_AMOUNT,
    API_BASE,
    CATEGORY_CHART_COLORS,
    DEFAULT_SORT_MODE,
    DEFAULT_TIME_WINDOW,
    DUE_SOON_DAYS,
    PAID_STORAGE_KEY,
    SUMMARY_DEFAULT,
    TIME_WINDOW_MONTH_COUNT,
    TIME_WINDOW_OPTIONS,
} from "../constants/dashboardConstants.js";
import { useAnimatedNumber } from "../hooks/useAnimatedNumber.js";
import {
    cleanBillsDatabase,
    exportReceiptsReportByIds,
    fetchDashboardData,
    sendDashboardChatMessage,
    syncBillsFromGmail,
} from "../services/dashboardApi.js";
import {
    buildRecentMonthKeys,
    daysBetween,
    filenameFromContentDisposition,
    formatDate,
    isElectricityCategory,
    monthKey,
    monthLabel,
    parseDate,
    getStableBillId,
    timeWindowDays,
    toNumber,
} from "../utils/billUtils.js";
import "../styles/App.css";
import AnalysisPage from "./AnalysisPage.jsx";
import BillsPage from "./BillsPage.jsx";
import HomePage from "./HomePage.jsx";
import ReportsPage from "./ReportsPage.jsx";

export default function DashboardPage() {
    const [billDocuments, setBillDocuments] = useState([]);
    const [dashboardSummary, setDashboardSummary] = useState(SUMMARY_DEFAULT);
    const [activeScreen, setActiveScreen] = useState("home");

    const [billsSearchQuery, setBillsSearchQuery] = useState("");
    const [selectedBillCategory, setSelectedBillCategory] = useState("all");
    const [selectedBillStatus, setSelectedBillStatus] = useState("all");
    const [selectedBillQuickFilter, setSelectedBillQuickFilter] = useState("all");
    const [billsSortMode, setBillsSortMode] = useState(DEFAULT_SORT_MODE);
    const [billsTimeWindow, setBillsTimeWindow] = useState(DEFAULT_TIME_WINDOW);
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
    const [isDashboardLoading, setIsDashboardLoading] = useState(true);
    const [isSyncingBills, setIsSyncingBills] = useState(false);
    const [isExportingReceiptsReport, setIsExportingReceiptsReport] = useState(false);
    const [isSyncModalOpen, setIsSyncModalOpen] = useState(false);
    const [syncTimeWindow, setSyncTimeWindow] = useState(DEFAULT_TIME_WINDOW);
    const [dashboardError, setDashboardError] = useState("");
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

    const deferredBillsSearch = useDeferredValue(billsSearchQuery);
    const deferredReportSearch = useDeferredValue(reportSearch);
    const isHomeScreen = activeScreen === "home";
    const isAnalysisChartsScreen = activeScreen === "analysis_charts";
    const isAnalysisBillsScreen = activeScreen === "analysis_bills";
    const isReportsScreen = activeScreen === "reports";

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
    }, [isSyncModalOpen, isSyncingBills]);

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

    function toggleBillPaidStatus(itemId, subject) {
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

    function showLocalReminderToast(item) {
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
            const payload = await sendDashboardChatMessage({
                message,
                previousResponseId: chatPreviousResponseId,
            });
            const answer = String(payload.answer || "").trim() || "?? ?????? ?????.";
            setChatMessages((prev) => [...prev, { role: "assistant", text: answer }]);
            setChatPreviousResponseId(payload.response_id || "");
        } catch (e) {
            const messageText = e?.message || "????? ?????? ?????";
            setChatError(messageText);
            setChatMessages((prev) => [
                ...prev,
                { role: "assistant", text: `????? ?????: ${messageText}` },
            ]);
        } finally {
            setChatSending(false);
        }
    }

    async function loadDashboardData() {
        try {
            setIsDashboardLoading(true);
            setDashboardError("");

            const dashboardData = await fetchDashboardData();

            startTransition(() => {
                setBillDocuments(dashboardData.billDocuments);
                setDashboardSummary(dashboardData.dashboardSummary);
            });
        } catch (e) {
            setDashboardError(e?.message || "Failed to load data");
        } finally {
            setIsDashboardLoading(false);
        }
    }

    function openSyncModal() {
        setSyncTimeWindow(billsTimeWindow || DEFAULT_TIME_WINDOW);
        setIsSyncModalOpen(true);
    }

    function closeSyncModal() {
        if (isSyncingBills) return;
        setIsSyncModalOpen(false);
    }

    async function syncBillsNow(windowValue = billsTimeWindow) {
        try {
            setIsSyncingBills(true);
            setDashboardError("");

            const result = await syncBillsFromGmail(windowValue);
            if (result.redirected) return;

            setToastMessage("??????? ?????? ??????");
            await loadDashboardData();
        } catch (e) {
            setDashboardError(e?.message || "Sync failed");
        } finally {
            setIsSyncingBills(false);
        }
    }

    async function confirmBillsSyncSelection() {
        const selectedWindow = syncTimeWindow || DEFAULT_TIME_WINDOW;
        setIsSyncModalOpen(false);
        await syncBillsNow(selectedWindow);
    }

    async function deleteAllBillRecords() {
        const confirmed = window.confirm("????? ?? ???? ?? ??????? ????? ????????. ???????");
        if (!confirmed) return;

        try {
            await cleanBillsDatabase();
            setToastMessage("???? ???? ??????");
            await loadDashboardData();
        } catch (e) {
            setDashboardError(e?.message || "Clean DB failed");
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
            setIsExportingReceiptsReport(true);
            setReportError("");

            const res = await exportReceiptsReportByIds(selectedIds);
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
            setIsExportingReceiptsReport(false);
        }
    }

    function clearFilters() {
        setBillsSearchQuery("");
        setSelectedBillCategory("all");
        setSelectedBillStatus("all");
        setSelectedBillQuickFilter("all");
        setBillsSortMode(DEFAULT_SORT_MODE);
        setBillsTimeWindow(DEFAULT_TIME_WINDOW);
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
        loadDashboardData();
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

        const mappedItems = billDocuments.map((item) => {
            const amount = toNumber(item.amount_value);
            const dueDate = parseDate(item.due_date_iso);
            const msgDate = parseDate(item.msg_date);
            const daysToDue = dueDate ? daysBetween(now, dueDate) : null;
            const id = getStableBillId(item);

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
    }, [billDocuments, paidIds]);

    const categories = useMemo(() => {
        const set = new Set(normalizedItems.map((item) => item.category).filter(Boolean));
        return Array.from(set).sort((a, b) => a.localeCompare(b, "he"));
    }, [normalizedItems]);

    const filteredBills = useMemo(() => {
        const query = deferredBillsSearch.trim().toLowerCase();
        const windowDays = timeWindowDays(billsTimeWindow);
        const nowTs = Date.now();
        const cutoffTs = windowDays === null ? null : nowTs - windowDays * 24 * 60 * 60 * 1000;

        const filtered = normalizedItems.filter((item) => {
            if (selectedBillCategory !== "all" && item.category !== selectedBillCategory) return false;

            if (selectedBillStatus === "unpaid" && item.isPaid) return false;
            if (selectedBillStatus === "paid" && !item.isPaid) return false;

            if (selectedBillQuickFilter === "high_amount" && (item.amount === null || item.amount < 500)) return false;
            if (selectedBillQuickFilter === "uncategorized" && item.category) return false;
            if (selectedBillQuickFilter === "missing_amount" && item.amount !== null) return false;
            if (selectedBillQuickFilter === "has_file" && !item.saved_path) return false;

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
            if (billsSortMode === "amount_desc" || billsSortMode === "amount_asc") {
                const aAmount = a.amount ?? (billsSortMode === "amount_desc" ? -Infinity : Infinity);
                const bAmount = b.amount ?? (billsSortMode === "amount_desc" ? -Infinity : Infinity);
                return billsSortMode === "amount_desc" ? bAmount - aAmount : aAmount - bAmount;
            }

            if (billsSortMode === "received_desc") {
                const aDate = a.msgDate ? a.msgDate.getTime() : 0;
                const bDate = b.msgDate ? b.msgDate.getTime() : 0;
                return bDate - aDate;
            }

            if (a.isPaid !== b.isPaid) return a.isPaid ? 1 : -1;
            if (a.isOverdue !== b.isOverdue) return a.isOverdue ? -1 : 1;
            if (a.isDueSoon !== b.isDueSoon) return a.isDueSoon ? -1 : 1;

            const aDue = a.dueDate ? a.dueDate.getTime() : Number.MAX_SAFE_INTEGER;
            const bDue = b.dueDate ? b.dueDate.getTime() : Number.MAX_SAFE_INTEGER;
            return billsSortMode === "due_desc" ? bDue - aDue : aDue - bDue;
        });
    }, [
        normalizedItems,
        deferredBillsSearch,
        selectedBillCategory,
        selectedBillStatus,
        selectedBillQuickFilter,
        billsSortMode,
        billsTimeWindow,
    ]);

    const filteredReportItems = useMemo(() => {
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
        () => filteredReportItems.filter((item) => item.saved_path),
        [filteredReportItems],
    );

    const stats = useMemo(() => {
        const visibleAmount = filteredBills.reduce((acc, item) => acc + (item.amount ?? 0), 0);
        const pendingCount = filteredBills.filter((item) => !item.isPaid).length;
        const paidCount = filteredBills.filter((item) => item.isPaid).length;

        return {
            visibleAmount,
            pendingCount,
            paidCount,
            apiTotal: Number(dashboardSummary?.total || 0),
        };
    }, [filteredBills, dashboardSummary]);

    const homeStats = useMemo(() => {
        const pendingCount = normalizedItems.filter((item) => !item.isPaid).length;
        const paidCount = normalizedItems.filter((item) => item.isPaid).length;

        return {
            pendingCount,
            paidCount,
            apiTotal: Number(dashboardSummary?.total || 0),
        };
    }, [normalizedItems, dashboardSummary]);

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
            apiTotal: Number(dashboardSummary?.total || 0),
        };
    }, [analysisFilteredItems, dashboardSummary]);

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

    const visibleAnalysisItems = isAnalysisBillsScreen ? filteredBills : analysisFilteredItems;
    const analysisViewStats = isAnalysisBillsScreen ? stats : analysisStats;
    const animatedHomeBillsCount = useAnimatedNumber(normalizedItems.length);
    const animatedHomeTotal = useAnimatedNumber(homeStats.apiTotal, { decimals: 2 });
    const animatedHomePaidCount = useAnimatedNumber(homeStats.paidCount);
    const animatedHomePendingCount = useAnimatedNumber(homeStats.pendingCount);
    const animatedAnalysisBillsCount = useAnimatedNumber(visibleAnalysisItems.length);
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
                        <button className="btnPrimary syncMainButton" onClick={openSyncModal} disabled={isSyncingBills}>
                            {isSyncingBills ? "מסנכרן..." : "🔄 סנכרן חשבוניות"}
                        </button>

                        {isSyncModalOpen && (
                            <section className="syncPopover" role="dialog" aria-label="בחירת תקופת סנכרון">
                                <label className="syncPopoverField">
                                    <span>תקופת זמן</span>
                                    <select
                                        className="select"
                                        value={syncTimeWindow}
                                        onChange={(event) => setSyncTimeWindow(event.target.value)}
                                        disabled={isSyncingBills}
                                    >
                                        {TIME_WINDOW_OPTIONS.map((option) => (
                                            <option key={`sync-time-${option.value}`} value={option.value}>
                                                {option.label}
                                            </option>
                                        ))}
                                    </select>
                                </label>

                                <div className="syncPopoverActions">
                                    <button className="btnGhost buttonSmall" onClick={closeSyncModal} disabled={isSyncingBills}>
                                        ביטול
                                    </button>
                                    <button className="btnPrimary buttonSmall" onClick={confirmBillsSyncSelection} disabled={isSyncingBills}>
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
                    onClick={() => setActiveScreen("home")}
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
                    onClick={() => setActiveScreen("analysis_bills")}
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
                    onClick={() => setActiveScreen("analysis_charts")}
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
                    onClick={() => setActiveScreen("reports")}
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
                {isDashboardLoading && <section className="panelCard centeredStatus">טוען נתונים...</section>}
                {!isDashboardLoading && dashboardError && (
                    <section className="panelCard errorBox">
                        <h2>שגיאה בטעינת הנתונים</h2>
                        <p>{dashboardError}</p>
                        <p className="hint">בדוק שהשרת פעיל בכתובת {API_BASE} ונסה שוב.</p>
                    </section>
                )}

                {!isDashboardLoading && !dashboardError && (
                    <>
                        {isHomeScreen && (
                            <HomePage
                                animatedHomeBillsCount={animatedHomeBillsCount}
                                animatedHomeTotal={animatedHomeTotal}
                                animatedHomePaidCount={animatedHomePaidCount}
                                animatedHomePendingCount={animatedHomePendingCount}
                                recentItems={recentItems}
                                toggleBillPaidStatus={toggleBillPaidStatus}
                            />
                        )}

                        {isAnalysisChartsScreen && (
                            <AnalysisPage
                                animatedAnalysisBillsCount={animatedAnalysisBillsCount}
                                animatedAnalysisVisibleAmount={animatedAnalysisVisibleAmount}
                                animatedAnalysisPaidCount={animatedAnalysisPaidCount}
                                animatedAnalysisPendingCount={animatedAnalysisPendingCount}
                                analysisTimeWindow={analysisTimeWindow}
                                setAnalysisTimeWindow={setAnalysisTimeWindow}
                                analysisCategory={analysisCategory}
                                setAnalysisCategory={setAnalysisCategory}
                                categories={categories}
                                anomalyInsight={anomalyInsight}
                                analysisMonthFilter={analysisMonthFilter}
                                setAnalysisMonthFilter={setAnalysisMonthFilter}
                                monthlySeries={monthlySeries}
                                isDenseMonthlyChart={isDenseMonthlyChart}
                                chartCanvasHeight={chartCanvasHeight}
                                chartPoints={chartPoints}
                                chartAreaPath={chartAreaPath}
                                chartLinePath={chartLinePath}
                                visibleAxisPoints={visibleAxisPoints}
                                categoryChart={categoryChart}
                                categoryLegendItems={categoryLegendItems}
                                chatMessagesRef={chatMessagesRef}
                                chatMessages={chatMessages}
                                chatSending={chatSending}
                                chatError={chatError}
                                chatInput={chatInput}
                                setChatInput={setChatInput}
                                sendChatMessage={sendChatMessage}
                            />
                        )}

                        {isAnalysisBillsScreen && (
                            <BillsPage
                                animatedAnalysisBillsCount={animatedAnalysisBillsCount}
                                animatedAnalysisVisibleAmount={animatedAnalysisVisibleAmount}
                                animatedAnalysisPaidCount={animatedAnalysisPaidCount}
                                animatedAnalysisPendingCount={animatedAnalysisPendingCount}
                                billsSearchQuery={billsSearchQuery}
                                setBillsSearchQuery={setBillsSearchQuery}
                                selectedBillCategory={selectedBillCategory}
                                setSelectedBillCategory={setSelectedBillCategory}
                                selectedBillStatus={selectedBillStatus}
                                setSelectedBillStatus={setSelectedBillStatus}
                                billsTimeWindow={billsTimeWindow}
                                setBillsTimeWindow={setBillsTimeWindow}
                                billsSortMode={billsSortMode}
                                setBillsSortMode={setBillsSortMode}
                                selectedBillQuickFilter={selectedBillQuickFilter}
                                setSelectedBillQuickFilter={setSelectedBillQuickFilter}
                                categories={categories}
                                filteredBills={filteredBills}
                                clearFilters={clearFilters}
                                deleteAllBillRecords={deleteAllBillRecords}
                                toggleBillPaidStatus={toggleBillPaidStatus}
                                showLocalReminderToast={showLocalReminderToast}
                            />
                        )}

                        {isReportsScreen && (
                            <ReportsPage
                                reportSearch={reportSearch}
                                setReportSearch={setReportSearch}
                                reportCategory={reportCategory}
                                setReportCategory={setReportCategory}
                                reportStatusFilter={reportStatusFilter}
                                setReportStatusFilter={setReportStatusFilter}
                                reportTimeWindow={reportTimeWindow}
                                setReportTimeWindow={setReportTimeWindow}
                                reportSortMode={reportSortMode}
                                setReportSortMode={setReportSortMode}
                                reportQuickFilter={reportQuickFilter}
                                setReportQuickFilter={setReportQuickFilter}
                                categories={categories}
                                clearReportFilters={clearReportFilters}
                                exportReceiptsReport={exportReceiptsReport}
                                isExportingReceiptsReport={isExportingReceiptsReport}
                                reportExportableFilteredItems={reportExportableFilteredItems}
                                reportError={reportError}
                            />
                        )}
                    </>
                )}
            </main>

            {toastMessage && <div className="toast">{toastMessage}</div>}
        </div>
    );
}
