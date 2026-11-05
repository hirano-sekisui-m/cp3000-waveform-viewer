export interface FolderEntry {
  label: string;
  folder_path: string;
  csv_path?: string | null;
  has_prof: boolean;
  has_csv: boolean;
  has_log: boolean;
}

export interface FileInfo {
  kind: string;
  filename?: string | null;
  size?: number | null;
  folder?: string | null;
}

export interface BatchSummary {
  name: string;
  total_records: number;
  samples_count?: number | null;
  items_count: number;
  csv_matched: number;
  error_count: number;
  modes: string[];
  points_summary: string;
  step_summary: string;
  files: FileInfo[];
  warnings: string[];
  items_list: string[];
  groups_list: string[];
  columns: string[];
}

export interface RecordItem {
  No: number;
  _pos: number;
  _label?: string;
  依頼No?: string | null;
  SID?: string | null;
  検体名?: string | null;
  項目名?: string | null;
  内部依頼No?: string | null;
  項目番号?: number | null;
  測定値?: string | number | null;
  "Tc2(計算)"?: number | null;
  "Te2(計算)"?: number | null;
  属性?: string | null;
  測定種別?: string | null;
  測定モード?: string | null;
  "測定時間(秒)"?: number | null;
  エラーフラグ?: number | null;
  再測定?: boolean | null;
  [key: string]: any;
}

export interface WaveformSeries {
  position: number;
  no: number;
  label: string;
  item_name: string;
  mode: string;
  time: (number | null)[];
  raw: (number | null)[];
  scaled: (number | null)[];
  endpoint_scaled: (number | null)[];
  slope: (number | null)[];
  acceleration: (number | null)[];
  abs_slope?: (number | null)[] | null;
  tc2?: number | null;
  te2?: number | null;
  shift: number;
}

export interface DetailCalculated {
  Tc2?: number | null;
  Te2?: number | null;
  Tc1?: number | null;
  Te1?: number | null;
  device_val?: number | null;
  tc2_diff?: number | null;
  vmax?: number | null;
  t_vmax?: number | null;
}

export interface DetailWaveformResponse {
  position: number;
  no: number;
  label: string;
  item_name: string;
  mode: string;
  time: (number | null)[];
  raw: (number | null)[];
  scaled: (number | null)[];
  endpoint_scaled: (number | null)[];
  slope: (number | null)[];
  acceleration: (number | null)[];
  abs_slope?: (number | null)[] | null;
  calculated: DetailCalculated;
  record_info: Record<string, string | number>;
}
