"""Use Windows ICU rather than an unrelated Conda ICU DLL in frozen Qt apps."""
import ctypes
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    # Qt uses the Windows ICU API. A different ICU from Conda may have been
    # collected under the same DLL name but expose incompatible entry points.
    _windows_icu = ctypes.WinDLL(str(Path(os.environ["SystemRoot"]) / "System32" / "icuuc.dll"))
