import React, { useState, useEffect } from "react";
import Plot from "react-plotly.js";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { BatchSummary, DetailWaveformResponse, RecordItem } from "../types";
import { getWaveformDetail } from "../api/client";
import { SidebarOptions } from "./Sidebar";
import { WindowSelector } from "./WindowSelector";

interface Props {
  summary: BatchSummary;
  records: RecordItem[];
  options: SidebarOptions;
  onChangeOptions: (opts: Partial<SidebarOptions>) => void;
}

export const TabDetail: React.FC<Props> = ({ summary, records, options, onChangeOptions }) => {
  const [selectedNo, setSelectedNo] = useState<number>(records[0]?.No || 1);
  const [detail, setDetail] = useState<DetailWaveformResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const isChromogenic = options.selectedMode === "比色項目";

  useEffect(() => {
    if (records.length > 0 && (!selectedNo || !records.some((r) => r.No === selectedNo))) {
      setSelectedNo(records[0].No);
    }
  }, [records]);

  useEffect(() => {
    if (!selectedNo) return;
    setLoading(true);
    getWaveformDetail(selectedNo, {
      window_end_sec: options.windowEndSec ? parseFloat(options.windowEndSec) : null,
      coag_ratio: options.coagRatio,
      ref_point_idx: options.chromoRefPointIdx,
    })
      .then((res) => {
        setDetail(res);
      })
      .catch((err) => {
        console.error("Failed to get detail:", err);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [selectedNo, options.windowEndSec, options.coagRatio, options.chromoRefPointIdx]);

  const handleStep = (delta: number) => {
    if (records.length === 0) return;
    const idx = records.findIndex((r) => r.No === selectedNo);
    if (idx === -1) return;
    const nextIdx = (idx + delta + records.length) % records.length;
    setSelectedNo(records[nextIdx].No);
  };

  if (!detail) {
    return <div style={{ padding: 20 }}>読み込み中…</div>;
  }

  const numPanels = isChromogenic ? 3 : 4;
  const traces: any[] = [];
  const c = detail.calculated;

  if (isChromogenic) {
    // 1. Raw
    traces.push({
      type: "scatter",
      mode: "lines",
      x: detail.time,
      y: detail.raw,
      name: "生波形",
      yaxis: "y",
      line: { color: "#2563eb", width: 1.5 },
    });
    // 2. Base aligned / Scaled
    traces.push({
      type: "scatter",
      mode: "lines",
      x: detail.time,
      y: detail.base_aligned || detail.scaled,
      name: "吸光度変化 (基準点=0)",
      yaxis: "y2",
      line: { color: "#2563eb", width: 1.5 },
    });
    // 3. Abs slope
    if (detail.abs_slope) {
      traces.push({
        type: "scatter",
        mode: "lines",
        x: detail.time,
        y: detail.abs_slope,
        name: "吸光度変化率",
        yaxis: "y3",
        line: { color: "#ea580c", width: 1.5 },
      });
    }
  } else {
    // Coagulation: Raw, Scaled, Slope, Acceleration
    traces.push({
      type: "scatter",
      mode: "lines",
      x: detail.time,
      y: detail.raw,
      name: "生波形",
      yaxis: "y",
      line: { color: "#2563eb", width: 1.5 },
    });
    traces.push({
      type: "scatter",
      mode: "lines",
      x: detail.time,
      y: detail.scaled,
      name: "凝固波形 (0–100%)",
      yaxis: "y2",
      line: { color: "#2563eb", width: 1.5 },
    });
    traces.push({
      type: "scatter",
      mode: "lines",
      x: detail.time,
      y: detail.slope,
      name: "速度波形 (%/s)",
      yaxis: "y3",
      line: { color: "#16a34a", width: 1.5 },
    });
    traces.push({
      type: "scatter",
      mode: "lines",
      x: detail.time,
      y: detail.acceleration,
      name: "加速度波形 (%/s²)",
      yaxis: "y4",
      line: { color: "#9333ea", width: 1.5 },
    });
  }

  // Vertical line shapes (Coagulation only)
  const shapes: any[] = [];
  if (!isChromogenic) {
    const addVline = (x: number | null | undefined, color: string, dash = "solid") => {
      if (x == null || !isFinite(x)) return;
      shapes.push({
        type: "line",
        xref: "x",
        yref: "paper",
        x0: x,
        x1: x,
        y0: 0,
        y1: 1,
        line: { color, width: 1.5, dash },
      });
    };

    addVline(c.Tc1, "#94a3b8", "dot");
    addVline(c.Te1, "#94a3b8", "dot");
    addVline(c.Tc2, "#ef4444", "dash");
    addVline(c.Te2, "#f97316", "dash");
    addVline(c.device_val, "#d97706", "solid");
  }

  const layout: any = {
    autosize: true,
    height: numPanels * 160,
    margin: { l: 60, r: 20, t: 20, b: 40 },
    paper_bgcolor: "transparent",
    plot_bgcolor: "#ffffff",
    hovermode: "x unified",
    showlegend: false,
    grid: { rows: numPanels, columns: 1, pattern: "coupled" },
    shapes,
  };

  const titles = isChromogenic
    ? ["生波形 (0.1 mAbs)", "吸光度変化 (基準点=0, 0.1 mAbs)", "吸光度変化率 (mAbs/min.)"]
    : ["生波形", "凝固波形 (0–100 %)", "速度 (%/s)", "加速度 (%/s²)"];

  titles.forEach((t, i) => {
    const yKey = i === 0 ? "yaxis" : `yaxis${i + 1}`;
    layout[yKey] = {
      title: { text: t, font: { size: 10 } },
      gridcolor: "#f1f5f9",
    };
  });

  layout.xaxis = {
    title: { text: "時間 (秒)", font: { size: 11 } },
    gridcolor: "#f1f5f9",
  };

  return (
    <div className="tab-panel">
      {/* Navigation & Control bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 12,
          padding: "0.5rem 0.75rem",
          backgroundColor: "#fff",
          border: "1px solid var(--border)",
          borderRadius: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button className="btn btn-outline btn-sm" onClick={() => handleStep(-1)}>
            <ChevronLeft size={16} />
            <span>前へ</span>
          </button>
          <select
            className="select-box"
            style={{ width: 340, padding: "0.25rem 0.5rem", fontSize: "0.8125rem" }}
            value={selectedNo}
            onChange={(e) => setSelectedNo(parseInt(e.target.value))}
          >
            {records.map((r) => (
              <option key={r.No} value={r.No}>
                No {r.No} ・ {r._label || `${r.依頼No} / ${r.項目名}`}
              </option>
            ))}
          </select>
          <button className="btn btn-outline btn-sm" onClick={() => handleStep(1)}>
            <span>次へ</span>
            <ChevronRight size={16} />
          </button>
          {loading && <span style={{ fontSize: "0.8125rem", color: "var(--text-muted)" }}>読込中…</span>}
        </div>

        {/* Window Selector */}
        <WindowSelector
          isChromogenic={isChromogenic}
          value={options.windowEndSec}
          onChange={(val) => onChangeOptions({ windowEndSec: val })}
          refPointIdx={options.chromoRefPointIdx}
          onChangeRefPoint={(idx) => onChangeOptions({ chromoRefPointIdx: idx })}
          timePoints={summary.time_points}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 20 }}>
        {/* Left: Chart */}
        <div
          style={{
            backgroundColor: "#fff",
            border: "1px solid var(--border)",
            borderRadius: 8,
            padding: 10,
          }}
        >
          <Plot
            data={traces}
            layout={layout}
            useResizeHandler={true}
            style={{ width: "100%", height: "100%" }}
            config={{ displaylogo: false, responsive: true }}
          />
          {!isChromogenic && (
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: 6 }}>
              縦線: 点線 = Tc1 / Te1、破線 = Tc2 / Te2、橙の実線 = 装置の測定値(CSV)
            </div>
          )}
        </div>

        {/* Right: Calculated values & Metadata */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Calculated metrics table */}
          <div style={{ backgroundColor: "#fff", border: "1px solid var(--border)", borderRadius: 8, padding: 14 }}>
            <h3 style={{ fontSize: "0.875rem", fontWeight: 700, marginBottom: 8 }}>計算値</h3>
            <table style={{ width: "100%", fontSize: "0.8125rem", borderCollapse: "collapse" }}>
              <tbody>
                {!isChromogenic ? (
                  <>
                    <tr>
                      <td style={{ color: "var(--text-muted)", padding: "4px 0" }}>Tc2</td>
                      <td style={{ textAlign: "right", fontWeight: 600 }}>{c.Tc2 != null ? `${c.Tc2} s` : "–"}</td>
                    </tr>
                    <tr>
                      <td style={{ color: "var(--text-muted)", padding: "4px 0" }}>Te2</td>
                      <td style={{ textAlign: "right", fontWeight: 600 }}>{c.Te2 != null ? `${c.Te2} s` : "–"}</td>
                    </tr>
                    <tr>
                      <td style={{ color: "var(--text-muted)", padding: "4px 0" }}>Tc1</td>
                      <td style={{ textAlign: "right", fontWeight: 600 }}>{c.Tc1 != null ? `${c.Tc1} s` : "–"}</td>
                    </tr>
                    <tr>
                      <td style={{ color: "var(--text-muted)", padding: "4px 0" }}>Te1</td>
                      <td style={{ textAlign: "right", fontWeight: 600 }}>{c.Te1 != null ? `${c.Te1} s` : "–"}</td>
                    </tr>
                    <tr>
                      <td style={{ color: "var(--text-muted)", padding: "4px 0" }}>装置の測定値</td>
                      <td style={{ textAlign: "right", fontWeight: 600 }}>{c.device_val != null ? `${c.device_val} s` : "–"}</td>
                    </tr>
                    <tr>
                      <td style={{ color: "var(--text-muted)", padding: "4px 0" }}>Tc2 − 装置値</td>
                      <td style={{ textAlign: "right", fontWeight: 600 }}>{c.tc2_diff != null ? `${c.tc2_diff} s` : "–"}</td>
                    </tr>
                    <tr>
                      <td style={{ color: "var(--text-muted)", padding: "4px 0" }}>速度の最大</td>
                      <td style={{ textAlign: "right", fontWeight: 600 }}>
                        {c.vmax != null ? `${c.vmax} %/s (${c.t_vmax}s)` : "–"}
                      </td>
                    </tr>
                  </>
                ) : (
                  <>
                    <tr>
                      <td style={{ color: "var(--text-muted)", padding: "4px 0" }}>装置の測定値</td>
                      <td style={{ textAlign: "right", fontWeight: 600 }}>{c.device_val != null ? `${c.device_val}` : "–"}</td>
                    </tr>
                    <tr>
                      <td style={{ color: "var(--text-muted)", padding: "4px 0" }}>速度の最大 (vmax)</td>
                      <td style={{ textAlign: "right", fontWeight: 600 }}>
                        {c.vmax != null ? `${c.vmax} %/s` : "–"}
                      </td>
                    </tr>
                    <tr>
                      <td style={{ color: "var(--text-muted)", padding: "4px 0" }}>最大速度の時刻</td>
                      <td style={{ textAlign: "right", fontWeight: 600 }}>
                        {c.t_vmax != null ? `${c.t_vmax} s` : "–"}
                      </td>
                    </tr>
                  </>
                )}
              </tbody>
            </table>
          </div>

          {/* Record Metadata table */}
          <div style={{ backgroundColor: "#fff", border: "1px solid var(--border)", borderRadius: 8, padding: 14 }}>
            <h3 style={{ fontSize: "0.875rem", fontWeight: 700, marginBottom: 8 }}>レコード情報</h3>
            <div style={{ maxHeight: 280, overflowY: "auto" }}>
              <table style={{ width: "100%", fontSize: "0.8125rem", borderCollapse: "collapse" }}>
                <tbody>
                  {Object.entries(detail.record_info).map(([k, v]) => (
                    <tr key={k} style={{ borderBottom: "1px solid #f1f5f9" }}>
                      <td style={{ color: "var(--text-muted)", padding: "4px 0", width: "40%" }}>{k}</td>
                      <td style={{ textAlign: "right", padding: "4px 0", fontWeight: 500 }}>{String(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
