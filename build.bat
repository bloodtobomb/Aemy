@echo off
REM Python 3.14 ships Tcl/Tk inside zip archives (loaded via a virtual zipfs),
REM which PyInstaller cannot bundle automatically. extract_tcl.py unpacks them
REM into _tclsrc; we then bundle those under the names the Tcl runtime expects.
python extract_tcl.py

REM Build the .exe icon from a sprite frame (multi-resolution).
python make_icon.py

REM version_info.txt supplies the Windows file properties shown in
REM Explorer's Details tab (Product, File version, Company, Copyright).
if exist aicon.png (
    pyinstaller --onefile --windowed --name Aemy --icon app.ico --version-file version_info.txt --manifest app.manifest --add-data "frames;frames" --add-data "_tclsrc\tcl_library;_tcl_data" --add-data "_tclsrc\tk_library;_tk_data" --add-data "aicon.png;." sprite_tray_app.py
) else (
    pyinstaller --onefile --windowed --name Aemy --icon app.ico --version-file version_info.txt --manifest app.manifest --add-data "frames;frames" --add-data "_tclsrc\tcl_library;_tcl_data" --add-data "_tclsrc\tk_library;_tk_data" sprite_tray_app.py
)
