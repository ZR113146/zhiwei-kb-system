import os, shutil
from datetime import datetime

def find_latest_docx(directory=None):
    import glob
    if directory is None:
        directory = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop")
    candidates = []
    for f in glob.glob(os.path.join(directory, "*.docx")):
        if ".bak" in f or os.path.basename(f).startswith("~$"):
            continue
        candidates.append((os.path.getmtime(f), f))
    candidates.sort(reverse=True)
    return candidates[0][1] if candidates else None

def backup_docx(docx_path, suffix="_bak"):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bp = docx_path.replace(".docx", f"_{suffix}_{ts}.docx")
    shutil.copy2(docx_path, bp)
    return bp
