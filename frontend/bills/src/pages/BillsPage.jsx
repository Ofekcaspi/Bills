import { QUICK_FILTERS, SORT_OPTIONS, STATUS_OPTIONS, TIME_WINDOW_OPTIONS } from "../constants/dashboardConstants.js";
import { fileUrlFromSavedPath, formatDate, getBillStatus, formatMoney, formatSenderName } from "../utils/billUtils.js";

export default function BillsPage(props) {
    const {
        animatedAnalysisBillsCount,
        animatedAnalysisVisibleAmount,
        animatedAnalysisPaidCount,
        animatedAnalysisPendingCount,
        billsSearchQuery,
        setBillsSearchQuery,
        selectedBillCategory,
        setSelectedBillCategory,
        selectedBillStatus,
        setSelectedBillStatus,
        billsTimeWindow,
        setBillsTimeWindow,
        billsSortMode,
        setBillsSortMode,
        selectedBillQuickFilter,
        setSelectedBillQuickFilter,
        categories,
        filteredBills,
        clearFilters,
        deleteAllBillRecords,
        toggleBillPaidStatus,
        showLocalReminderToast,
    } = props;

    return (
                            <>
                                    <section className="kpiGrid fadeIn">
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
                                            <div className="kpiValue">{formatMoney(animatedAnalysisVisibleAmount, "₪")}</div>
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
                                        <section className="panelCard filtersCard fadeIn">

                                            <div className="filtersGrid">
                                                <label className="searchField prominentSearch">
                                                    <span className="searchIcon" aria-hidden="true">🔎</span>
                                                    <input
                                                        className="input searchInput"
                                                        value={billsSearchQuery}
                                                        onChange={(event) => setBillsSearchQuery(event.target.value)}
                                                        placeholder="חיפוש לפי נושא, שולח, שם קובץ או קטגוריה"
                                                    />
                                                </label>

                                                <select className="select" value={selectedBillCategory} onChange={(event) => setSelectedBillCategory(event.target.value)}>
                                                    <option value="all">כל הקטגוריות</option>
                                                    {categories.map((option) => (
                                                        <option key={option} value={option}>
                                                            {option}
                                                        </option>
                                                    ))}
                                                </select>

                                                <select
                                                    className="select"
                                                    value={selectedBillStatus}
                                                    onChange={(event) => setSelectedBillStatus(event.target.value)}
                                                >
                                                    {STATUS_OPTIONS.map((option) => (
                                                        <option key={option.value} value={option.value}>
                                                            {option.label}
                                                        </option>
                                                    ))}
                                                </select>

                                                <select
                                                    className="select"
                                                    value={billsTimeWindow}
                                                    onChange={(event) => setBillsTimeWindow(event.target.value)}
                                                >
                                                    {TIME_WINDOW_OPTIONS.map((option) => (
                                                        <option key={option.value} value={option.value}>
                                                            תקופת זמן: {option.label}
                                                        </option>
                                                    ))}
                                                </select>

                                                <select className="select" value={billsSortMode} onChange={(event) => setBillsSortMode(event.target.value)}>
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
                                                        className={`chipButton ${selectedBillQuickFilter === filter.value ? "active" : ""}`}
                                                        onClick={() => setSelectedBillQuickFilter(filter.value)}
                                                    >
                                                        {filter.label}
                                                    </button>
                                                ))}
                                            </div>

                                            <div className="filtersActions">
                                                <button className="btnGhost" onClick={clearFilters}>
                                                    נקה פילטרים
                                                </button>
                                                <button className="btnDanger" onClick={deleteAllBillRecords}>
                                                    נקה מסד נתונים
                                                </button>
                                            </div>
                                        </section>

                                        <section className="panelCard tableCard fadeIn">
                                            <div className="sectionHeader">
                                                <h2>טבלת חשבוניות</h2>
                                                <span className="hint">מציג {filteredBills.length} חשבוניות</span>
                                            </div>

                                            {filteredBills.length === 0 && (
                                                <div className="emptyState">לא נמצאו חשבונות לפי הסינון הנוכחי.</div>
                                            )}

                                            {filteredBills.length > 0 && (
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
                                                        {filteredBills.map((item, index) => {
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
                                                                            <span className="tableSender">{formatSenderName(item.sender)}</span>
                                                                        </div>
                                                                    </td>
                                                                    <td>
                                                                        <span className="categoryBadge tableBadge">{item.category || "ללא קטגוריה"}</span>
                                                                    </td>
                                                                    <td>
                                                                        <span className={`statusBadge ${status.tone}`}>{status.label}</span>
                                                                    </td>
                                                                    <td className="tableAmount">{formatMoney(item.amount, item.amount_currency || "₪")}</td>
                                                                    <td className="tableDate">{formatDate(item.msgDate)}</td>
                                                                    <td>
                                                                        <div className="tableActions">
                                                                            {item.saved_path ? (
                                                                                <a className="btnSecondary buttonSmall" href={fileUrl} target="_blank" rel="noreferrer">
                                                                                    צפייה
                                                                                </a>
                                                                            ) : (
                                                                                <button className="btnSecondary buttonSmall" disabled>
                                                                                    אין קובץ
                                                                                </button>
                                                                            )}
                                                                            <button
                                                                                className="btnPrimary buttonSmall"
                                                                                onClick={() => toggleBillPaidStatus(item.stableId, subject)}
                                                                            >
                                                                                {item.isPaid ? "בטל שולם" : "סמן כשולם"}
                                                                            </button>
                                                                            <button className="btnGhost buttonSmall" onClick={() => showLocalReminderToast(item)}>
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
    );
}
