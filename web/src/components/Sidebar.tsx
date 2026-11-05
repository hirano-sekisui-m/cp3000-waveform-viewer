import React, { useState } from "react";
import { Folder, Upload, Settings2, Sliders, RefreshCw, X } from "lucide-react";
import { FolderEntry } from "../types";

export interface SidebarOptions {
  sourceType: "folder" | "upload";
  rootPath: string;
  selectedBatchFolder: string;
  selectedMode: string;
  waveTypes: string[];
  align: string;
  xStart: string;
  xEnd: string;
  baseline: boolean;
  showTc2: boolean;
  thin: boolean;
  windowEndSec: string;
  coagRatio: number;
}

interface Props {
  isOpen: boolean;
  onClose: () => void;
  options: SidebarOptions;
  onChangeOptions: (opts: Partial<SidebarOptions>) => void;
  folderEntries: FolderEntry[];
  onRefreshFolders: () => void;
  onSelectFolder: (folder: string) => void;
  onUploadFiles: (files: File[]) => void;
  availableModes: string[];
}

export const COAG_WAVE_TYPES: Record<string, string> = {
  raw: "生波形",
  scaled: "凝固波形 (最大=100%)",
  endpoint_scaled: "凝固波形 (終点=100%)",
  slope: "速度 (1次微分)",
  acceleration: "加速度 (2次微分)",
};

export const CHROMO_WAVE_TYPES: Record<string, string> = {
  raw: "生波形 (0.1 mAbs)",
  scaled: "吸光度変化 (0–100%)",
  abs_slope: "吸光度変化率 (mAbs/min.)",
};

