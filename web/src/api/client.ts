import {
  BatchSummary,
  DetailWaveformResponse,
  FolderEntry,
  RecordItem,
  WaveformSeries,
} from "../types";

const BASE_URL = "/api";

export async function fetchHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

export async function getSettings(): Promise<Record<string, any>> {
  const res = await fetch(`${BASE_URL}/settings`);
  return res.json();
}

export async function updateSettings(data: Record<string, any>): Promise<Record<string, any>> {
  const res = await fetch(`${BASE_URL}/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return res.json();
}

export async function listFolders(rootPath?: string): Promise<FolderEntry[]> {
  const q = rootPath ? `?root_path=${encodeURIComponent(rootPath)}` : "";
  const res = await fetch(`${BASE_URL}/batches/folders${q}`);
  if (!res.ok) throw new Error("Failed to list folders");
  return res.json();
}

export async function loadBatch(params: {
  folder_path?: string;
  csv_path?: string;
  entry_id?: string;
  prof_file?: string;
  csv_file?: string;
  log_file?: string;
  profile_mode?: string;
  csv_encoding?: string;
}): Promise<BatchSummary> {

  const res = await fetch(`${BASE_URL}/batches/load`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || "Failed to load batch");
  }
  return res.json();
}

export async function uploadBatchFiles(
  files: File[],
  profile_mode = "auto",
  csv_encoding = "cp932"
): Promise<BatchSummary> {
  const formData = new FormData();
  for (const f of files) {
    formData.append("files", f);
  }
  const q = `?profile_mode=${profile_mode}&csv_encoding=${csv_encoding}`;
  const res = await fetch(`${BASE_URL}/batches/upload${q}`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || "Failed to upload files");
  }
  return res.json();
}

export async function getBatchSummary(): Promise<BatchSummary> {
  const res = await fetch(`${BASE_URL}/batches/summary`);
  if (!res.ok) throw new Error("No active batch");
  return res.json();
}

export async function queryRecords(params: {
  items?: string[];
  groups?: string[];
  search?: string;
  request_no?: string;
  meas_expr?: string;
  proc_expr?: string;
  error_only?: boolean;
  mode?: string;
  limit?: number;
  offset?: number;
  window_end_sec?: number | null;
  coag_ratio?: number;
}): Promise<{ total: number; filtered_total: number; records: RecordItem[] }> {
  const { window_end_sec, coag_ratio, ...body } = params;
  const q = new URLSearchParams();
  if (window_end_sec != null) q.set("window_end_sec", String(window_end_sec));
  if (coag_ratio != null) q.set("coag_ratio", String(coag_ratio));

  const res = await fetch(`${BASE_URL}/batches/records?${q.toString()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to query records");
  return res.json();
}

export async function deriveWaveforms(params: {
  positions: number[];
  window_end_sec?: number | null;
  coag_ratio?: number;
  align?: string;
  baseline?: boolean;
  thin?: boolean;
  ref_point_idx?: number;
}): Promise<{ series: WaveformSeries[]; skipped_count: number }> {

  const res = await fetch(`${BASE_URL}/waveforms/derive`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error("Failed to derive waveforms");
  return res.json();
}

export async function getWaveformDetail(
  no: number,
  params?: { window_end_sec?: number | null; coag_ratio?: number; ref_point_idx?: number }
): Promise<DetailWaveformResponse> {
  const q = new URLSearchParams();
  if (params?.window_end_sec != null) q.set("window_end_sec", String(params.window_end_sec));
  if (params?.coag_ratio != null) q.set("coag_ratio", String(params.coag_ratio));
  if (params?.ref_point_idx != null) q.set("ref_point_idx", String(params.ref_point_idx));

  const res = await fetch(`${BASE_URL}/waveforms/detail/${no}?${q.toString()}`);

  if (!res.ok) throw new Error(`Failed to get detail for waveform ${no}`);
  return res.json();
}

export async function downloadTableCsv(): Promise<void> {
  window.open(`${BASE_URL}/export/table-csv`, "_blank");
}

export async function downloadWaveformsCsv(params: {
  positions: number[];
  kind: string;
  window_end_sec?: number | null;
  coag_ratio?: number;
  ref_point_idx?: number;
}): Promise<void> {
  const res = await fetch(`${BASE_URL}/export/waveforms-csv`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error("Failed to download waveforms CSV");
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const cd = res.headers.get("content-disposition");
  let filename = "waveforms.csv";
  if (cd) {
    const match = cd.match(/filename="?([^";]+)"?/);
    if (match?.[1]) filename = decodeURIComponent(match[1]);
  }
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}
