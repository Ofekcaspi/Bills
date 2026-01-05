import { useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE = "http://127.0.0.1:8000";

function money(v, cur) {
    if (v == null) return "—";
    const n = Number(v);
    if (Number.isNaN(n)) return `${v} ${cur || ""}`.trim();
    return `${n.toFixed(2)} ${cur || ""}`.trim();
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

    const [loading, setLoading] = useState(true);
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

    useEffect(() => {
        async function load() {
            try {
                setLoading(true);
                setError("");

                const [billsRes, sumRes, upRes] = await Promise.all([
                    fetch(`${API_BASE}/bills?limit=300`),
                    fetch(`${API_BASE}/summary`),
                    fetch(`${API_BASE}/upcoming?days=14`),
                ]);

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
        load();
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
                        <div className="hint">ודא שה־API רץ על {API_BASE} ושאתה יכול לפתוח /docs.</div>
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

                        {/* Filters */}
                        <section className="card filters">
                            <div className="filtersLeft">
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
                                <button className="btn" onClick={() => { setQ(""); setCategory(""); }}>
                                    נקה
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
                                    </tr>
                                    </thead>
                                    <tbody>
                                    {filtered.map((x) => {
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
