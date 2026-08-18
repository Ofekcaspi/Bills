// Calls to the backend API: fetching bills, syncing Gmail, exporting reports, and chatting.
import { API_BASE, SUMMARY_DEFAULT } from "../constants/dashboardConstants.js";

export async function fetchDashboardData() {
    const [billsRes, sumRes] = await Promise.all([
        fetch(`${API_BASE}/bills/`, { credentials: "include" }),
        fetch(`${API_BASE}/summary/`, { credentials: "include" }),
    ]);

    if (!billsRes.ok) throw new Error(`Bills API error: ${billsRes.status}`);
    if (!sumRes.ok) throw new Error(`Summary API error: ${sumRes.status}`);

    const [billsData, sumData] = await Promise.all([billsRes.json(), sumRes.json()]);

    return {
        billDocuments: Array.isArray(billsData?.items) ? billsData.items : [],
        dashboardSummary: { ...SUMMARY_DEFAULT, ...(sumData || {}) },
    };
}

export async function syncBillsFromGmail(windowValue) {
    const res = await fetch(`${API_BASE}/sync/`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ max_results: 100, time_window: windowValue }),
    });

    // 401 means Gmail isn't connected yet — send the user to sign in instead of failing.
    if (res.status === 401) {
        window.location.href = `${API_BASE}/connect-email/`;
        return { redirected: true };
    }

    if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`Sync failed: ${res.status} ${text}`);
    }

    return { redirected: false };
}

export async function cleanBillsDatabase() {
    const res = await fetch(`${API_BASE}/clean-db/`, {
        method: "DELETE",
        credentials: "include",
    });

    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
        throw new Error(payload?.error || `Clean DB failed: ${res.status}`);
    }
}

export async function exportReceiptsReportByIds(selectedIds) {
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

    return res;
}

export async function sendDashboardChatMessage({ message, previousResponseId }) {
    const res = await fetch(`${API_BASE}/chat/`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            message,
            previous_response_id: previousResponseId || null,
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

    return payload;
}
