import React, { useState, useEffect } from "react";
import { Sidebar, SidebarOptions } from "./components/Sidebar";
import { Header } from "./components/Header";
import { TabOverlay } from "./components/TabOverlay";
import { TabDetail } from "./components/TabDetail";
import { TabInfo } from "./components/TabInfo";
import { BatchSummary, FolderEntry, RecordItem } from "./types";
import {
  getSettings,
  updateSettings,
  listFolders,
  loadBatch,
  uploadBatchFiles,
  queryRecords,
} from "./api/client";

export const App: React.FC = () => {
  const [options, setOptions] = useState<SidebarOptions>({
    sourceType: "folder",
    rootPath: "",
    selectedBatchFolder: "",
    selectedMode: "",
    waveTypes: ["raw", "scaled", "slope"],
    align: "off",
    xStart: "",
    xEnd: "",
    baseline: false,
    showTc2: true,
    thin: true,
    windowEndSec: "",
    coagRatio: 0.5,
    chromoRefPointIdx: 0,
  });

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [folderEntries, setFolderEntries] = useState<FolderEntry[]>([]);
  const [summary, setSummary] = useState<BatchSummary | null>(null);
  const [records, setRecords] = useState<RecordItem[]>([]);
  const [activeTab, setActiveTab] = useState<"overlay" | "detail" | "info">("overlay");
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Initialize: load settings and list folders
  useEffect(() => {
    getSettings()
      .then((settings) => {
        const root = settings.root || "data-source";
        setOptions((prev) => ({ ...prev, rootPath: root }));
        return listFolders(root).then((folders) => {
          setFolderEntries(folders);
          if (folders.length > 0) {
            // Newest folder or file is at index 0
            const target = (settings.last_batch && folders.some((f) => f.entry_id === settings.last_batch))
              ? settings.last_batch
              : folders[0].entry_id;
            setOptions((prev) => ({ ...prev, selectedBatchFolder: target }));
            handleLoadBatch(target, folders);
          }
        });
      })
      .catch((err) => {
        console.error("Initialization error:", err);
      });
  }, []);

  const autoSelectMode = (modes: string[]): { mode: string; waveTypes: string[] } => {
    if (modes.length === 1) {
      const single = modes[0];
      return {
        mode: single,
        waveTypes: single === "比色項目" ? ["raw", "base_aligned", "abs_slope"] : ["raw", "scaled", "slope"],
      };
    }
    if (modes.includes("比色項目") && !modes.includes("凝固項目")) {
      return { mode: "比色項目", waveTypes: ["raw", "base_aligned", "abs_slope"] };
    }
    const defaultMode = modes[0] || "凝固項目";
    return {
      mode: defaultMode,
      waveTypes: defaultMode === "比色項目" ? ["raw", "base_aligned", "abs_slope"] : ["raw", "scaled", "slope"],
    };
  };

  const handleRefreshFolders = async (customRoot?: string) => {
    try {
      const rootToUse = customRoot ?? options.rootPath;
      if (customRoot) {
        setOptions((prev) => ({ ...prev, rootPath: customRoot }));
      }
      const folders = await listFolders(rootToUse);
      setFolderEntries(folders);
      if (folders.length > 0 && !folders.some((f) => f.entry_id === options.selectedBatchFolder)) {
        handleLoadBatch(folders[0].entry_id, folders);
      }
    } catch (err: any) {
      setErrorMsg(err.message);
    }
  };

  const handleLoadBatch = async (entryId: string, entries = folderEntries) => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const match = entries.find((f) => f.entry_id === entryId);
      const req = match?.csv_path
        ? { csv_path: match.csv_path }
        : { entry_id: entryId, folder_path: match?.folder_path || entryId };

      const sum = await loadBatch(req);
      setSummary(sum);

      const auto = autoSelectMode(sum.modes);
      // Clean reload: reset all waveform & plot settings to defaults
      setOptions((prev) => ({
        ...prev,
        selectedBatchFolder: entryId,
        selectedMode: auto.mode,
        waveTypes: auto.waveTypes,
        windowEndSec: "",
        xStart: "",
        xEnd: "",
        baseline: false,
        align: "off",
        showTc2: true,
        coagRatio: 0.5,
        chromoRefPointIdx: 0,
      }));

      await fetchRecords(sum, auto.mode, "");
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleUploadFiles = async (files: File[]) => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const sum = await uploadBatchFiles(files);
      setSummary(sum);

      const auto = autoSelectMode(sum.modes);
      // Clean reload: reset all waveform & plot settings to defaults
      setOptions((prev) => ({
        ...prev,
        sourceType: "upload",
        selectedBatchFolder: "",
        selectedMode: auto.mode,
        waveTypes: auto.waveTypes,
        windowEndSec: "",
        xStart: "",
        xEnd: "",
        baseline: false,
        align: "off",
        showTc2: true,
        coagRatio: 0.5,
        chromoRefPointIdx: 0,
      }));

      await fetchRecords(sum, auto.mode, "");
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchRecords = async (currentSummary: BatchSummary, mode?: string, windowEndSecOverride?: string | null) => {
    try {
      const winVal = windowEndSecOverride !== undefined ? windowEndSecOverride : options.windowEndSec;
      const res = await queryRecords({
        mode: mode || undefined,
        window_end_sec: winVal ? parseFloat(winVal) : null,
        coag_ratio: options.coagRatio,
      });
      setRecords(res.records);
    } catch (err: any) {
      console.error("Failed to query records:", err);
    }
  };

  const handleChangeOptions = (partial: Partial<SidebarOptions>) => {
    const updated = { ...options, ...partial };

    // When switching measurement mode, completely reset range/alignment/reference settings
    if (partial.selectedMode !== undefined && partial.selectedMode !== options.selectedMode) {
      const isChrom = partial.selectedMode === "比色項目";
      updated.waveTypes = isChrom
        ? ["raw", "base_aligned", "abs_slope"]
        : ["raw", "scaled", "slope"];
      updated.windowEndSec = "";
      updated.xStart = "";
      updated.xEnd = "";
      updated.align = "off";
      updated.chromoRefPointIdx = 0;
    } else if (updated.selectedMode === "比色項目" && updated.waveTypes.includes("scaled")) {
      updated.waveTypes = updated.waveTypes
        .map((t) => (t === "scaled" ? "base_aligned" : t))
        .filter((t, i, arr) => arr.indexOf(t) === i);
    }
    setOptions(updated);

    if (partial.rootPath !== undefined) {
      updateSettings({ root: partial.rootPath });
    }

    if (partial.selectedMode !== undefined && summary) {
      fetchRecords(summary, partial.selectedMode, "");
    } else if (partial.windowEndSec !== undefined || partial.coagRatio !== undefined) {
      if (summary) {
        fetchRecords(summary, updated.selectedMode, updated.windowEndSec);
      }
    }
  };

  return (
    <div className="app-container">
      {/* Main Content Area (Left side) */}
      <main className="main-content">
        {errorMsg && (
          <div
            style={{
              padding: "0.75rem 1rem",
              backgroundColor: "#fef2f2",
              border: "1px solid #fecaca",
              color: "#b91c1c",
              borderRadius: 6,
              fontSize: "0.875rem",
            }}
          >
            エラー: {errorMsg}
          </div>
        )}

        <Header
          summary={summary}
          sidebarOpen={sidebarOpen}
          onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
        />

        {/* Tab Navigation */}
        <div className="tabs-nav">
          <button
            className={`tab-btn ${activeTab === "overlay" ? "active" : ""}`}
            onClick={() => setActiveTab("overlay")}
          >
            📈 重ね描き
          </button>
          <button
            className={`tab-btn ${activeTab === "detail" ? "active" : ""}`}
            onClick={() => setActiveTab("detail")}
          >
            🔍 1波形の詳細
          </button>
          <button
            className={`tab-btn ${activeTab === "info" ? "active" : ""}`}
            onClick={() => setActiveTab("info")}
          >
            🗂 一覧・読み込み情報
          </button>
        </div>

        {/* Tab Content */}
        {summary && records.length > 0 ? (
          <>
            {activeTab === "overlay" && (
              <TabOverlay
                summary={summary}
                records={records}
                options={options}
                onChangeOptions={handleChangeOptions}
              />
            )}
            {activeTab === "detail" && (
              <TabDetail
                summary={summary}
                records={records}
                options={options}
                onChangeOptions={handleChangeOptions}
              />
            )}
            {activeTab === "info" && <TabInfo summary={summary} records={records} />}
          </>
        ) : (
          <div
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--text-muted)",
            }}
          >
            {loading ? "バッチを読み込み中…" : "右の設定パネルでバッチを選択してください"}
          </div>
        )}
      </main>

      {/* Sidebar (Right side, collapsible) */}
      <Sidebar
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        options={options}
        onChangeOptions={handleChangeOptions}
        folderEntries={folderEntries}
        onRefreshFolders={handleRefreshFolders}
        onSelectFolder={handleLoadBatch}
        onUploadFiles={handleUploadFiles}
        availableModes={summary?.modes || []}
        timePoints={
          options.selectedMode === "比色項目"
            ? (summary?.chromo_time_points && summary.chromo_time_points.length > 0
                ? summary.chromo_time_points
                : summary?.time_points)
            : summary?.time_points
        }
      />
    </div>
  );
};
