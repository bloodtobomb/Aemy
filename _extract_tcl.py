import zipfile, os, sys

# Locate the Tcl/Tk runtime folders for this Python install.
# Python 3.14 keeps Tcl/Tk as libtcl*.zip / libtk*.zip inside the tcl folder,
# which we must unpack for PyInstaller.
tcl_dir = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "tcl")
out = r"C:\Users\fares_xa0ks9w\Videos\frames\_tclsrc"
os.makedirs(out, exist_ok=True)

for name in os.listdir(tcl_dir):
    if name.startswith("libtcl") and name.endswith(".zip"):
        zipfile.ZipFile(os.path.join(tcl_dir, name)).extractall(out)
        print("extracted", name)
    if name.startswith("libtk") and name.endswith(".zip"):
        zipfile.ZipFile(os.path.join(tcl_dir, name)).extractall(out)
        print("extracted", name)
print("DONE ->", out)
