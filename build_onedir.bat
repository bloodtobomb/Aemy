@echo off
python extract_tcl.py
python make_icon.py
pyinstaller --onedir --windowed --name Aemy --icon app.ico --version-file version_info.txt --manifest app.manifest --add-data "frames;frames" --add-data "_tclsrc\tcl_library;_tcl_data" --add-data "_tclsrc\tk_library;_tk_data" sprite_tray_app.py
