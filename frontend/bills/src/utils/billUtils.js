// Small helper functions for formatting and reading bill data, shared across the dashboard pages.
import { API_BASE, CONTROL_MARKS_REGEX, ELECTRICITY_CATEGORY } from "../constants/dashboardConstants.js";

export function toNumber(value) {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}

export function timeWindowDays(value) {
    const match = /^(\d+)d$/.exec(String(value || ""));
    if (!match) return null;
    const days = Number(match[1]);
    return Number.isFinite(days) && days > 0 ? days : null;
}

export function parseDate(value) {
    if (!value) return null;
    const date = value instanceof Date ? value : new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value) {
    if (!value) return "-";
    const date = parseDate(value);
    if (!date) return String(value);
    return date.toLocaleDateString("he-IL");
}

export function daysBetween(fromDate, toDate) {
    const msPerDay = 1000 * 60 * 60 * 24;
    return Math.ceil((toDate.getTime() - fromDate.getTime()) / msPerDay);
}

export function monthKey(date) {
    if (!date) return "";
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

export function monthLabel(key) {
    if (!key) return "";
    const [year, month] = key.split("-").map(Number);
    const date = new Date(year, month - 1, 1);
    return date.toLocaleDateString("he-IL", { month: "short", year: "2-digit" });
}

export function buildRecentMonthKeys(count) {
    const safeCount = Math.max(0, Number(count) || 0);
    const now = new Date();
    return Array.from({ length: safeCount }, (_, index) => {
        const shift = safeCount - index - 1;
        const date = new Date(now.getFullYear(), now.getMonth() - shift, 1);
        return monthKey(date);
    });
}

// Picks whichever ID is available so the same bill gets the same key every time, even if some data is missing.
export function getStableBillId(item) {
    return String(item.message_id ?? item.id ?? item.filename ?? "");
}

// Pulls the actual file name out of a file-download response header.
export function filenameFromContentDisposition(headerValue) {
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

export function formatMoney(value, currency = "") {
    if (value === null || value === undefined || value === "") return "-";
    const num = Number(value);
    if (!Number.isFinite(num)) return `${value} ${currency}`.trim();
    const formatted = new Intl.NumberFormat("he-IL", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(num);
    return `${formatted} ${currency}`.trim();
}

// Turns the path we stored in the database into a URL the browser can actually open.
export function fileUrlFromSavedPath(savedPath) {
    if (!savedPath) return "";
    const normalized = savedPath.replaceAll("\\", "/");
    const relative = normalized.replace(/^downloads\//, "");
    return `${API_BASE}/files/${encodeURI(relative)}`;
}

export function getBillStatus(item) {
    if (item.isPaid) return { tone: "paid", label: "שולם" };
    return { tone: "unpaid", label: "לא שולם" };
}

export function formatSenderName(value) {
    if (!value) return "שולח לא זוהה";
    const cleaned = String(value).replace(/<[^>]+>/g, "").trim();
    return cleaned || String(value);
}

export function senderInitials(value) {
    const label = formatSenderName(value);
    const tokens = label
        .split(/[\s._-]+/)
        .filter(Boolean)
        .slice(0, 2);
    if (!tokens.length) return "?";
    return tokens.map((token) => token[0]).join("").toUpperCase();
}

export function normalizeCategoryLabel(value) {
    return String(value || "").replace(CONTROL_MARKS_REGEX, "").trim();
}

export function isElectricityCategory(value) {
    return normalizeCategoryLabel(value) === ELECTRICITY_CATEGORY;
}
