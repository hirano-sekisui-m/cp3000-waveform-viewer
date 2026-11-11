import { RecordItem } from "../types";

export interface RecordFilterState {
  selectedItems: string[];
  requestNo: string;
  procExpr: string;
  measExpr: string;
}

export const INITIAL_RECORD_FILTER: RecordFilterState = {
  selectedItems: [],
  requestNo: "",
  procExpr: "",
  measExpr: "",
};

/**
 * Evaluate numeric condition on a value.
 * Supports:
 *   "> 50", ">= 50", "< 10", "<= 10", "= 5", "5", "!= 0", "10-50", "10..50", "10～50"
 */
export function matchesNumericFilter(val: any, expr: string): boolean {
  if (!expr || expr.trim() === "") return true;
  if (val === null || val === undefined || val === "" || isNaN(Number(val))) return false;
  const num = Number(val);
  const trimmed = expr.trim();

  // Range: "10-50", "10..50", "10～50", "10~50"
  const rangeMatch = trimmed.match(/^(-?\d+(?:\.\d+)?)\s*(?:-|\.\.|～|~)\s*(-?\d+(?:\.\d+)?)$/);
  if (rangeMatch) {
    const min = parseFloat(rangeMatch[1]);
    const max = parseFloat(rangeMatch[2]);
    return num >= Math.min(min, max) && num <= Math.max(min, max);
  }

  // Operator + number: ">= 50", "< 10", "= 5", etc.
  const opMatch = trimmed.match(/^(>=|<=|>|<|==|=|!=)?\s*(-?\d+(?:\.\d+)?)$/);
  if (opMatch) {
    const op = opMatch[1] || "=";
    const target = parseFloat(opMatch[2]);
    switch (op) {
      case ">": return num > target;
      case ">=": return num >= target;
      case "<": return num < target;
      case "<=": return num <= target;
      case "=":
      case "==": return Math.abs(num - target) < 1e-5;
      case "!=": return Math.abs(num - target) >= 1e-5;
    }
  }

  return true;
}

/**
 * Check if a record matches requestNo query (comma, space separated, substring match).
 */
export function matchesRequestNoFilter(record: RecordItem, filterText: string): boolean {
  if (!filterText || filterText.trim() === "") return true;
  const targetReq = String(record.依頼No || record.内部依頼No || "");
  const queries = filterText
    .split(/[,、\s]+/)
    .map((q) => q.trim())
    .filter((q) => q.length > 0);
  if (queries.length === 0) return true;
  return queries.some((q) => targetReq.toLowerCase().includes(q.toLowerCase()));
}

/**
 * Filter an array of records by filter conditions.
 */
export function filterRecords(records: RecordItem[], filter: RecordFilterState): RecordItem[] {
  const hasItems = filter.selectedItems && filter.selectedItems.length > 0;
  const hasReq = Boolean(filter.requestNo && filter.requestNo.trim());
  const hasProc = Boolean(filter.procExpr && filter.procExpr.trim());
  const hasMeas = Boolean(filter.measExpr && filter.measExpr.trim());

  if (!hasItems && !hasReq && !hasProc && !hasMeas) {
    return records;
  }

  return records.filter((r) => {
    // 1. Item Name
    if (hasItems) {
      const item = r.項目名 || "";
      if (!filter.selectedItems.includes(item)) {
        return false;
      }
    }

    // 2. Request No
    if (hasReq) {
      if (!matchesRequestNoFilter(r, filter.requestNo)) {
        return false;
      }
    }

    // 3. Processed / Tc2 value
    if (hasProc) {
      const procVal = r.処理値 != null ? r.処理値 : r["Tc2(計算)"];
      if (!matchesNumericFilter(procVal, filter.procExpr)) {
        return false;
      }
    }

    // 4. Measured value
    if (hasMeas) {
      if (!matchesNumericFilter(r.測定値, filter.measExpr)) {
        return false;
      }
    }

    return true;
  });
}
