from pathlib import Path
import os
import sys
import glob
import threading

# Locate Tcl/Tk libraries belonging to the base Python installation.
# Some Windows Python 3.13 installations do not resolve these paths correctly
# when launched from a virtual environment.
_base = Path(sys.base_prefix)
_tcl_candidates = [ _base / "tcl" / "tcl8.6", _base / "lib" / "tcl8.6" ]
_tk_candidates = [ _base / "tcl" / "tk8.6", _base / "lib" / "tk8.6" ]
for _path in _tcl_candidates + [Path(p) for p in glob.glob(str(_base / "tcl" / "tcl8.6.*"))]:
    if (_path / "init.tcl").is_file():
        os.environ["TCL_LIBRARY"] = str(_path)
        break
for _path in _tk_candidates + [Path(p) for p in glob.glob(str(_base / "tcl" / "tk8.6.*"))]:
    if (_path / "tk.tcl").is_file():
        os.environ["TK_LIBRARY"] = str(_path)
        break

import tkinter as tk
from ui.main_window import main

if __name__ == "__main__":
    main()
