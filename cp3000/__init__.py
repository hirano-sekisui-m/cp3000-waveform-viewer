"""CP3000 raw data (prof*.dat, *CSV_data.csv, LOG*.dat) reader and waveform processing."""

from .batch import (
    MODE_CHROMOGENIC,
    MODE_COAGULATION,
    MODE_UNKNOWN,
    Batch,
    BatchFiles,
    classify_measurement_mode,
    find_batch_files,
    find_batch_folders,
    load_batch,
)
from .prof import ProfRecord, detect_profile_format, parse_prof_dat
from .signal import Derived, derive_batch, time_axis

__version__ = "0.1.0"

__all__ = [
    "MODE_COAGULATION", "MODE_CHROMOGENIC", "MODE_UNKNOWN", "classify_measurement_mode",
    "Batch", "BatchFiles", "find_batch_files", "find_batch_folders", "load_batch",
    "ProfRecord", "detect_profile_format", "parse_prof_dat",
    "Derived", "derive_batch", "time_axis",
]
