"""Unpack the Tcl/Tk zip archives that PyInstaller cannot bundle on its own.

Python 3.13+ ships Tcl/Tk as libtcl*.zip / libtk*.zip inside the install's tcl
folder, loaded through a virtual zipfs. The frozen app expects real folders
called _tcl_data and _tk_data, so unpack them into _tclsrc/.
"""
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
tcl_dir = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "tcl")
out = os.path.join(HERE, "_tclsrc")
os.makedirs(out, exist_ok=True)

if not os.path.isdir(tcl_dir):
    sys.exit("Could not find the tcl folder at %s" % tcl_dir)

found = False
for name in sorted(os.listdir(tcl_dir)):
    if name.endswith(".zip") and (name.startswith("libtcl") or name.startswith("libtk")):
        zipfile.ZipFile(os.path.join(tcl_dir, name)).extractall(out)
        print("extracted", name)
        found = True

if not found:
    # Older Pythons keep Tcl/Tk as plain folders; nothing to do.
    print("No Tcl/Tk zips found - using the plain tcl folder (nothing to unpack).")
