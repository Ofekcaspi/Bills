import { useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE = "http://127.0.0.1:8000";

const TIME_WINDOW_OPTIONS = [
    { value: "7d", label: "7 ימים" },
    { value: "14d", label: "14 ימים" },
    { value: "30d", label: "חודש (30 ימים)" },
    { value: "90d", label: "3 חודשים (90 ימים)" },
    { value: "180d", label: "6 חודשים (180 ימים)" },
    { value: "365d", label: "שנה (365 ימים)" },
];

function money(v, cur) {
    if (v == null) return "—";
    const n = Number(v);
    if (Number.isNaN(n)) return `${v} ${cur || ""}`.trim();
    return `${n.toFixed(2)} ${cur || ""}`.trim();
}

function formatReceivedDate(value) {
    if (!value) return "ג€”";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleDateString("he-IL");
}

function fileUrlFromSavedPath(saved_path) {
    if (!saved_path) return "";
    // Normalize windows path -> url path
    const norm = saved_path.replaceAll("\\", "/"); // חשוב!
    const rel = norm.replace(/^downloads\//, "");
    return `http://127.0.0.1:8000/files/${encodeURI(rel)}`;
}

export default function App() {
    const [items, setItems] = useState([]);
    const [summary, setSummary] = useState(null);
    const [upcoming, setUpcoming] = useState(null);

    const [q, setQ] = useState("");
    const [category, setCategory] = useState("");

    // ✅ time window select (like category)
    const [timeWindow, setTimeWindow] = useState("30d");

    const [loading, setLoading] = useState(true);
    const [syncing, setSyncing] = useState(false);
    const [error, setError] = useState("");

    const categories = useMemo(() => {
        const set = new Set(items.map((x) => x.category).filter(Boolean));
        return Array.from(set);
    }, [items]);

    const filtered = useMemo(() => {
        const qq = q.trim().toLowerCase();
        return items.filter((x) => {
            if (category && x.category !== category) return false;
            if (!qq) return true;
            const hay = `${x.subject || ""} ${x.sender || ""} ${x.filename || ""}`.toLowerCase();
            return hay.includes(qq);
        });
    }, [items, q, category]);

    async function loadDashboard() {
        try {
            setLoading(true);
            setError("");

            const [billsRes, sumRes, upRes] = await Promise.all([
                fetch(`${API_BASE}/bills/`, { credentials: "include" }),
                fetch(`${API_BASE}/summary/`, { credentials: "include" }),
                fetch(`${API_BASE}/upcoming/`, { credentials: "include" }),
            ]);

            // אם המשתמש לא מחובר, sync/bills עלול להחזיר 401 (תלוי במימוש שלך)
            if (!billsRes.ok) throw new Error(`Bills API error: ${billsRes.status}`);
            if (!sumRes.ok) throw new Error(`Summary API error: ${sumRes.status}`);
            if (!upRes.ok) throw new Error(`Upcoming API error: ${upRes.status}`);

            const billsData = await billsRes.json();
            const sumData = await sumRes.json();
            const upData = await upRes.json();

            setItems(billsData.items || []);
            setSummary(sumData);
            setUpcoming(upData);
        } catch (e) {
            setError(e?.message || "Failed to load");
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
                // לא מחובר -> נשלח להתחברות
                window.location.href = `${API_BASE}/connect-email/`;
                return;
            }

            if (!res.ok) {
                const txt = await res.text().catch(() => "");
                throw new Error(`Sync error: ${res.status} ${txt}`);
            }

            // לאחר סנכרון, נטען מחדש
            await loadDashboard();
        } catch (e) {
            setError(e?.message || "Sync failed");
        } finally {
            setSyncing(false);
        }
    }

    useEffect(() => {
        loadDashboard();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return (
        <div className="page" dir="rtl" lang="he">
            <header className="topbar">
                <div className="container topbarInner">
                    <div>
                        <div className="title">Bills Dashboard</div>
                        <div className="subtitle">ניהול חשבוניות • סיווג • סכומים • תאריכי יעד</div>
                    </div>
                    <div className="chip">
                        API: <span className="mono">{API_BASE}</span>
                    </div>
                </div>
            </header>

            <main className="container main">
                {loading && <div className="card center">טוען נתונים…</div>}

                {!loading && error && (
                    <div className="card">
                        <div className="errorTitle">שגיאה</div>
                        <div className="errorText">{error}</div>
                        <div className="hint">
                            ודא שה־API רץ על {API_BASE}. אם צריך להתחבר לג׳ימייל, לחץ "סנכרן" והוא יפנה להתחברות.
                        </div>
                    </div>
                )}

                {!loading && !error && (
                    <>
                        {/* KPIs */}
                        <section className="grid3">
                            <div className="kpi">
                                <div className="kpiLabel">סה״כ חשבוניות</div>
                                <div className="kpiValue">{items.length}</div>
                            </div>
                            <div className="kpi">
                                <div className="kpiLabel">סה״כ סכומים (amount)</div>
                                <div className="kpiValue">{Number(summary?.total || 0).toFixed(2)}</div>
                            </div>
                            <div className="kpi">
                                <div className="kpiLabel">תשלומים קרובים (14 יום)</div>
                                <div className="kpiValue">{upcoming?.count ?? 0}</div>
                            </div>
                        </section>

                        {/* Actions + Filters */}
                        <section className="card filters" style={{ alignItems: "center", gap: 12 }}>
                            <div className="filtersLeft" style={{ flexWrap: "wrap", gap: 10 }}>
                                <button className="btn" onClick={syncNow} disabled={syncing}>
                                    {syncing ? "מסנכרן…" : "סנכרן חשבוניות מהמייל"}
                                </button>

                                <input
                                    className="input"
                                    value={q}
                                    onChange={(e) => setQ(e.target.value)}
                                    placeholder="חיפוש לפי נושא / שולח / שם קובץ…"
                                />

                                <select className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
                                    <option value="">כל הקטגוריות</option>
                                    {categories.map((c) => (
                                        <option key={c} value={c}>
                                            {c}
                                        </option>
                                    ))}
                                </select>

                                {/* ✅ Time window dropdown (like category) */}
                                <select className="select" value={timeWindow} onChange={(e) => setTimeWindow(e.target.value)}>
                                    {TIME_WINDOW_OPTIONS.map((t) => (
                                        <option key={t.value} value={t.value}>
                                            חלון זמן: {t.label}
                                        </option>
                                    ))}
                                </select>

                                <button
                                    className="btn"
                                    onClick={async () => {
                                        if (!window.confirm("⚠️ This will permanently delete DB data. Continue?")) {
                                            return;
                                        }

                                        setQ("");
                                        setCategory("");

                                        try {
                                            const res = await fetch(`${API_BASE}/clean-db/`, {
                                                method: "DELETE",
                                            });

                                            const data = await res.json();

                                            if (!res.ok) {
                                                throw new Error(data.error || "Failed to clean DB");
                                            }

                                            alert("Database cleaned successfully");
                                            // 🔄 Refresh the page
                                            window.location.reload();

                                        } catch (err) {
                                            alert(err.message);
                                        }
                                    }}

                                >
                                    נקה
                                </button>

                                <button className="btn" onClick={loadDashboard} disabled={loading || syncing}>
                                    רענן
                                </button>
                            </div>

                            <div className="filtersRight">
                                מציג <b>{filtered.length}</b> מתוך <b>{items.length}</b>
                            </div>
                        </section>

                        {/* Table */}
                        <section className="card tableCard">
                            <div className="tableHeader">
                                <div className="tableTitle">רשימת חשבוניות</div>
                                <div className="tableHint">לחץ “פתח PDF” כדי לראות את המסמך</div>
                            </div>

                            <div className="tableWrap">
                                <table className="table">
                                    <thead>
                                    <tr>
                                        <th>קטגוריה</th>
                                        <th>שולח</th>
                                        <th>נושא</th>
                                        <th>סכום</th>
                                        <th>תאריך יעד</th>
                                        <th>קובץ</th>
                                        <th>תאריך קבלה</th>
                                    </tr>
                                    </thead>
                                    <tbody>
                                    {filtered.map((x) => {
                                        const receivedDate = formatReceivedDate(x.msg_date);
                                        const url = fileUrlFromSavedPath(x.saved_path);
                                        const due = x.due_date_iso || "—";
                                        const dueSoon = x.due_date_iso && upcoming?.items?.some((u) => u.id === x.id);

                                        return (
                                            <tr key={x.id} className={dueSoon ? "rowWarn" : ""}>
                                                <td className="nowrap">{x.category || "—"}</td>
                                                <td className="truncate">{x.sender || "—"}</td>
                                                <td className="truncate">{x.subject || "—"}</td>
                                                <td className="nowrap">{money(x.amount_value, x.amount_currency)}</td>
                                                <td className="nowrap">{due}</td>
                                                <td className="nowrap">
                                                    {x.saved_path ? (
                                                        <a className="linkBtn" href={url} target="_blank" rel="noreferrer">
                                                            פתח PDF
                                                        </a>
                                                    ) : (
                                                        "—"
                                                    )}
                                                </td>
                                                <td className="nowrap">{receivedDate}</td>
                                            </tr>
                                        );
                                    })}
                                    </tbody>
                                </table>
                            </div>
                        </section>
                    </>
                )}
            </main>
        </div>
    );
}
