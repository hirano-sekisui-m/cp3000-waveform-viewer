import React, { useState } from "react";
import { Folder, Upload, Settings2, Sliders, RefreshCw } from "lucide-react";
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
  options: SidebarOptions;
  onChangeOptions: (opts: Partial<SidebarOptions>) => void;
  folderEntries: FolderEntry[];
  onRefreshFolders: () => void;
  onSelectFolder: (folder: string) => void;
  onUploadFiles: (files: File[]) => void;
  availableModes: string[];
}

export const WAVE_TYPE_LABELS: Record<string, string> = {
  raw: "生波形",
  scaled: "凝固波形 (最大=100%)",
  endpoint_scaled: "凝固波形 (終点=100%)",
  slope: "速度 (1次微分)",
  acceleration: "加速度 (2次微分)",
  abs_slope: "吸光度変化率 (mAbs/min.)",
};

export const Sidebar: React.FC<Props> = ({
  options,
  onChangeOptions,
  folderEntries,
  onRefreshFolders,
  onSelectFolder,
  onUploadFiles,
  availableModes,
}) => {
  const [showCalcSettings, setShowCalcSettings] = useState(false);

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
    <aside className="sidebar">
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
                  <option key={f.folder_path} value={f.folder_path}>
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
            onChange={(e) => onChangeOptions({ selectedMode: e.target.value })}
          >
            <option value="">すべて</option>
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
          {Object.entries(WAVE_TYPE_LABELS).map(([k, label]) => {
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

        <div>
          <span className="sidebar-label">時間軸のそろえ方</span>
          <select
            className="select-box"
            value={options.align}
            onChange={(e) => onChangeOptions({ align: e.target.value })}
          >
            <option value="off">そろえない (測定時間)</option>
            <option value="tc2">Tc2 を 0 秒に</option>
            <option value="peak">速度ピークを 0 秒に</option>
            <option value="rise">立ち上がり (10%) を 0 秒に</option>
          </select>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <div style={{ flex: 1 }}>
            <span className="sidebar-label">開始 (秒)</span>
            <input
              type="number"
              className="input-text"
              placeholder="自動"
              value={options.xStart}
              onChange={(e) => onChangeOptions({ xStart: e.target.value })}
            />
          </div>
          <div style={{ flex: 1 }}>
            <span className="sidebar-label">終了 (秒)</span>
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
          <label style={{ fontSize: "0.8125rem", display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={options.showTc2}
              onChange={(e) => onChangeOptions({ showTc2: e.target.checked })}
            />
            <span>Tc2 の位置に印を付ける</span>
          </label>
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

      {/* Calc settings */}
      <div className="sidebar-section" style={{ borderBottom: "none" }}>
        <button
          className="btn btn-outline btn-sm"
          style={{ width: "100%", justifyContent: "space-between" }}
          onClick={() => setShowCalcSettings(!showCalcSettings)}
        >
          <span>計算の設定</span>
          <span>{showCalcSettings ? "▲" : "▼"}</span>
        </button>

        {showCalcSettings && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
            <div>
              <span className="sidebar-label">解析窓 (秒、空欄=全長)</span>
              <input
                type="number"
                className="input-text"
                placeholder="全長"
                value={options.windowEndSec}
                onChange={(e) => onChangeOptions({ windowEndSec: e.target.value })}
              />
            </div>
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
    </aside>
  );
};
