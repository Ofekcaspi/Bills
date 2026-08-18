// The analysis/charts page: spending trend, category breakdown,
//  and the AI insights chat.
import { TIME_WINDOW_OPTIONS } from "../constants/dashboardConstants.js";
import { formatDate, formatMoney } from "../utils/billUtils.js";

export default function AnalysisPage(props) {
    const {
        animatedAnalysisBillsCount,
        animatedAnalysisVisibleAmount,
        animatedAnalysisPaidCount,
        animatedAnalysisPendingCount,
        analysisTimeWindow,
        setAnalysisTimeWindow,
        analysisCategory,
        setAnalysisCategory,
        categories,
        anomalyInsight,
        analysisMonthFilter,
        setAnalysisMonthFilter,
        monthlySeries,
        isDenseMonthlyChart,
        chartCanvasHeight,
        chartPoints,
        chartAreaPath,
        chartLinePath,
        visibleAxisPoints,
        categoryChart,
        categoryLegendItems,
        chatMessagesRef,
        chatMessages,
        chatSending,
        chatError,
        chatInput,
        setChatInput,
        sendChatMessage,
    } = props;

    return (
                            <>
                                    <section className="kpiGrid fadeIn analysisChartsKpiGrid">
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
                                        <section className="panelCard chartTimeWindowCard analysisChartsFiltersCard">
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

                                        {anomalyInsight && (
                                            <section className="panelCard anomalyInsightCard" role="status" aria-live="polite">
                                                <div className="anomalyInsightRow">
                                                    <div className="anomalyInsightIcon" aria-hidden="true">
                                                        <svg className="anomalyInsightIconSvg" viewBox="0 0 24 24" focusable="false">
                                                            <circle cx="12" cy="12" r="9" />
                                                            <path d="M12 7.5v6" />
                                                            <path d="M12 16.8h.01" />
                                                        </svg>
                                                    </div>
                                                    <div className="anomalyInsightContent">
                                                        <p className="anomalyInsightText">
                                                            חשבון {anomalyInsight.category} האחרון עומד על {formatMoney(anomalyInsight.latestAmount, "₪")} והוא גבוה
                                                            ב-{Math.round(anomalyInsight.ratio * 100)}% לעומת החשבון הקודם ({formatMoney(anomalyInsight.previousAmount, "₪")}).
                                                        </p>
                                                        <p className="anomalyInsightMeta">
                                                            פער: +{formatMoney(anomalyInsight.delta, "₪")} בין {formatDate(anomalyInsight.previousDate)} ל-{formatDate(anomalyInsight.latestDate)}.
                                                        </p>
                                                    </div>
                                                </div>
                                            </section>
                                        )}

                                        <section className="insightsGrid analysisChartsInsightsGrid">
                                            <article className="panelCard chartCard analysisChartsPanelCard">
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
                                                            <div
                                                                className={`lineChartTrack ${isDenseMonthlyChart ? "dense" : ""}`}
                                                            >
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
                                                                                    title={`${point.label}: ${formatMoney(point.total)}`}
                                                                                    aria-label={`${point.label}: ${formatMoney(point.total)}`}
                                                                                />
                                                                            );
                                                                        })}
                                                                    </div>
                                                                </div>

                                                                <div className="lineChartAxis">
                                                                    {visibleAxisPoints.map((point) => {
                                                                        const active = analysisMonthFilter === point.key;

                                                                        return (
                                                                            <button
                                                                                key={`axis-${point.key}`}
                                                                                className={`lineChartAxisLabel ${active ? "active" : ""}`}
                                                                                onClick={() =>
                                                                                    setAnalysisMonthFilter((prev) => (prev === point.key ? "" : point.key))
                                                                                }
                                                                                style={{ left: `${point.x}%` }}
                                                                                title={`${point.label}: ${formatMoney(point.total)}`}
                                                                                aria-label={`${point.label}: ${formatMoney(point.total)}`}
                                                                            >
                                                                                <span className="lineChartAxisMonth">{point.label}</span>
                                                                                {(!isDenseMonthlyChart || active) && (
                                                                                    <span className="lineChartAxisAmount">{formatMoney(point.total, "₪")}</span>
                                                                                )}
                                                                            </button>
                                                                        );
                                                                    })}
                                                                </div>
                                                            </div>
                                                        </div>
                                                    </div>
                                                )}
                                            </article>

                                            <article className="panelCard categoryCard analysisChartsPanelCard">
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
                                                                <strong>{formatMoney(categoryChart.total, "₪")}</strong>
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
                                                                        <strong>{formatMoney(entry.total, "₪")}</strong>
                                                                    </div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                )}
                                            </article>
                                        </section>

                                        <section className="panelCard chatAssistantCard fadeIn analysisChartsChatDock">
                                            <div className="sectionHeader">
                                                <h2>צ׳אט תובנות</h2>
                                                <span className="hint">שאל שאלות על הנתונים שלך</span>
                                            </div>

                                            <div className="chatThread" ref={chatMessagesRef}>
                                                {chatMessages.map((msg, index) => (
                                                    <div
                                                        key={`chat-${index}`}
                                                        className={`chatBubble ${msg.role === "user" ? "user" : "assistant"}`}
                                                    >
                                                        {msg.text}
                                                    </div>
                                                ))}
                                                {chatSending && <div className="chatBubble assistant pending">חושב...</div>}
                                            </div>

                                            {chatError && <div className="chatError">{chatError}</div>}

                                            <div className="chatComposer">
                                        <textarea
                                            className="chatInput"
                                            value={chatInput}
                                            onChange={(event) => setChatInput(event.target.value)}
                                            // Enter sends the message; Shift+Enter adds a new line.
                                            onKeyDown={(event) => {
                                                if (event.key === "Enter" && !event.shiftKey) {
                                                    event.preventDefault();
                                                    sendChatMessage();
                                                }
                                            }}
                                            placeholder="לדוגמה: באיזה קטגוריה הייתה העלייה הגדולה ביותר החודש?"
                                            rows={2}
                                        />
                                                <button
                                                    className="btnPrimary"
                                                    onClick={sendChatMessage}
                                                    disabled={chatSending || !chatInput.trim()}
                                                >
                                                    {chatSending ? "שולח..." : "שלח"}
                                                </button>
                                            </div>
                                        </section>
                            </>
    );
}
