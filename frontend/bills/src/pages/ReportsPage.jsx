import { QUICK_FILTERS, SORT_OPTIONS, STATUS_OPTIONS, TIME_WINDOW_OPTIONS } from "../constants/dashboardConstants.js";
import { fileUrlFromSavedPath, formatDate, formatMoney, formatSenderName } from "../utils/billUtils.js";

export default function ReportsPage(props) {
    const {
        reportSearch,
        setReportSearch,
        reportCategory,
        setReportCategory,
        reportStatusFilter,
        setReportStatusFilter,
        reportTimeWindow,
        setReportTimeWindow,
        reportSortMode,
        setReportSortMode,
        reportQuickFilter,
        setReportQuickFilter,
        categories,
        clearReportFilters,
        exportReceiptsReport,
        isExportingReceiptsReport,
        reportExportableFilteredItems,
        reportError,
    } = props;

    return (
                                    <>
                                        <section className="panelCard filtersCard fadeIn">
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
                                                    disabled={isExportingReceiptsReport || reportExportableFilteredItems.length === 0}
                                                >
                                                    {isExportingReceiptsReport ? "מכין דוח..." : "הפק דוח קבלות"}
                                                </button>
                                            </div>
                                            {reportError && <div className="reportErrorBox">{reportError}</div>}
                                        </section>

                                        <section className="panelCard tableCard fadeIn">
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
                                                                            <span className="tableSender">{formatSenderName(item.sender)}</span>
                                                                        </div>
                                                                    </td>
                                                                    <td>
                                                                        <span className="statusBadge unpaid">{item.document_type === "receipt" ? "קבלה" : "חשבונית"}</span>
                                                                    </td>
                                                                    <td>
                                                                        <span className="categoryBadge tableBadge">{item.category || "ללא קטגוריה"}</span>
                                                                    </td>
                                                                    <td className="tableAmount">{formatMoney(item.amount, item.amount_currency || "₪")}</td>
                                                                    <td className="tableDate">{formatDate(item.msgDate)}</td>
                                                                    <td>
                                                                        <div className="tableActions">
                                                                            <a className="btnSecondary buttonSmall" href={fileUrl} target="_blank" rel="noreferrer">
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
    );
}
