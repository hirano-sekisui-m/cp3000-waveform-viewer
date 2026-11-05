import React, { useState, useEffect } from "react";
import Plot from "react-plotly.js";
import { Download, CheckSquare } from "lucide-react";
import { BatchSummary, RecordItem, WaveformSeries } from "../types";
import { deriveWaveforms, downloadWaveformsCsv } from "../api/client";
import { CHROMO_WAVE_TYPES, COAG_WAVE_TYPES, SidebarOptions } from "./Sidebar";
import { WindowSelector } from "./WindowSelector";

interface Props {
  summary: BatchSummary;
  records: RecordItem[];
  options: SidebarOptions;
  onChangeOptions: (opts: Partial<SidebarOptions>) => void;
}

const PALETTE = [
  "#2563eb", // blue
  "#dc2626", // red
  "#16a34a", // green
  "#9333ea", // purple
  "#ea580c", // orange
  "#0891b2", // cyan
  "#db2777", // pink
  "#475569", // slate
];

export const TabOverlay: React.FC<Props> = ({ summary, records, options, onChangeOptions }) => {
  const [selectedPositions, setSelectedPositions] = useState<number[]>([]);
  const [seriesData, setSeriesData] = useState<WaveformSeries[]>([]);
  const [loading, setLoading] = useState(false);
  const [downloadKind, setDownloadKind] = useState("raw");

  const isChromogenic = options.selectedMode === "比色項目";
  const waveTypeDict = isChromogenic ? CHROMO_WAVE_TYPES : COAG_WAVE_TYPES;

  // Auto-select first 5 records initially or when records change
  useEffect(() => {
    if (records.length > 0) {
      const validSelected = selectedPositions.filter((p) => records.some((r) => r._pos === p));
      if (validSelected.length === 0) {
        setSelectedPositions(records.slice(0, Math.min(5, records.length)).map((r) => r._pos));
      } else {
        setSelectedPositions(validSelected);
      }
    } else {
      setSelectedPositions([]);
    }
  }, [records]);

  // Fetch derived waveforms when selection or calc options change
  useEffect(() => {
    if (selectedPositions.length === 0) {
      setSeriesData([]);
      return;
    }
    setLoading(true);
    deriveWaveforms({
      positions: selectedPositions,
      window_end_sec: options.windowEndSec ? parseFloat(options.windowEndSec) : null,
      coag_ratio: options.coagRatio,
      align: options.align,
      baseline: options.baseline,
      thin: options.thin,
    })
      .then((res) => {
        setSeriesData(res.series);
      })
      .catch((err) => {
        console.error("Failed to derive waveforms:", err);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [
    selectedPositions,
    options.windowEndSec,
    options.coagRatio,
    options.align,
    options.baseline,
    options.thin,
  ]);

  const handleSelectRow = (pos: number, isMulti: boolean) => {
    if (isMulti) {
      if (selectedPositions.includes(pos)) {
        setSelectedPositions(selectedPositions.filter((p) => p !== pos));
      } else {
        if (selectedPositions.length >= 300) return;
        setSelectedPositions([...selectedPositions, pos]);
      }
    } else {
      setSelectedPositions([pos]);
    }
  };

  const handleSelectAllVisible = () => {
    if (selectedPositions.length === records.length) {
      setSelectedPositions([]);
    } else {
      setSelectedPositions(records.slice(0, 300).map((r) => r._pos));
    }
  };

  const handleDownloadCsv = () => {
    if (selectedPositions.length === 0) return;
    downloadWaveformsCsv({
      positions: selectedPositions,
      kind: downloadKind,
      window_end_sec: options.windowEndSec ? parseFloat(options.windowEndSec) : null,
      coag_ratio: options.coagRatio,
    });
  };

  // Build Plotly layout and traces
  const waveTypes = options.waveTypes.filter((t) => t in waveTypeDict);
  const numPanels = Math.max(1, waveTypes.length);

  const traces: any[] = [];

  waveTypes.forEach((kind, panelIdx) => {
    const yAxisId = panelIdx === 0 ? "y" : `y${panelIdx + 1}`;

    seriesData.forEach((s, sIdx) => {
      const color = PALETTE[sIdx % PALETTE.length];
      const yData =
        kind === "scaled"
          ? s.scaled
          : kind === "endpoint_scaled"
          ? s.endpoint_scaled
          : kind === "slope"
          ? s.slope
          : kind === "acceleration"
          ? s.acceleration
          : kind === "abs_slope" && s.abs_slope
          ? s.abs_slope
          : s.raw;

      traces.push({
        type: "scattergl",
        mode: "lines",
        x: s.time,
        y: yData,
        name: s.label,
        yaxis: yAxisId,
        line: { color, width: 1.5 },
        showlegend: panelIdx === 0,
        legendgroup: `group-${s.position}`,
        hovertemplate: `<b>%{y:.2f}</b><extra>${s.label}</extra>`,
      });

      // Tc2 marker on panels (Coagulation only)
      if (!isChromogenic && options.showTc2 && s.tc2 != null && isFinite(s.tc2)) {
        traces.push({
          type: "scattergl",
          mode: "markers",
          x: [s.tc2],
          y: [0],
          yaxis: yAxisId,
          marker: { symbol: "triangle-up", size: 8, color },
          showlegend: false,
          legendgroup: `group-${s.position}`,
          hoverinfo: "skip",
        });
      }
    });
  });

  const layout: any = {
    autosize: true,
    height: Math.max(500, numPanels * 220),
    margin: { l: 60, r: 20, t: 30, b: 40 },
    paper_bgcolor: "transparent",
    plot_bgcolor: "#ffffff",
    hovermode: "x unified",
    legend: { orientation: "h", y: 1.1, x: 0 },
    grid: { rows: numPanels, columns: 1, pattern: "coupled" },
  };

  waveTypes.forEach((kind, panelIdx) => {
    const yKey = panelIdx === 0 ? "yaxis" : `yaxis${panelIdx + 1}`;
    layout[yKey] = {
      title: { text: waveTypeDict[kind] || kind, font: { size: 11 } },
      gridcolor: "#f1f5f9",
      zerolinecolor: "#cbd5e1",
    };
  });

  const xAxisTitle =
    isChromogenic || options.align === "off" ? "測定時間 (秒)" : "そろえた時間 (秒)";
  layout.xaxis = {
    title: { text: xAxisTitle, font: { size: 12 } },
    gridcolor: "#f1f5f9",
    zerolinecolor: "#cbd5e1",
  };
  if (options.xStart || options.xEnd) {
    layout.xaxis.range = [
      options.xStart ? parseFloat(options.xStart) : 0,
      options.xEnd ? parseFloat(options.xEnd) : 600,
    ];
  }

  return (
    <div className="tab-panel">
      <div className="overlay-layout">
        {/* Left: Waveform List Table */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: "0.875rem", fontWeight: 600 }}>
              波形一覧 ({records.length} 件)
            </span>
            <button className="btn btn-outline btn-sm" onClick={handleSelectAllVisible}>
              <CheckSquare size={12} />
              <span>{selectedPositions.length === records.length ? "解除" : "先頭選択"}</span>
            </button>
          </div>

          <div className="table-container" style={{ height: "540px" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 40 }}>No</th>
                  <th>依頼No</th>
                  <th>項目名</th>
                  <th>{isChromogenic ? "処理値" : "Tc2"}</th>
                  <th>測定値</th>
                </tr>
              </thead>
              <tbody>
                {records.map((r) => {
                  const isSelected = selectedPositions.includes(r._pos);
                  return (
                    <tr
                      key={r.No}
                      className={isSelected ? "selected" : ""}
                      onClick={(e) => handleSelectRow(r._pos, e.ctrlKey || e.shiftKey || e.metaKey)}
                      style={{ cursor: "pointer" }}
                    >
                      <td>{r.No}</td>
                      <td>{r.依頼No || r.内部依頼No || "–"}</td>
                      <td>{r.項目名 || "–"}</td>
                      <td>
                        {isChromogenic
                          ? (r.処理値 != null ? r.処理値 : "–")
                          : (r["Tc2(計算)"] != null ? r["Tc2(計算)"] : "–")}
                      </td>
                      <td>{r.測定値 != null ? r.測定値 : "–"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            ※行クリックで選択、Ctrl/Shift+クリックで複数選択 (最大300本)
          </span>
        </div>

        {/* Right: Waveform Chart */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {/* Top Control Bar directly above the chart */}
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
            {/* Window selector placed right above chart */}
            <WindowSelector
              isChromogenic={isChromogenic}
              value={options.windowEndSec}
              onChange={(val) => onChangeOptions({ windowEndSec: val })}
            />

            {/* CSV Download bar */}
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: "0.8125rem", color: "var(--text-muted)" }}>
                {selectedPositions.length} 本選択中 {loading ? "(計算中…)" : ""}
              </span>
              <select
                className="select-box"
                style={{ width: "auto", padding: "0.2rem 0.5rem", fontSize: "0.8125rem" }}
                value={downloadKind}
                onChange={(e) => setDownloadKind(e.target.value)}
              >
                {Object.entries(waveTypeDict).map(([k, lbl]) => (
                  <option key={k} value={k}>
                    {lbl}
                  </option>
                ))}
              </select>
              <button
                className="btn btn-outline btn-sm"
                onClick={handleDownloadCsv}
                disabled={selectedPositions.length === 0}
              >
                <Download size={14} />
                <span>CSV保存</span>
              </button>
            </div>
          </div>

          <div
            style={{
              backgroundColor: "#fff",
              border: "1px solid var(--border)",
              borderRadius: 8,
              padding: 10,
              minHeight: 520,
            }}
          >
            {seriesData.length > 0 ? (
              <Plot
                data={traces}
                layout={layout}
                useResizeHandler={true}
                style={{ width: "100%", height: "100%" }}
                config={{ displaylogo: false, responsive: true }}
              />
            ) : (
              <div
                style={{
                  height: 480,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--text-muted)",
                }}
              >
                波形を選択してください
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
