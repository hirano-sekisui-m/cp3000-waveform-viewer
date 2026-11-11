import React, { useMemo } from "react";
import { Filter, X, Check, RotateCcw } from "lucide-react";
import { RecordFilterState } from "../utils/filter";

interface Props {
  isChromogenic: boolean;
  availableItems: string[];
  filter: RecordFilterState;
  onChangeFilter: (next: RecordFilterState) => void;
  totalCount: number;
  filteredCount: number;
}

export const RecordFilterBar: React.FC<Props> = ({
  isChromogenic,
  availableItems,
  filter,
  onChangeFilter,
  totalCount,
  filteredCount,
}) => {
  const isFiltered = useMemo(() => {
    return (
      filter.selectedItems.length > 0 ||
      filter.requestNo.trim() !== "" ||
      filter.procExpr.trim() !== "" ||
      filter.measExpr.trim() !== ""
    );
  }, [filter]);

  const handleToggleItem = (item: string) => {
    const current = filter.selectedItems;
    if (current.includes(item)) {
      onChangeFilter({ ...filter, selectedItems: current.filter((x) => x !== item) });
    } else {
      onChangeFilter({ ...filter, selectedItems: [...current, item] });
    }
  };

  const handleSelectAllItems = () => {
    onChangeFilter({ ...filter, selectedItems: [...availableItems] });
  };

  const handleClearItems = () => {
    onChangeFilter({ ...filter, selectedItems: [] });
  };

  const handleResetAll = () => {
    onChangeFilter({
      selectedItems: [],
      requestNo: "",
      procExpr: "",
      measExpr: "",
    });
  };

  return (
    <div
      style={{
        backgroundColor: "#f8fafc",
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "8px 10px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        fontSize: "0.8125rem",
      }}
    >
      {/* Title & Count row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 600, color: "var(--text-main)" }}>
          <Filter size={14} style={{ color: isFiltered ? "#2563eb" : "var(--text-muted)" }} />
          <span>絞り込み</span>
          <span
            style={{
              fontSize: "0.75rem",
              padding: "1px 6px",
              borderRadius: 10,
              backgroundColor: isFiltered ? "#dbeafe" : "#e2e8f0",
              color: isFiltered ? "#1e40af" : "var(--text-muted)",
              fontWeight: 600,
            }}
          >
            {filteredCount} / {totalCount} 件
          </span>
        </div>

        {isFiltered && (
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={handleResetAll}
            style={{ padding: "2px 8px", fontSize: "0.75rem", display: "flex", alignItems: "center", gap: 4 }}
            title="絞り込み条件をすべてクリア"
          >
            <RotateCcw size={11} />
            <span>クリア</span>
          </button>
        )}
      </div>

      {/* Item Selector (Pills) */}
      {availableItems.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "0.75rem" }}>
            <span style={{ color: "var(--text-muted)", fontWeight: 500 }}>項目名 (複数選択可):</span>
            <div style={{ display: "flex", gap: 6 }}>
              <button
                type="button"
                onClick={handleSelectAllItems}
                style={{
                  background: "none",
                  border: "none",
                  color: "#2563eb",
                  cursor: "pointer",
                  fontSize: "0.7rem",
                  padding: 0,
                  textDecoration: "underline",
                }}
              >
                全選択
              </button>
              <span style={{ color: "var(--border)" }}>|</span>
              <button
                type="button"
                onClick={handleClearItems}
                style={{
                  background: "none",
                  border: "none",
                  color: "var(--text-muted)",
                  cursor: "pointer",
                  fontSize: "0.7rem",
                  padding: 0,
                  textDecoration: "underline",
                }}
              >
                解除
              </button>
            </div>
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {availableItems.map((item) => {
              const active = filter.selectedItems.includes(item);
              return (
                <button
                  key={item}
                  type="button"
                  onClick={() => handleToggleItem(item)}
                  style={{
                    padding: "2px 8px",
                    borderRadius: 12,
                    fontSize: "0.75rem",
                    border: active ? "1px solid #2563eb" : "1px solid var(--border)",
                    backgroundColor: active ? "#eff6ff" : "#fff",
                    color: active ? "#1d4ed8" : "var(--text-main)",
                    fontWeight: active ? 600 : 400,
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: 3,
                    transition: "all 0.15s ease",
                  }}
                >
                  {active && <Check size={11} />}
                  <span>{item}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Request No & Numeric inputs */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {/* Request No */}
        <div style={{ flex: "1 1 120px" }}>
          <label style={{ display: "block", fontSize: "0.72rem", color: "var(--text-muted)", marginBottom: 2 }}>
            依頼No
          </label>
          <input
            type="text"
            className="input-text"
            style={{ width: "100%", padding: "3px 6px", fontSize: "0.75rem" }}
            placeholder="例: 0001, C001"
            value={filter.requestNo}
            onChange={(e) => onChangeFilter({ ...filter, requestNo: e.target.value })}
          />
        </div>

        {/* Processed Value / Tc2 */}
        <div style={{ flex: "1 1 110px" }}>
          <label style={{ display: "block", fontSize: "0.72rem", color: "var(--text-muted)", marginBottom: 2 }}>
            {isChromogenic ? "処理値" : "処理値 / Tc2"}
          </label>
          <input
            type="text"
            className="input-text"
            style={{ width: "100%", padding: "3px 6px", fontSize: "0.75rem" }}
            placeholder="例: > 10, < 50"
            value={filter.procExpr}
            onChange={(e) => onChangeFilter({ ...filter, procExpr: e.target.value })}
          />
        </div>

        {/* Measured Value */}
        <div style={{ flex: "1 1 110px" }}>
          <label style={{ display: "block", fontSize: "0.72rem", color: "var(--text-muted)", marginBottom: 2 }}>
            測定値
          </label>
          <input
            type="text"
            className="input-text"
            style={{ width: "100%", padding: "3px 6px", fontSize: "0.75rem" }}
            placeholder="例: > 10, 10-50"
            value={filter.measExpr}
            onChange={(e) => onChangeFilter({ ...filter, measExpr: e.target.value })}
          />
        </div>
      </div>

      <div style={{ fontSize: "0.68rem", color: "var(--text-muted)", lineHeight: 1.2 }}>
        ※数値絞り込み例: <code>&gt; 50</code>, <code>&lt;= 20</code>, <code>10-50</code> (範囲)
      </div>
    </div>
  );
};
