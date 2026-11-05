import React, { useState, useEffect } from "react";

interface Props {
  isChromogenic: boolean;
  value: string; // "" means "full"
  onChange: (val: string) => void;
  refPointIdx?: number;
  onChangeRefPoint?: (idx: number) => void;
  timePoints?: number[];
}

export const WindowSelector: React.FC<Props> = ({
  isChromogenic,
  value,
  onChange,
  refPointIdx = 0,
  onChangeRefPoint,
  timePoints,
}) => {
  if (isChromogenic) {
    const points =
      timePoints && timePoints.length > 0
        ? timePoints
        : Array.from({ length: 60 }, (_, i) => i * 2.0);

    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.8125rem" }}>
        <span style={{ fontWeight: 600, color: "var(--text-main)" }}>⏱️ 0 点の基準ポイント:</span>
        <select
          className="select-box"
          style={{ width: "auto", padding: "0.2rem 0.6rem", fontSize: "0.8125rem", fontWeight: 500 }}
          value={refPointIdx}
          onChange={(e) => onChangeRefPoint?.(parseInt(e.target.value))}
        >
          {points.map((sec, i) => (
            <option key={i} value={i}>
              第 {i + 1} ポイント ({sec.toFixed(1)} 秒時点)
            </option>
          ))}
        </select>
      </div>
    );
  }

  // Determine current active button
  const currentPreset =
    value === "" ? "full" : value === "50" ? "50" : value === "100" ? "100" : "custom";

  const [customVal, setCustomVal] = useState(currentPreset === "custom" ? value : "");

  useEffect(() => {
    if (value !== "" && value !== "50" && value !== "100") {
      setCustomVal(value);
    }
  }, [value]);

  const handleSelectPreset = (preset: "full" | "50" | "100" | "custom") => {
    if (preset === "full") {
      onChange("");
    } else if (preset === "50") {
      onChange("50");
    } else if (preset === "100") {
      onChange("100");
    } else {
      // custom
      onChange(customVal || "60");
    }
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: "0.8125rem" }}>
      <span style={{ fontWeight: 600, color: "var(--text-muted)" }}>解析窓:</span>
      <div className="pill-group">
        <button
          className={`pill-btn ${currentPreset === "full" ? "active" : ""}`}
          onClick={() => handleSelectPreset("full")}
        >
          全長
        </button>
        <button
          className={`pill-btn ${currentPreset === "50" ? "active" : ""}`}
          onClick={() => handleSelectPreset("50")}
        >
          50 秒
        </button>
        <button
          className={`pill-btn ${currentPreset === "100" ? "active" : ""}`}
          onClick={() => handleSelectPreset("100")}
        >
          100 秒
        </button>
        <button
          className={`pill-btn ${currentPreset === "custom" ? "active" : ""}`}
          onClick={() => handleSelectPreset("custom")}
        >
          カスタム
        </button>
      </div>

      {currentPreset === "custom" && (
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <input
            type="number"
            min="10"
            step="10"
            className="input-text"
            style={{ width: 70, padding: "0.2rem 0.4rem", fontSize: "0.8125rem" }}
            value={customVal}
            placeholder="秒"
            onChange={(e) => {
              setCustomVal(e.target.value);
              onChange(e.target.value);
            }}
          />
          <span style={{ color: "var(--text-muted)" }}>秒</span>
        </div>
      )}
    </div>
  );
};
