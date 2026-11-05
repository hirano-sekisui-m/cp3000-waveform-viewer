import React from "react";
import { Download } from "lucide-react";
import { BatchSummary, RecordItem } from "../types";
import { downloadTableCsv } from "../api/client";

interface Props {
  summary: BatchSummary;
  records: RecordItem[];
}

export const TabInfo: React.FC<Props> = ({ summary, records }) => {
  return (
    <div className="tab-panel">
      {/* Table Section */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: "0.875rem", fontWeight: 700 }}>全波形の一覧 ({records.length} 件)</span>
          <button className="btn btn-outline btn-sm" onClick={downloadTableCsv}>
            <Download size={14} />
            <span>一覧を CSV で保存</span>
          </button>
        </div>

        <div className="table-container" style={{ maxHeight: 360 }}>
          <table className="data-table">
            <thead>
              <tr>
                {summary.columns
                  .filter((c) => !c.startsWith("_"))
                  .map((col) => (
                    <th key={col}>{col}</th>
                  ))}
              </tr>
            </thead>
            <tbody>
              {records.map((r, i) => (
                <tr key={i}>
                  {summary.columns
                    .filter((c) => !c.startsWith("_"))
                    .map((col) => (
                      <td key={col}>{r[col] != null ? String(r[col]) : "–"}</td>
                    ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Loaded Files Section */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12 }}>
        <span style={{ fontSize: "0.875rem", fontWeight: 700 }}>読み込んだファイル</span>
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>種類</th>
                <th>ファイル</th>
                <th>サイズ</th>
                <th>フォルダ</th>
              </tr>
            </thead>
            <tbody>
              {summary.files.map((f) => (
                <tr key={f.kind}>
                  <td>{f.kind}</td>
                  <td>{f.filename || "(なし)"}</td>
                  <td>{f.size != null ? `${f.size.toLocaleString()} bytes` : "–"}</td>
                  <td>{f.folder || "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ fontSize: "0.8125rem", color: "var(--text-muted)", marginTop: 4 }}>
          <div>・{summary.points_summary}、{summary.total_records.toLocaleString()} レコード ({summary.step_summary})</div>
        </div>
      </div>
    </div>
  );
};
