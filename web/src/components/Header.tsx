import React from "react";
import { BatchSummary } from "../types";
import { Check, AlertCircle } from "lucide-react";

interface Props {
  summary: BatchSummary | null;
}

export const Header: React.FC<Props> = ({ summary }) => {
  if (!summary) return null;

  const profFile = summary.files.find((f) => f.kind === "prof");
  const csvFile = summary.files.find((f) => f.kind === "csv");
  const logFile = summary.files.find((f) => f.kind === "log");

  return (
    <header style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
          <span>📈</span>
          <span>{summary.name}</span>
        </h1>
      </div>

      {/* Chips */}
      <div className="chips-container">
        <span className={`chip ${profFile?.filename ? "ok" : "no"}`}>
          {profFile?.filename ? <Check size={12} color="#166534" /> : "–"}
          <span>prof{profFile?.filename ? `: ${profFile.filename}` : ""}</span>
        </span>
        <span className={`chip ${csvFile?.filename ? "ok" : "no"}`}>
          {csvFile?.filename ? <Check size={12} color="#166534" /> : "–"}
          <span>CSV{csvFile?.filename ? `: ${csvFile.filename}` : ""}</span>
        </span>
        <span className={`chip ${logFile?.filename ? "ok" : "no"}`}>
          {logFile?.filename ? <Check size={12} color="#166534" /> : "–"}
          <span>LOG{logFile?.filename ? `: ${logFile.filename}` : ""}</span>
        </span>
        <span className="chip">
          <span>{summary.points_summary} ({summary.step_summary})</span>
        </span>
      </div>

      {/* Metrics Grid */}
      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-card-title">波形</div>
          <div className="metric-card-val">{summary.total_records.toLocaleString()}</div>
        </div>
        <div className="metric-card">
          <div className="metric-card-title">検体 (依頼No)</div>
          <div className="metric-card-val">{summary.samples_count ? summary.samples_count.toLocaleString() : "–"}</div>
        </div>
        <div className="metric-card">
          <div className="metric-card-title">項目</div>
          <div className="metric-card-val">{summary.items_count}</div>
        </div>
        <div className="metric-card">
          <div className="metric-card-title">CSV と対応</div>
          <div className="metric-card-val">
            {summary.csv_matched.toLocaleString()} / {summary.total_records.toLocaleString()}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-card-title">エラーフラグあり</div>
          <div className="metric-card-val" style={{ color: summary.error_count > 0 ? "var(--accent-err)" : "inherit" }}>
            {summary.error_count.toLocaleString()}
          </div>
        </div>
      </div>

      {/* Warnings */}
      {summary.warnings.length > 0 && (
        <div
          style={{
            backgroundColor: "#fffbeb",
            border: "1px solid #fde68a",
            borderRadius: 6,
            padding: "0.5rem 0.75rem",
            fontSize: "0.8125rem",
            color: "#92400e",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <AlertCircle size={16} />
          <span>確認事項 {summary.warnings.length} 件: {summary.warnings.join(" / ")}</span>
        </div>
      )}
    </header>
  );
};
