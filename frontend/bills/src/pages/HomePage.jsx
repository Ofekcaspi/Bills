// The home/overview page: KPI totals plus a list of the most recent bills.
import { fileUrlFromSavedPath, formatDate, getBillStatus, formatMoney, formatSenderName } from "../utils/billUtils.js";

export default function HomePage(props) {
    const {
        animatedHomeBillsCount,
        animatedHomeTotal,
        animatedHomePaidCount,
        animatedHomePendingCount,
        recentItems,
        toggleBillPaidStatus,
    } = props;

    return (
                            <>
                                <section className="kpiGrid fadeIn">
                                    <article className="kpiCard bills">
                                        <div className="kpiLabel">
                                            <span className="kpiLabelIcon" aria-hidden="true">📄</span>
                                            <span>סה״כ חשבוניות</span>
                                        </div>
                                        <div className="kpiValue">{animatedHomeBillsCount}</div>
                                    </article>
                                    <article className="kpiCard amount">
                                        <div className="kpiLabel">
                                            <span className="kpiLabelIcon" aria-hidden="true">₪</span>
                                            <span>סכום כולל</span>
                                        </div>
                                        <div className="kpiValue">{formatMoney(animatedHomeTotal, "₪")}</div>
                                    </article>
                                    <article className="kpiCard paid">
                                        <div className="kpiLabel">
                                            <span className="kpiLabelIcon" aria-hidden="true">✅</span>
                                            <span>חשבוניות ששולמו</span>
                                        </div>
                                        <div className="kpiValue">{animatedHomePaidCount}</div>
                                    </article>
                                    <article className="kpiCard pending">
                                        <div className="kpiLabel">
                                            <span className="kpiLabelIcon" aria-hidden="true">🧾</span>
                                            <span>ממתין לתשלום</span>
                                        </div>
                                        <div className="kpiValue">{animatedHomePendingCount}</div>
                                    </article>
                                </section>

                                <section className="panelCard recentCard fadeIn interactiveCard">
                                    <div className="sectionHeader">
                                        <h2>חשבוניות אחרונות</h2>
                                        <span className="hint">מציג {recentItems.length} חשבוניות אחרונות</span>
                                    </div>

                                    {recentItems.length === 0 && <div className="emptyState">עדיין אין חשבוניות להצגה.</div>}

                                    {recentItems.length > 0 && (
                                        <div className="recentList">
                                            {recentItems.map((item) => {
                                                const status = getBillStatus(item);
                                                const subject = item.subject || item.filename || "ללא נושא";
                                                const fileUrl = fileUrlFromSavedPath(item.saved_path);
                                                const receivedDateText = item.msgDate ? formatDate(item.msgDate) : "—";
                                                const dueDateText = item.dueDate ? formatDate(item.dueDate) : "—";

                                                return (
                                                    <article key={`recent-${item.stableId}-${item.id}`} className={`recentItem ${status.tone}`}>
                                                        <div className="recentItemTop">
                                                            <div className="recentSubjectWrap">
                                                                <div className="recentSubject">{subject}</div>
                                                                <div className="recentCompanyName">{formatSenderName(item.sender)}</div>
                                                            </div>
                                                            <span className={`statusBadge ${status.tone}`}>{status.label}</span>
                                                        </div>

                                                        <div className="recentItemBody">
                                                            <div className="recentFields">
                                                                <div className="recentFieldRow">
                                                                    <span className="recentFieldLabel">סכום:</span>
                                                                    <span className="recentFieldValue">{formatMoney(item.amount, item.amount_currency || "₪")}</span>
                                                                </div>
                                                                <div className="recentFieldRow">
                                                                    <span className="recentFieldLabel">התקבל:</span>
                                                                    <span className="recentFieldValue">{receivedDateText}</span>
                                                                </div>
                                                                <div className="recentFieldRow">
                                                                    <span className="recentFieldLabel">יעד:</span>
                                                                    <span className="recentFieldValue">{dueDateText}</span>
                                                                </div>
                                                            </div>
                                                        </div>

                                                        <div className="recentRowActions">
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
                                                        </div>
                                                    </article>
                                                );
                                            })}
                                        </div>
                                    )}
                                </section>
                            </>
    );
}
