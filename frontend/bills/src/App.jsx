import { useEffect, useState } from "react";
import "./App.css";

const API_BASE = "http://127.0.0.1:8000";

export default function App() {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [status, setStatus] = useState("unknown"); // unknown | connected | not_connected
    const [serverInfo, setServerInfo] = useState(null);

    async function checkConnection() {
        try {
            setLoading(true);
            setError("");

            // חשוב: כדי שסשן (state) יעבוד ב-Django
            const res = await fetch(`${API_BASE}/connect-email/`, {
                method: "GET",
                credentials: "include",
                headers: { Accept: "application/json" },
            });

            // אם השרת עשה redirect לגוגל, fetch בדרך כלל יחזיר HTML/שגיאה/או לא JSON.
            // ננסה לפרסר JSON ואם זה לא JSON -> ניפול ל-not_connected.
            const ct = res.headers.get("content-type") || "";
            if (!ct.includes("application/json")) {
                setStatus("not_connected");
                setServerInfo(null);
                return;
            }

            const data = await res.json();
            setServerInfo(data);

            if (data?.ok && (data?.status === "already_connected" || data?.status === "connected")) {
                setStatus("connected");
            } else {
                setStatus("not_connected");
            }
        } catch (e) {
            // הכי נפוץ: לא מחובר/redirect חסום/בעיה ב-CORS
            setStatus("not_connected");
            setServerInfo(null);
            setError(e?.message || "Failed to check connection");
        } finally {
            setLoading(false);
        }
    }

    useEffect(() => {
        checkConnection();
    }, []);

    const startOAuth = () => {
        // OAuth חייב להיות ניווט של הדפדפן (לא fetch)
        window.location.href = `${API_BASE}/connect-email/`;
    };

    return (
        <div className="page" dir="rtl" lang="he">
            <header className="topbar">
                <div className="container topbarInner">
                    <div>
                        <div className="title">Bills Dashboard</div>
                        <div className="subtitle">סטטוס התחברות ל-Gmail</div>
                    </div>
                    <div className="chip">
                        API: <span className="mono">{API_BASE}</span>
                    </div>
                </div>
            </header>

            <main className="container main">
                {loading && <div className="card center">בודק התחברות…</div>}

                {!loading && (
                    <div className="card">
                        <div style={{ display: "flex", gap: 12, alignItems: "center", justifyContent: "space-between" }}>
                            <div>
                                <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 6 }}>
                                    {status === "connected" ? "✅ מחובר ל-Gmail" : "🔒 לא מחובר ל-Gmail"}
                                </div>
                                <div style={{ opacity: 0.8 }}>
                                    {status === "connected"
                                        ? "אפשר להמשיך לשלב הבא (שליפה/ניתוח חשבוניות) לאחר שתוסיף endpoints מתאימים בבק."
                                        : "כדי לאשר גישה למיילים, צריך להתחבר דרך Google OAuth."}
                                </div>
                            </div>

                            <div style={{ display: "flex", gap: 10 }}>
                                {status !== "connected" && (
                                    <button className="btn" onClick={startOAuth}>
                                        התחבר עם Google
                                    </button>
                                )}
                                <button className="btn" onClick={checkConnection}>
                                    רענן סטטוס
                                </button>
                            </div>
                        </div>

                        {error && (
                            <div style={{ marginTop: 12 }}>
                                <div className="errorTitle">הערה</div>
                                <div className="errorText">{error}</div>
                                <div className="hint">אם אתה רואה שגיאת CORS/Network, ודא שה-API רץ ושמוגדר CORS+credentials.</div>
                            </div>
                        )}

                        {serverInfo && (
                            <pre
                                style={{
                                    marginTop: 12,
                                    background: "rgba(0,0,0,0.05)",
                                    padding: 12,
                                    borderRadius: 12,
                                    overflow: "auto",
                                    direction: "ltr",
                                    textAlign: "left",
                                }}
                            >
                {JSON.stringify(serverInfo, null, 2)}
              </pre>
                        )}

                        <div style={{ marginTop: 12, opacity: 0.75 }}>
                            טיפ: אפשר לפתוח את <span className="mono">{API_BASE}/admin/</span> או לבדוק את השרת דרך logs.
                        </div>
                    </div>
                )}
            </main>
        </div>
    );
}