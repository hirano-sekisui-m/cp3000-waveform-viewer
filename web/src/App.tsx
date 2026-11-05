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
  getBatchSummary,
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
  });

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
        const root = settings.root || "demo_data";
        setOptions((prev) => ({ ...prev, rootPath: root }));
        return listFolders(root).then((folders) => {
          setFolderEntries(folders);
          const target = settings.last_batch || (folders[0]?.folder_path ?? "");
          if (target) {
            setOptions((prev) => ({ ...prev, selectedBatchFolder: target }));
            handleLoadBatch(target);
          }
        });
      })
      .catch((err) => {
        console.error("Initialization error:", err);
      });
  }, []);

  const handleRefreshFolders = async () => {
    try {
      const folders = await listFolders(options.rootPath);
      setFolderEntries(folders);
      if (folders.length > 0 && !folders.some((f) => f.folder_path === options.selectedBatchFolder)) {
        handleLoadBatch(folders[0].folder_path);
      }
    } catch (err: any) {
      setErrorMsg(err.message);
    }
  };

  const handleLoadBatch = async (folderPath: string) => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const sum = await loadBatch({ folder_path: folderPath });
      setSummary(sum);
      setOptions((prev) => ({ ...prev, selectedBatchFolder: folderPath }));
      await fetchRecords(sum, options.selectedMode);
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
      await fetchRecords(sum, options.selectedMode);
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchRecords = async (currentSummary: BatchSummary, mode?: string) => {
    try {
      const res = await queryRecords({
        mode: mode || undefined,
        window_end_sec: options.windowEndSec ? parseFloat(options.windowEndSec) : null,
        coag_ratio: options.coagRatio,
      });
      setRecords(res.records);
    } catch (err: any) {
      console.error("Failed to query records:", err);
    }
  };

  const handleChangeOptions = (partial: Partial<SidebarOptions>) => {
    const updated = { ...options, ...partial };
    setOptions(updated);

    if (partial.rootPath !== undefined) {
      updateSettings({ root: partial.rootPath });
    }

    if (partial.selectedMode !== undefined && summary) {
      fetchRecords(summary, partial.selectedMode);
    }
  };

  return (
    <div className="app-container">
      <Sidebar
        options={options}
        onChangeOptions={handleChangeOptions}
        folderEntries={folderEntries}
        onRefreshFolders={handleRefreshFolders}
        onSelectFolder={handleLoadBatch}
        onUploadFiles={handleUploadFiles}
        availableModes={summary?.modes || []}
      />

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

        <Header summary={summary} />

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
              <TabOverlay summary={summary} records={records} options={options} />
            )}
            {activeTab === "detail" && (
              <TabDetail summary={summary} records={records} options={options} />
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
            {loading ? "バッチを読み込み中…" : "左のサイドバーでバッチを選択してください"}
          </div>
        )}
      </main>
    </div>
  );
};