export const Sidebar: React.FC<Props> = ({
  isOpen,
  onClose,
  options,
  onChangeOptions,
  folderEntries,
  onRefreshFolders,
  onSelectFolder,
  onUploadFiles,
  availableModes,
}) => {
  const [showCalcSettings, setShowCalcSettings] = useState(false);
  const isChromogenic = options.selectedMode === "比色項目";

  const waveTypeDict = isChromogenic ? CHROMO_WAVE_TYPES : COAG_WAVE_TYPES;

  const handleToggleWaveType = (type: string) => {
    const current = options.waveTypes;
    if (current.includes(type)) {
      if (current.length > 1) {
        onChangeOptions({ waveTypes: current.filter((t) => t !== type) });
      }
    } else {
      onChangeOptions({ waveTypes: [...current, type] });
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      onUploadFiles(Array.from(e.target.files));
    }
  };

  return (
    <aside className={`sidebar ${isOpen ? "" : "closed"}`}>
      {/* Header of sidebar */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontWeight: 700, fontSize: "0.9375rem" }}>設定パネル</span>
        <button className="btn btn-outline btn-sm" onClick={onClose} title="閉じる">
          <X size={14} />
        </button>
      </div>

      {/* Source selector */}
      <div className="sidebar-section">
        <div className="sidebar-title">
          <Folder size={18} />
          <span>データソース</span>
        </div>
        <div className="toggle-group">
          <button
            className={`toggle-item ${options.sourceType === "folder" ? "active" : ""}`}
            onClick={() => onChangeOptions({ sourceType: "folder" })}
          >
            フォルダから選ぶ
          </button>
          <button
            className={`toggle-item ${options.sourceType === "upload" ? "active" : ""}`}
            onClick={() => onChangeOptions({ sourceType: "upload" })}
          >
            アップロード
          </button>
        </div>

        {options.sourceType === "folder" ? (
          <>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <span className="sidebar-label">親フォルダ</span>
                <button
                  className="btn btn-outline btn-sm"
                  onClick={onRefreshFolders}
                  title="フォルダ一覧を更新"
                >
                  <RefreshCw size={12} />
                </button>
              </div>
              <input
                type="text"
                className="input-text"
                value={options.rootPath}
                onChange={(e) => onChangeOptions({ rootPath: e.target.value })}
                placeholder="例: demo_data"
              />
            </div>

            <div>
              <span className="sidebar-label">バッチを選択 ({folderEntries.length} 件)</span>
              <select
                className="select-box"
                value={options.selectedBatchFolder}
                onChange={(e) => onSelectFolder(e.target.value)}
              >
                {folderEntries.map((f) => (
                  <option key={f.entry_id} value={f.entry_id}>
                    {f.label}
                  </option>
                ))}
              </select>

            </div>
          </>
        ) : (
          <div>
            <span className="sidebar-label">ファイルを指定 (.dat, .csv)</span>
            <input
              type="file"
              multiple
              className="input-text"
              onChange={handleFileChange}
              accept=".dat,.csv"
            />
          </div>
        )}
      </div>

      {/* Measurement Mode */}
      {availableModes.length > 0 && (
        <div className="sidebar-section">
          <span className="sidebar-label">測定モード</span>
          <select
            className="select-box"
            value={options.selectedMode}
            onChange={(e) => {
              const newMode = e.target.value;
              const newWaveTypes =
                newMode === "比色項目"
                  ? ["raw", "scaled", "abs_slope"]
                  : ["raw", "scaled", "slope"];
              onChangeOptions({
                selectedMode: newMode,
                waveTypes: newWaveTypes,
                align: newMode === "比色項目" ? "off" : options.align,
              });
            }}
          >
            {availableModes.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Waveform types */}
      <div className="sidebar-section">
        <div className="sidebar-title">
          <Sliders size={18} />
          <span>表示する波形</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {Object.entries(waveTypeDict).map(([k, label]) => {
            const checked = options.waveTypes.includes(k);
            return (
              <label key={k} style={{ fontSize: "0.8125rem", display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => handleToggleWaveType(k)}
                />
                <span>{label}</span>
              </label>
            );
          })}
        </div>
      </div>

      {/* Display Options */}
      <div className="sidebar-section">
        <div className="sidebar-title">
          <Settings2 size={18} />
          <span>時間軸と配置</span>
        </div>

        {!isChromogenic && (
          <div>
            <span className="sidebar-label">時間軸のそろえ方</span>
            <select
              className="select-box"
              value={options.align}
              onChange={(e) => onChangeOptions({ align: e.target.value })}
            >
              <option value="off">測定時間 (そのまま)</option>
              <option value="tc2">凝固時間 (Tc2) を 0 秒に</option>
              <option value="peak">速度ピークを 0 秒に</option>
              <option value="rise">立ち上がり (10%) を 0 秒に</option>
            </select>
          </div>
        )}

        <div style={{ display: "flex", gap: 8 }}>
          <div style={{ flex: 1 }}>
            <span className="sidebar-label">表示開始 (秒)</span>
            <input
              type="number"
              className="input-text"
              placeholder="自動"
              value={options.xStart}
              onChange={(e) => onChangeOptions({ xStart: e.target.value })}
            />
          </div>
          <div style={{ flex: 1 }}>
            <span className="sidebar-label">表示終了 (秒)</span>
            <input
              type="number"
              className="input-text"
              placeholder="自動"
              value={options.xEnd}
              onChange={(e) => onChangeOptions({ xEnd: e.target.value })}
            />
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
          <label style={{ fontSize: "0.8125rem", display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={options.baseline}
              onChange={(e) => onChangeOptions({ baseline: e.target.checked })}
            />
            <span>生波形の開始値を 0 にそろえる</span>
          </label>

          {!isChromogenic && (
            <label style={{ fontSize: "0.8125rem", display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={options.showTc2}
                onChange={(e) => onChangeOptions({ showTc2: e.target.checked })}
              />
              <span>Tc2 の位置に印を付ける</span>
            </label>
          )}

          <label style={{ fontSize: "0.8125rem", display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={options.thin}
              onChange={(e) => onChangeOptions({ thin: e.target.checked })}
            />
            <span>重ね描きは間引いて軽くする</span>
          </label>
        </div>
      </div>

      {/* Calc settings (Coagulation only) */}
      {!isChromogenic && (
        <div className="sidebar-section" style={{ borderBottom: "none" }}>
          <button
            className="btn btn-outline btn-sm"
            style={{ width: "100%", justifyContent: "space-between" }}
            onClick={() => setShowCalcSettings(!showCalcSettings)}
          >
            <span>計算の詳細設定</span>
            <span>{showCalcSettings ? "▲" : "▼"}</span>
          </button>

          {showCalcSettings && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
              <div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span className="sidebar-label">Tc の判定割合</span>
                  <span style={{ fontSize: "0.75rem", fontWeight: 600 }}>{options.coagRatio}</span>
                </div>
                <input
                  type="range"
                  min="0.1"
                  max="0.9"
                  step="0.05"
                  style={{ width: "100%" }}
                  value={options.coagRatio}
                  onChange={(e) => onChangeOptions({ coagRatio: parseFloat(e.target.value) })}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </aside>
  );
};
