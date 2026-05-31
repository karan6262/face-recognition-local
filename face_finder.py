#!/usr/bin/env python3
"""
Local Face Finder - v3
Beautiful UI, face thumbnails in sidebar, merge clusters, scan progress
"""
import os
import json
import shutil
import sqlite3
import threading
from pathlib import Path
from tkinter import simpledialog
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk

# ─── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
DATA_DIR  = BASE_DIR / "data"
DB_PATH   = DATA_DIR / "faces.db"
CROP_DIR  = DATA_DIR / "face_crops"
THUMB_DIR = DATA_DIR / "thumbnails"
for _d in [DATA_DIR, CROP_DIR, THUMB_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

SUPPORTED = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}

# ─── Colour Palette (Warm Natural Light Theme) ───────────────────────────────
BG        = "#faf7f2"   # warm off-white background
BG2       = "#f0ebe3"   # slightly darker panel background
CARD      = "#fffdf9"   # clean white card
ACCENT    = "#7c6f5b"   # warm brown accent (titles, headers)
ACCENT2   = "#a0845c"   # golden brown accent
GREEN     = "#5a8a5a"   # muted forest green (labeled)
RED       = "#b85c5c"   # muted terracotta (unnamed)
YELLOW    = "#a07840"   # warm amber (faces counter)
TEXT      = "#3a3228"   # dark warm brown (main text)
MUTED     = "#9c8e80"   # warm grey (muted text)
BORDER    = "#ddd5c8"   # soft sand border
BTN_BG    = "#e8e0d4"   # light warm sand button
BTN_HOV   = "#d9cfc2"   # slightly darker on hover



# ─── Database ─────────────────────────────────────────────────────────────────
class DB:
    def __init__(self):
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE, scanned INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS faces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id INTEGER, crop_path TEXT, embedding TEXT,
                cluster_id INTEGER DEFAULT -1,
                person_name TEXT DEFAULT '', face_index INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS clusters (
                id INTEGER PRIMARY KEY, person_name TEXT DEFAULT ''
            );
        """)
        self.conn.commit()

    def add_image(self, path):
        try:
            self.conn.execute("INSERT OR IGNORE INTO images (path) VALUES (?)", (str(path),))
            self.conn.commit()
            return self.conn.execute("SELECT id FROM images WHERE path=?", (str(path),)).fetchone()[0]
        except:
            return None

    def add_face(self, image_id, crop_path, embedding, face_index):
        self.conn.execute(
            "INSERT INTO faces (image_id, crop_path, embedding, face_index) VALUES (?,?,?,?)",
            (image_id, str(crop_path), json.dumps(embedding), face_index))
        self.conn.commit()

    def get_all_faces(self):
        return self.conn.execute(
            "SELECT f.*, i.path as image_path FROM faces f JOIN images i ON f.image_id=i.id"
        ).fetchall()

    def update_face_cluster(self, face_id, cluster_id):
        self.conn.execute("UPDATE faces SET cluster_id=? WHERE id=?", (cluster_id, face_id))
        self.conn.commit()

    def update_cluster_name(self, cluster_id, name):
        self.conn.execute("INSERT OR REPLACE INTO clusters (id,person_name) VALUES (?,?)", (cluster_id, name))
        self.conn.execute("UPDATE faces SET person_name=? WHERE cluster_id=?", (name, cluster_id))
        self.conn.commit()

    def merge_clusters(self, keep_id, merge_id):
        row = self.conn.execute("SELECT person_name FROM clusters WHERE id=?", (keep_id,)).fetchone()
        name = row["person_name"] if row else ""
        self.conn.execute("UPDATE faces SET cluster_id=?,person_name=? WHERE cluster_id=?", (keep_id, name, merge_id))
        self.conn.execute("DELETE FROM clusters WHERE id=?", (merge_id,))
        self.conn.commit()

    def get_clusters(self):
        return self.conn.execute("""
            SELECT f.cluster_id, COALESCE(c.person_name,'') as person_name,
                   COUNT(DISTINCT f.id) as face_count,
                   COUNT(DISTINCT f.image_id) as photo_count
            FROM faces f LEFT JOIN clusters c ON f.cluster_id=c.id
            WHERE f.cluster_id >= 0
            GROUP BY f.cluster_id ORDER BY face_count DESC
        """).fetchall()

    def get_first_crop(self, cluster_id):
        row = self.conn.execute(
            "SELECT crop_path FROM faces WHERE cluster_id=? AND crop_path!='' LIMIT 1", (cluster_id,)
        ).fetchone()
        return row["crop_path"] if row else None

    def get_images_for_cluster(self, cluster_id):
        return self.conn.execute("""
            SELECT DISTINCT i.path FROM faces f
            JOIN images i ON f.image_id=i.id WHERE f.cluster_id=?
        """, (cluster_id,)).fetchall()

    def get_stats(self):
        i = self.conn.execute("SELECT COUNT(*) FROM images WHERE scanned=1").fetchone()[0]
        f = self.conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0]
        p = self.conn.execute("SELECT COUNT(DISTINCT person_name) FROM faces WHERE person_name!=''").fetchone()[0]
        c = self.conn.execute("SELECT COUNT(DISTINCT cluster_id) FROM faces WHERE cluster_id>=0").fetchone()[0]
        return i, f, p, c

    def mark_scanned(self, image_id):
        self.conn.execute("UPDATE images SET scanned=1 WHERE id=?", (image_id,))
        self.conn.commit()

    def reset_scanned(self):
        self.conn.execute("UPDATE images SET scanned=0")
        self.conn.execute("DELETE FROM faces")
        self.conn.execute("DELETE FROM clusters")
        self.conn.commit()

    def clear_all(self):
        self.conn.executescript("DELETE FROM faces; DELETE FROM images; DELETE FROM clusters;")
        self.conn.commit()



# ─── Face Engine ──────────────────────────────────────────────────────────────
class FaceEngine:
    def __init__(self, log_fn=None):
        self.log = log_fn or print
        self._load()

    def _load(self):
        try:
            from deepface import DeepFace
            import numpy as np, cv2
            self.DeepFace = DeepFace
            self.np = np
            self.cv2 = cv2
            self.log("DeepFace loaded OK")
        except ImportError as e:
            self.log("ERROR: " + str(e))
            raise

    # Backends tried in order — ssd and retinaface catch most real-world photos
    BACKENDS = ["retinaface", "ssd", "opencv", "mtcnn"]

    def _preprocess(self, image_path):
        """
        Load and preprocess image:
        - Convert to RGB (handles PNG with alpha, EXIF rotation, etc.)
        - Resize very large images to max 2000px for speed
        Returns numpy array or None on failure.
        """
        import numpy as np
        try:
            pil_img = Image.open(image_path).convert("RGB")
            # Apply EXIF rotation so portrait photos are upright
            try:
                from PIL import ExifTags
                exif = pil_img._getexif()
                if exif:
                    for tag, val in exif.items():
                        if ExifTags.TAGS.get(tag) == "Orientation":
                            if val == 3:
                                pil_img = pil_img.rotate(180, expand=True)
                            elif val == 6:
                                pil_img = pil_img.rotate(270, expand=True)
                            elif val == 8:
                                pil_img = pil_img.rotate(90, expand=True)
                            break
            except:
                pass
            # Downscale very large images
            w, h = pil_img.size
            if max(w, h) > 2000:
                scale = 2000 / max(w, h)
                pil_img = pil_img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
            return np.array(pil_img)
        except:
            return None

    def detect_and_encode(self, image_path):
        """
        Detect all faces in an image and return (embedding, crop, index) tuples.
        Tries multiple detector backends so more faces are found.
        Uses enforce_detection=False so it always returns something if a face-like
        region exists — reduces missed detections on real-world photos.
        """
        results = []
        img_array = self._preprocess(image_path)
        if img_array is None:
            self.log("SKIP (unreadable): " + Path(image_path).name)
            return results

        for backend in self.BACKENDS:
            try:
                faces = self.DeepFace.represent(
                    img_path        = img_array,
                    model_name      = "Facenet512",   # better accuracy than Facenet
                    enforce_detection = False,         # don't skip if confidence is low
                    detector_backend = backend,
                    align            = True            # align face for better encoding
                )
                if not faces:
                    continue
                h, w = img_array.shape[:2]
                seen_regions = []
                for i, fd in enumerate(faces):
                    emb = fd.get("embedding")
                    if not emb:
                        continue
                    # Skip near-duplicate regions from multiple backends
                    reg = fd.get("facial_area", {})
                    x, y = reg.get("x", 0), reg.get("y", 0)
                    fw, fh = reg.get("w", 80), reg.get("h", 80)
                    # Ignore tiny detections (< 30px) — likely false positives
                    if fw < 30 or fh < 30:
                        continue
                    # De-duplicate: skip if this region overlaps one we already have
                    cx, cy = x + fw//2, y + fh//2
                    duplicate = False
                    for (ox, oy) in seen_regions:
                        if abs(cx-ox) < 40 and abs(cy-oy) < 40:
                            duplicate = True
                            break
                    if duplicate:
                        continue
                    seen_regions.append((cx, cy))
                    # Crop with padding
                    pad = 25
                    x1 = max(0, x - pad)
                    y1 = max(0, y - pad)
                    x2 = min(w, x + fw + pad)
                    y2 = min(h, y + fh + pad)
                    crop = img_array[y1:y2, x1:x2]
                    # Convert crop back to BGR for cv2.imwrite
                    crop_bgr = self.cv2.cvtColor(crop, self.cv2.COLOR_RGB2BGR)
                    results.append((emb, crop_bgr, len(results)))
                if results:
                    break   # stop trying other backends once we found faces
            except Exception as e:
                msg = str(e)
                if "Face could not be detected" not in msg and "No face" not in msg:
                    self.log("  [" + backend + "] " + Path(image_path).name + ": " + msg[:80])
                continue
        return results

    def cluster_embeddings(self, embeddings, tolerance=0.45):
        """
        Cluster face embeddings using cosine similarity (better than L2 for face vectors).
        Uses DBSCAN-style approach: a face joins a cluster if its cosine distance
        to ANY existing member is below tolerance.
        """
        import numpy as np
        if not embeddings:
            return []

        arr = np.array(embeddings, dtype=np.float32)

        # L2-normalise so dot-product == cosine similarity
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        arr = arr / norms

        n      = len(arr)
        labels = [-1] * n
        cid    = 0

        for i in range(n):
            if labels[i] != -1:
                continue
            labels[i] = cid
            # Compare against all unassigned faces
            for j in range(i + 1, n):
                if labels[j] != -1:
                    continue
                # Cosine distance = 1 - dot product (since vectors are normalised)
                cos_dist = 1.0 - float(np.dot(arr[i], arr[j]))
                if cos_dist < tolerance:
                    labels[j] = cid
            cid += 1

        return labels



# ─── Cluster Card (Canvas-based row with real face thumbnail) ─────────────────
class ClusterCard(tk.Frame):
    """A single row in the cluster sidebar showing a real face thumbnail.
    - Single click  → select and show photos
    - Ctrl+Click    → toggle multi-select for merge (blue border highlight)
    - Double-click  → select and open label dialog
    """
    THUMB = 48

    def __init__(self, parent, cluster_id, name, photo_count, face_img,
                 is_named, on_click, on_ctrl_click, on_double):
        super().__init__(parent, bg=CARD, cursor="hand2", pady=4)
        self.cluster_id    = cluster_id
        self.selected      = False   # normal single-click selection (blue bg)
        self.ctrl_selected = False   # ctrl-click multi-select (purple border)

        # face thumbnail canvas
        self._canvas = tk.Canvas(self, width=self.THUMB, height=self.THUMB,
                                 bg=CARD, highlightthickness=0)
        self._canvas.pack(side=tk.LEFT, padx=(6, 4))
        if face_img:
            self._canvas.create_image(0, 0, anchor="nw", image=face_img)
            self._canvas.image = face_img
        else:
            self._canvas.create_oval(4, 4, self.THUMB-4, self.THUMB-4,
                                     fill=BORDER, outline=MUTED, width=2)
            self._canvas.create_text(self.THUMB//2, self.THUMB//2,
                                     text="?", fill=MUTED, font=("Segoe UI", 16, "bold"))

        # text block
        self._txt = tk.Frame(self, bg=CARD)
        self._txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        color = GREEN if is_named else TEXT
        self._name_lbl = tk.Label(self._txt, text=name, bg=CARD, fg=color,
                                  font=("Segoe UI", 10, "bold"), anchor="w")
        self._name_lbl.pack(fill=tk.X)
        self._count_lbl = tk.Label(self._txt, text=str(photo_count) + " photos",
                                   bg=CARD, fg=MUTED, font=("Segoe UI", 8), anchor="w")
        self._count_lbl.pack(fill=tk.X)

        # ctrl-select badge label (hidden by default)
        self._badge = tk.Label(self, text="✓", bg=ACCENT2, fg="#fffdf9",
                               font=("Segoe UI", 9, "bold"), padx=4)

        # bind clicks on every child widget
        for w in [self, self._canvas, self._txt, self._name_lbl, self._count_lbl]:
            w.bind("<Button-1>",         lambda e, ci=cluster_id: on_click(ci))
            w.bind("<Control-Button-1>", lambda e, ci=cluster_id: on_ctrl_click(ci))
            w.bind("<Double-Button-1>",  lambda e, ci=cluster_id: on_double(ci))

    # normal single-click highlight (blue)
    def set_selected(self, val):
        self.selected = val
        self._refresh_bg()

    # ctrl-click multi-select highlight (purple accent)
    def set_ctrl_selected(self, val):
        self.ctrl_selected = val
        if val:
            self._badge.place(relx=1.0, rely=0.0, anchor="ne", x=-4, y=4)
        else:
            self._badge.place_forget()
        self._refresh_bg()

    def _refresh_bg(self):
        if self.ctrl_selected:
            bg = "#f5ede0"           # warm amber tint for multi-select
        elif self.selected:
            bg = BTN_HOV             # sand tint for single select
        else:
            bg = CARD
        self._set_bg_recursive(self, bg)

    def _set_bg_recursive(self, widget, bg):
        try:
            widget.configure(bg=bg)
        except:
            pass
        for child in widget.winfo_children():
            if child is not self._badge:
                self._set_bg_recursive(child, bg)



# ─── Main Application ─────────────────────────────────────────────────────────
class App:
    def __init__(self, root):
        self.root             = root
        self.root.title("Local Face Finder")
        self.root.geometry("1380x860")
        self.root.configure(bg=BG)
        self.db               = DB()
        self.engine           = None
        self.photo_cache      = {}
        self.face_thumb_cache = {}
        self.cluster_cards    = {}      # cid -> ClusterCard
        self.selected_cluster = None
        self._build_ui()
        self._load_engine_async()

    # ── Apply global styles ───────────────────────────────────────────────────
    def _apply_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame",        background=BG)
        s.configure("TLabel",        background=BG,     foreground=TEXT)
        s.configure("TButton",       background=BTN_BG,  foreground=TEXT, padding=7, relief="flat")
        s.map("TButton",             background=[("active", BTN_HOV)])
        s.configure("TEntry",        fieldbackground=CARD, foreground=TEXT, insertcolor=TEXT,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        s.configure("TScrollbar",    background=BTN_BG, troughcolor=BG2,
                    arrowcolor=MUTED, bordercolor=BORDER)
        s.configure("Horizontal.TProgressbar", troughcolor=BG2, background=ACCENT2,
                    bordercolor=BORDER)
        s.configure("TProgressbar",  troughcolor=BG2,  background=ACCENT2,
                    bordercolor=BORDER)

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        self._apply_styles()

        # ── Title bar ──
        title_bar = tk.Frame(self.root, bg=BG2, pady=10)
        title_bar.pack(fill=tk.X)
        tk.Label(title_bar, text="  Local Face Finder", bg=BG2, fg=ACCENT,
                 font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
        tk.Label(title_bar, text="Powered by DeepFace", bg=BG2, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=8)

        # ── Toolbar ──
        tb = tk.Frame(self.root, bg=BG2, padx=8, pady=6)
        tb.pack(fill=tk.X)
        btn_cfg = {"bg": BTN_BG, "fg": TEXT, "relief": "flat", "padx": 12, "pady": 6,
                   "font": ("Segoe UI", 9), "cursor": "hand2", "bd": 0,
                   "activebackground": BTN_HOV, "activeforeground": TEXT}
        tk.Button(tb, text="Scan Folder",       command=self.scan_folder,         **btn_cfg).pack(side=tk.LEFT, padx=3)
        tk.Button(tb, text="Google Photos URL", command=self.import_google_photos, **{**btn_cfg, "bg": "#c8b89a", "fg": TEXT}).pack(side=tk.LEFT, padx=3)
        tk.Button(tb, text="Detect Faces",      command=self.detect_faces,         **btn_cfg).pack(side=tk.LEFT, padx=3)
        tk.Button(tb, text="Re-Detect All",     command=self.redetect_faces,       **btn_cfg).pack(side=tk.LEFT, padx=3)
        tk.Button(tb, text="Cluster Faces",     command=self.cluster_faces,        **btn_cfg).pack(side=tk.LEFT, padx=3)
        tk.Button(tb, text="Merge Clusters",    command=self.merge_clusters_popup, **btn_cfg).pack(side=tk.LEFT, padx=3)
        tk.Button(tb, text="Clear All Data",    command=self.clear_data,           **btn_cfg).pack(side=tk.LEFT, padx=3)
        tk.Button(tb, text="Statistics",        command=self.show_stats,           **btn_cfg).pack(side=tk.LEFT, padx=3)

        # ── Status + progress ──
        self.status_var = tk.StringVar(value="Starting...")
        self.status_bar = tk.Label(self.root, textvariable=self.status_var,
                                   bg=BG2, fg=GREEN, anchor="w", padx=12, pady=5,
                                   font=("Segoe UI", 9))
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.progress = ttk.Progressbar(self.root, mode="indeterminate", style="TProgressbar")
        self.progress.pack(fill=tk.X, side=tk.BOTTOM)

        # ── Main pane ──
        pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL,
                              bg=BG, sashwidth=6, sashrelief="flat",
                              sashpad=0, handlesize=0)
        pane.pack(fill=tk.BOTH, expand=True)

        # Left sidebar
        left = tk.Frame(pane, bg=BG2, width=300)
        pane.add(left, minsize=260)
        self._build_sidebar(left)

        # Right panel
        right = tk.Frame(pane, bg=BG)
        pane.add(right, minsize=600)
        self._build_right(right)

    # ── Left sidebar ─────────────────────────────────────────────────────────
    def _build_sidebar(self, parent):
        # Header
        hdr = tk.Frame(parent, bg=BG2, pady=8)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="  People & Clusters", bg=BG2, fg=ACCENT2,
                 font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT)

        # Search
        sf = tk.Frame(parent, bg=BG2, padx=8, pady=4)
        sf.pack(fill=tk.X)
        tk.Label(sf, text="Search:", bg=BG2, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh_cluster_list())
        e = ttk.Entry(sf, textvariable=self.search_var)
        e.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        # Scrollable cluster list
        list_frame = tk.Frame(parent, bg=BG2)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.cluster_canvas = tk.Canvas(list_frame, bg=BG2, highlightthickness=0)
        sb = tk.Scrollbar(list_frame, orient=tk.VERTICAL,
                          command=self.cluster_canvas.yview)
        self.cluster_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.cluster_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.cluster_list_frame = tk.Frame(self.cluster_canvas, bg=BG2)
        self.cluster_canvas_win = self.cluster_canvas.create_window(
            (0, 0), window=self.cluster_list_frame, anchor="nw")
        self.cluster_list_frame.bind("<Configure>",
            lambda e: self.cluster_canvas.configure(
                scrollregion=self.cluster_canvas.bbox("all")))
        self.cluster_canvas.bind("<Configure>",
            lambda e: self.cluster_canvas.itemconfig(
                self.cluster_canvas_win, width=e.width))
        self.cluster_canvas.bind_all("<MouseWheel>",
            lambda e: self.cluster_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # Action buttons
        bf = tk.Frame(parent, bg=BG2, padx=8, pady=8)
        bf.pack(fill=tk.X)
        btn_cfg = {"bg": BTN_BG, "fg": TEXT, "relief": "flat", "pady": 6,
                   "font": ("Segoe UI", 9), "cursor": "hand2", "bd": 0,
                   "activebackground": BTN_HOV, "activeforeground": TEXT}
        tk.Button(bf, text="Label Selected",          command=self.label_cluster,  **btn_cfg).pack(fill=tk.X, pady=2)
        tk.Button(bf, text="Merge Selected (Ctrl+Click)", command=self.merge_selected, **btn_cfg).pack(fill=tk.X, pady=2)
        tk.Button(bf, text="Export Photos",           command=self.export_photos,  **btn_cfg).pack(fill=tk.X, pady=2)

    # ── Right photo panel ─────────────────────────────────────────────────────
    def _build_right(self, parent):
        # Panel title
        self.panel_title = tk.Label(parent, text="Select a cluster to view photos",
                                    bg=BG, fg=ACCENT, font=("Segoe UI", 12, "bold"),
                                    pady=10)
        self.panel_title.pack(fill=tk.X)

        # Scrollable photo grid
        cf = tk.Frame(parent, bg=BG)
        cf.pack(fill=tk.BOTH, expand=True)
        vscroll = tk.Scrollbar(cf, orient=tk.VERTICAL, bg=BORDER)
        vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.photo_canvas = tk.Canvas(cf, bg=BG, highlightthickness=0,
                                      yscrollcommand=vscroll.set)
        self.photo_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vscroll.config(command=self.photo_canvas.yview)
        self.grid_frame = tk.Frame(self.photo_canvas, bg=BG)
        self.grid_win = self.photo_canvas.create_window(
            (0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>",
            lambda e: self.photo_canvas.configure(
                scrollregion=self.photo_canvas.bbox("all")))
        self.photo_canvas.bind("<Configure>",
            lambda e: self.photo_canvas.itemconfig(self.grid_win, width=e.width))
        self.photo_canvas.bind_all("<MouseWheel>",
            lambda e: self.photo_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))



    # ── Engine ────────────────────────────────────────────────────────────────
    def _load_engine_async(self):
        self.status("Loading AI engine... first launch downloads models (~300MB)")
        self.progress.start()
        def load():
            try:
                self.engine = FaceEngine(log_fn=self.status)
                self.root.after(0, lambda: self.status("Ready! Click Scan Folder to begin."))
            except Exception as e:
                self.root.after(0, lambda: self.status("Engine error: " + str(e)))
            finally:
                self.root.after(0, self.progress.stop)
        threading.Thread(target=load, daemon=True).start()

    # ── Scan Folder ───────────────────────────────────────────────────────────
    def scan_folder(self):
        folder = filedialog.askdirectory(title="Select folder containing photos")
        if not folder:
            return
        # Show scanning popup with progress
        popup = tk.Toplevel(self.root)
        popup.title("Scanning Folder")
        popup.geometry("460x160")
        popup.resizable(False, False)
        popup.configure(bg=BG2)
        popup.grab_set()
        tk.Label(popup, text="Scanning folder for images...", bg=BG2, fg=ACCENT,
                 font=("Segoe UI", 12, "bold")).pack(pady=(20, 8))
        scan_var = tk.StringVar(value="Please wait...")
        tk.Label(popup, textvariable=scan_var, bg=BG2, fg=TEXT,
                 font=("Segoe UI", 9)).pack()
        scan_bar = ttk.Progressbar(popup, mode="indeterminate", length=400)
        scan_bar.pack(pady=12, padx=30)
        scan_bar.start(10)
        popup.update()

        def do_scan():
            images = [str(p) for p in Path(folder).rglob("*")
                      if p.suffix.lower() in SUPPORTED]
            for path in images:
                self.db.add_image(path)
            self.root.after(0, lambda: self._scan_done(popup, len(images)))

        threading.Thread(target=do_scan, daemon=True).start()

    def _scan_done(self, popup, count):
        try:
            popup.destroy()
        except:
            pass
        self.status("Found " + str(count) + " images. Click Detect Faces.")
        messagebox.showinfo("Scan Complete", "Found " + str(count) + " images.\nNow click Detect Faces.")

    # ── Import from Google Photos Shared Album ────────────────────────────────
    def import_google_photos(self):
        """
        Full flow:
        Step 1 - User pastes URL and picks save folder
        Step 2 - App fetches album info (photo count + estimated size)
        Step 3 - Confirmation dialog shows details before any download
        Step 4 - Downloads with live per-photo progress bar
        Step 5 - Auto-starts face detection after download
        """
        import subprocess, sys, re

        win = tk.Toplevel(self.root)
        win.title("Import from Google Photos")
        win.geometry("600x440")
        win.resizable(False, False)
        win.configure(bg=BG2)
        win.grab_set()

        # ── Header ──────────────────────────────────────────────────────────
        tk.Label(win, text="Import Google Photos Album",
                 bg=BG2, fg=ACCENT, font=("Segoe UI", 14, "bold")).pack(pady=(18, 2))
        tk.Label(win, text="Paste a PUBLIC shared album link  (Anyone with link can view)",
                 bg=BG2, fg=MUTED, font=("Segoe UI", 9)).pack(pady=(0, 10))

        # ── URL input ────────────────────────────────────────────────────────
        url_frame = tk.Frame(win, bg=BG2)
        url_frame.pack(fill=tk.X, padx=28)
        tk.Label(url_frame, text="Album URL:", bg=BG2, fg=TEXT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        url_var = tk.StringVar()
        url_entry = ttk.Entry(url_frame, textvariable=url_var, width=62,
                              font=("Segoe UI", 10))
        url_entry.pack(fill=tk.X, pady=(2, 10))
        url_entry.focus()

        # ── Save folder picker ───────────────────────────────────────────────
        folder_frame = tk.Frame(win, bg=BG2)
        folder_frame.pack(fill=tk.X, padx=28)
        tk.Label(folder_frame, text="Save photos to:", bg=BG2, fg=TEXT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        folder_row = tk.Frame(folder_frame, bg=BG2)
        folder_row.pack(fill=tk.X, pady=(2, 4))
        save_dir_var = tk.StringVar(value=str(DATA_DIR / "google_photos"))
        ttk.Entry(folder_row, textvariable=save_dir_var, width=48,
                  font=("Segoe UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True)

        def pick_folder():
            chosen = filedialog.askdirectory(title="Choose where to save photos",
                                             initialdir=save_dir_var.get())
            if chosen:
                save_dir_var.set(chosen)

        tk.Button(folder_row, text="Browse...", command=pick_folder,
                  bg=BTN_BG, fg=TEXT, relief="flat", padx=8, pady=4,
                  font=("Segoe UI", 9), cursor="hand2", bd=0,
                  activebackground=BTN_HOV).pack(side=tk.LEFT, padx=(6, 0))

        # ── Separator ────────────────────────────────────────────────────────
        tk.Frame(win, bg=BORDER, height=1).pack(fill=tk.X, padx=28, pady=10)

        # ── Info / status area ───────────────────────────────────────────────
        info_var   = tk.StringVar(value="Click 'Check Album' to fetch photo count and size.")
        status_var = tk.StringVar(value="")
        tk.Label(win, textvariable=info_var, bg=BG2, fg=TEXT,
                 font=("Segoe UI", 10), justify="left").pack(padx=28, anchor="w")
        status_lbl = tk.Label(win, textvariable=status_var, bg=BG2, fg=MUTED,
                              font=("Segoe UI", 9))
        status_lbl.pack(padx=28, anchor="w", pady=(2, 0))

        # ── Progress bar (shown only during download) ────────────────────────
        pbar_outer = tk.Frame(win, bg=BG2)
        pbar_outer.pack(fill=tk.X, padx=28, pady=4)
        pbar = ttk.Progressbar(pbar_outer, mode="determinate", length=544)
        pbar_lbl = tk.Label(pbar_outer, text="", bg=BG2, fg=MUTED, font=("Segoe UI", 8))

        # ── Buttons ──────────────────────────────────────────────────────────
        tk.Frame(win, bg=BORDER, height=1).pack(fill=tk.X, padx=28, pady=(8, 0))
        btn_row = tk.Frame(win, bg=BG2)
        btn_row.pack(pady=10)

        S = {"relief": "flat", "padx": 14, "pady": 7,
             "font": ("Segoe UI", 10, "bold"), "cursor": "hand2", "bd": 0}

        fetch_btn    = tk.Button(btn_row, text="Check Album",
                                 bg=ACCENT2, fg="#fffdf9",
                                 activebackground=ACCENT, **S)
        fetch_btn.pack(side=tk.LEFT, padx=5)

        download_btn = tk.Button(btn_row, text="Download & Detect Faces",
                                 bg=GREEN, fg="#fffdf9",
                                 activebackground="#4a7a4a", **S,
                                 state="disabled")
        download_btn.pack(side=tk.LEFT, padx=5)

        tk.Button(btn_row, text="Cancel", command=win.destroy,
                  bg=BTN_BG, fg=TEXT, relief="flat", padx=14, pady=7,
                  font=("Segoe UI", 9), cursor="hand2", bd=0,
                  activebackground=BTN_HOV).pack(side=tk.LEFT, padx=5)

        tk.Label(win, text="Only PUBLIC albums work.  Private albums require Google OAuth login.",
                 bg=BG2, fg=MUTED, font=("Segoe UI", 8)).pack(pady=(0, 8))

        # ── Shared state dict ────────────────────────────────────────────────
        album = {"urls": [], "count": 0, "est_mb": 0.0}

        def set_info(msg):
            info_var.set(msg)
            win.update_idletasks()

        def set_status(msg, color=MUTED):
            status_var.set(msg)
            status_lbl.config(fg=color)
            win.update_idletasks()

        # ────────────────────────────────────────────────────────────────────
        # STEP 1 — CHECK ALBUM INFO (no download yet)
        # ────────────────────────────────────────────────────────────────────
        def check_album():
            url = url_var.get().strip()
            if not url:
                set_status("Please paste an album URL first.", RED)
                return
            if "photos.app.goo.gl" not in url and "photos.google.com" not in url:
                set_status("Not a valid Google Photos link.", RED)
                return

            fetch_btn.config(state="disabled", text="Checking...")
            download_btn.config(state="disabled")
            set_info("Connecting to album, please wait...")
            set_status("")
            pbar.pack_forget()
            pbar_lbl.pack_forget()

            def run():
                try:
                    try:
                        import requests
                    except ImportError:
                        set_status("Installing requests...", YELLOW)
                        subprocess.check_call(
                            [sys.executable, "-m", "pip", "install",
                             "requests", "beautifulsoup4", "--quiet"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        import requests

                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                                      "Chrome/120.0.0.0 Safari/537.36"
                    }
                    resp = requests.get(url, headers=headers, timeout=30)
                    resp.raise_for_status()

                    # Extract Google Photos CDN URLs from page source
                    raw = re.findall(
                        r'https://lh3\.googleusercontent\.com/[A-Za-z0-9_\-]+'
                        r'(?:=[A-Za-z0-9_\-\.]+)*',
                        resp.text
                    )
                    seen, clean = set(), []
                    for u in raw:
                        base = re.sub(r'=.*$', '', u)
                        if base not in seen and len(base) > 60:
                            seen.add(base)
                            clean.append(base)

                    count   = len(clean)
                    est_mb  = round(count * 3.5, 1)
                    est_gb  = round(est_mb / 1024, 2)
                    sz_str  = (str(est_gb) + " GB") if est_mb > 1024 else (str(est_mb) + " MB")

                    album["urls"]   = clean
                    album["count"]  = count
                    album["est_mb"] = est_mb

                    if count == 0:
                        self.root.after(0, lambda: set_info(
                            "No photos found in this album.\n"
                            "Album may be private or require login."))
                        self.root.after(0, lambda: set_status(
                            "Check album privacy settings.", RED))
                        self.root.after(0, lambda: fetch_btn.config(
                            state="normal", text="Check Album"))
                        return

                    msg = (
                        "Album found!\n\n"
                        "   Photos found    :  " + str(count) + " images\n"
                        "   Estimated size  :  " + sz_str +
                        "  (approx. " + str(round(count * 3.5)) + " MB at ~3.5 MB/photo)\n"
                        "   Save location   :  " + save_dir_var.get()
                    )
                    self.root.after(0, lambda: set_info(msg))
                    self.root.after(0, lambda: set_status(
                        "Ready to download. Click 'Download & Detect Faces' to proceed.", GREEN))
                    self.root.after(0, lambda: download_btn.config(state="normal"))
                    self.root.after(0, lambda: fetch_btn.config(
                        state="normal", text="Re-Check"))

                except Exception as e:
                    err = str(e)[:100]
                    self.root.after(0, lambda: set_info(""))
                    self.root.after(0, lambda: set_status("Error: " + err, RED))
                    self.root.after(0, lambda: fetch_btn.config(
                        state="normal", text="Check Album"))

            threading.Thread(target=run, daemon=True).start()

        fetch_btn.config(command=check_album)

        # ────────────────────────────────────────────────────────────────────
        # STEP 2 — DOWNLOAD WITH LIVE PROGRESS + AUTO DETECT
        # ────────────────────────────────────────────────────────────────────
        def start_download():
            urls    = album["urls"]
            count   = album["count"]
            est_mb  = album["est_mb"]
            sz_str  = (str(round(est_mb/1024, 2)) + " GB") if est_mb > 1024 else (str(est_mb) + " MB")

            if count == 0:
                set_status("Check album info first.", RED)
                return

            save_dir = Path(save_dir_var.get().strip())
            if not str(save_dir).strip():
                set_status("Please choose a save folder.", RED)
                return

            # ── Confirmation dialog ──────────────────────────────────────────
            confirmed = messagebox.askyesno(
                "Confirm Download",
                "You are about to download:\n\n"
                "   Photos   :  " + str(count) + " images\n"
                "   Est. size:  " + sz_str + "\n"
                "   Save to  :  " + str(save_dir) + "\n\n"
                "After download completes, face detection will\n"
                "start automatically.\n\nProceed?",
                parent=win
            )
            if not confirmed:
                return

            # Lock buttons
            fetch_btn.config(state="disabled")
            download_btn.config(state="disabled", text="Downloading...")

            # Show progress bar
            pbar.config(maximum=count, value=0, mode="determinate")
            pbar.pack(fill=tk.X, pady=(4, 0))
            pbar_lbl.config(text="Starting download...")
            pbar_lbl.pack(anchor="w")
            set_info("Downloading " + str(count) + " photos to:\n" + str(save_dir))

            def run():
                try:
                    import requests
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                      "AppleWebKit/537.36 Chrome/120 Safari/537.36"
                    }
                    save_dir.mkdir(parents=True, exist_ok=True)
                    total_bytes = 0
                    n_saved     = 0

                    for i, base_url in enumerate(urls):
                        try:
                            r = requests.get(base_url + "=d", headers=headers, timeout=30)
                            r.raise_for_status()
                            ct  = r.headers.get("Content-Type", "image/jpeg")
                            ext = ".jpg" if "jpeg" in ct else ".png" if "png" in ct else ".jpg"
                            out = save_dir / ("photo_" + str(i+1).zfill(4) + ext)
                            out.write_bytes(r.content)
                            self.db.add_image(str(out))
                            total_bytes += len(r.content)
                            n_saved     += 1
                        except:
                            pass

                        done      = i + 1
                        remaining = count - done
                        mb_done   = round(total_bytes / 1024 / 1024, 1)

                        def upd(d=done, rem=remaining, mb=mb_done):
                            try:
                                pbar["value"] = d
                                pbar_lbl.config(text=(
                                    str(d) + " / " + str(count) +
                                    "   |   " + str(rem) + " remaining" +
                                    "   |   " + str(mb) + " MB downloaded"
                                ))
                                set_status("Downloading photo " + str(d) + " of " + str(count) + "...", MUTED)
                            except:
                                pass

                        self.root.after(0, upd)

                    saved = n_saved
                    self.root.after(0, lambda: self._gphoto_done(win, saved, auto_detect=True))

                except Exception as e:
                    err = str(e)[:100]
                    self.root.after(0, lambda: set_status("Download error: " + err, RED))
                    self.root.after(0, lambda: download_btn.config(
                        state="normal", text="Download & Detect Faces"))

            threading.Thread(target=run, daemon=True).start()

        download_btn.config(command=start_download)

    def _scrape_google_photos_fallback(self, url, dest_dir):
        """
        Fallback: scrape image URLs directly from the Google Photos album HTML page.
        This works for simple public albums when gallery-dl fails.
        """
        try:
            import requests
            from bs4 import BeautifulSoup
            import re

            self.status("Fallback: scraping album page...")
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                     "AppleWebKit/537.36 Chrome/120 Safari/537.36"}
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()

            # Google Photos embeds image URLs in the page JS as JSON-like arrays
            # Pattern: ["https://lh3.googleusercontent.com/..."] (high-res image URLs)
            img_urls = re.findall(
                r'(https://lh3\.googleusercontent\.com/[A-Za-z0-9_\-]+=w\d+[^\'"]*)',
                resp.text
            )
            # Deduplicate
            seen = set()
            unique_urls = []
            for u in img_urls:
                # Force highest resolution: replace size suffix with =d (download)
                base = re.sub(r'=w\d+.*$', '', u)
                if base not in seen:
                    seen.add(base)
                    unique_urls.append(base + "=d")

            if not unique_urls:
                return []

            self.status("Downloading " + str(len(unique_urls)) + " images...")
            saved = []
            for i, img_url in enumerate(unique_urls):
                try:
                    r = requests.get(img_url, headers=headers, timeout=20)
                    r.raise_for_status()
                    # Determine extension from content-type
                    ct = r.headers.get("Content-Type", "image/jpeg")
                    ext = ".jpg" if "jpeg" in ct else ".png" if "png" in ct else ".jpg"
                    out = dest_dir / ("photo_" + str(i+1).zfill(4) + ext)
                    out.write_bytes(r.content)
                    saved.append(out)
                    self.status("Downloaded " + str(i+1) + " / " + str(len(unique_urls)))
                except:
                    continue
            return saved
        except Exception as e:
            self.status("Fallback scraping failed: " + str(e)[:60])
            return []

    def _gphoto_done(self, win, count, auto_detect=False):
        try:
            win.destroy()
        except:
            pass
        self.status("Downloaded " + str(count) + " photos from Google Photos.")
        if auto_detect:
            messagebox.showinfo("Download Complete",
                                "Downloaded " + str(count) + " photos!\n\n"
                                "Starting face detection now...")
            self.detect_faces()
        else:
            messagebox.showinfo("Import Complete",
                                "Downloaded " + str(count) + " photos!\n"
                                "Click 'Detect Faces' to find faces.")

    # ── Detect Faces ──────────────────────────────────────────────────────────
    def detect_faces(self):
        if not self.engine:
            messagebox.showerror("Not Ready", "AI engine is still loading. Please wait.")
            return
        images = self.db.conn.execute("SELECT id,path FROM images WHERE scanned=0").fetchall()
        if not images:
            messagebox.showinfo("Nothing To Do", "No unscanned images. Scan a folder first or use Re-Detect All.")
            return
        total = len(images)
        if not messagebox.askyesno("Detect Faces", "Detect faces in " + str(total) + " images?"):
            return

        # ── Progress popup ──
        popup = tk.Toplevel(self.root)
        popup.title("Detecting Faces")
        popup.geometry("540x460")
        popup.resizable(False, False)
        popup.configure(bg=BG2)

        tk.Label(popup, text="Scanning Photos for Faces", bg=BG2, fg=ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(pady=(16, 8))

        # photo preview box
        prev_frame = tk.Frame(popup, bg=CARD, width=210, height=210)
        prev_frame.pack()
        prev_frame.pack_propagate(False)
        prev_lbl = tk.Label(prev_frame, bg=CARD, text="Loading...", fg=MUTED,
                            font=("Segoe UI", 9))
        prev_lbl.place(relx=0.5, rely=0.5, anchor="center")

        fname_var   = tk.StringVar(value="Starting...")
        counter_var = tk.StringVar(value="0 / " + str(total) + "   |   " + str(total) + " remaining")
        faces_var   = tk.StringVar(value="Faces found: 0")

        tk.Label(popup, textvariable=fname_var, bg=BG2, fg=TEXT,
                 font=("Segoe UI", 9), wraplength=500).pack(pady=(8, 1))
        tk.Label(popup, textvariable=counter_var, bg=BG2, fg=GREEN,
                 font=("Segoe UI", 10, "bold")).pack(pady=1)
        tk.Label(popup, textvariable=faces_var, bg=BG2, fg=YELLOW,
                 font=("Segoe UI", 9)).pack(pady=1)

        pbar = ttk.Progressbar(popup, mode="determinate", maximum=total, length=480)
        pbar.pack(pady=10, padx=28)

        def update_preview(img_path):
            try:
                img = Image.open(img_path)
                img.thumbnail((210, 210))
                photo = ImageTk.PhotoImage(img)
                prev_lbl.config(image=photo, text="")
                prev_lbl.image = photo
            except:
                prev_lbl.config(image="", text="Preview N/A")

        def run():
            found = 0
            n = len(images)
            for idx, row in enumerate(images):
                img_id, img_path = row[0], row[1]
                done = idx + 1
                left = n - done
                fname = Path(img_path).name
                def gui_update(p=img_path, d=done, l=left, f=fname):
                    try:
                        fname_var.set(f)
                        counter_var.set(str(d) + " / " + str(n) + "   |   " + str(l) + " remaining")
                        pbar["value"] = d
                        update_preview(p)
                    except:
                        pass
                self.root.after(0, gui_update)
                detected = self.engine.detect_and_encode(img_path)
                for emb, crop, fi in detected:
                    crop_path = CROP_DIR / (str(img_id) + "_" + str(fi) + ".jpg")
                    try:
                        import cv2
                        cv2.imwrite(str(crop_path), crop)
                    except:
                        pass
                    self.db.add_face(img_id, crop_path, emb, fi)
                    found += 1
                self.db.mark_scanned(img_id)
                f2 = found
                self.root.after(0, lambda x=f2: faces_var.set("Faces found: " + str(x)))
            self.root.after(0, lambda: self._detect_done(found, popup))
        threading.Thread(target=run, daemon=True).start()

    def _detect_done(self, found, popup=None):
        try:
            popup.destroy()
        except:
            pass
        self.progress.stop()
        self.status("Done! Found " + str(found) + " faces. Click Cluster Faces.")
        messagebox.showinfo("Done", "Found " + str(found) + " faces.\nNow click Cluster Faces.")

    def redetect_faces(self):
        if not messagebox.askyesno("Re-Detect All", "Delete all face data and re-scan? Continue?"):
            return
        self.db.reset_scanned()
        for f in CROP_DIR.iterdir():
            try:
                f.unlink()
            except:
                pass
        self.face_thumb_cache.clear()
        self.refresh_cluster_list()
        self.detect_faces()



    # ── Cluster Faces ─────────────────────────────────────────────────────────
    def cluster_faces(self):
        if not self.engine:
            messagebox.showerror("Not Ready", "AI engine is still loading.")
            return
        rows = self.db.get_all_faces()
        if not rows:
            messagebox.showinfo("No Faces", "No faces found. Run Detect Faces first.")
            return
        tol = simpledialog.askfloat("Tolerance",
            "Enter clustering tolerance (cosine distance):\n"
            "  0.25 = very strict  (safer, may create more clusters)\n"
            "  0.35 = balanced     (recommended)\n"
            "  0.50 = loose        (may mix different people)\n\n"
            "Start with 0.35 and adjust if needed.",
            initialvalue=0.35, minvalue=0.05, maxvalue=0.8, parent=self.root)
        if tol is None:
            return
        self.progress.start()
        self.status("Clustering " + str(len(rows)) + " faces...")
        def run():
            embs   = [json.loads(r["embedding"]) for r in rows]
            labels = self.engine.cluster_embeddings(embs, tolerance=tol)
            for row, label in zip(rows, labels):
                self.db.update_face_cluster(row["id"], label)
            n = len(set(l for l in labels if l >= 0))
            self.root.after(0, lambda: self._cluster_done(n))
        threading.Thread(target=run, daemon=True).start()

    def _cluster_done(self, n):
        self.progress.stop()
        self.face_thumb_cache.clear()
        self.refresh_cluster_list()
        self.status("Found " + str(n) + " clusters. Select one on the left.")
        messagebox.showinfo("Done", "Found " + str(n) + " clusters!\nSelect one on the left to view photos.")

    # ── Cluster Sidebar ───────────────────────────────────────────────────────
    def _get_face_thumb(self, cluster_id):
        if cluster_id in self.face_thumb_cache:
            return self.face_thumb_cache[cluster_id]
        crop_path = self.db.get_first_crop(cluster_id)
        if crop_path and Path(crop_path).exists():
            try:
                img   = Image.open(crop_path).resize((48, 48), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.face_thumb_cache[cluster_id] = photo
                return photo
            except:
                pass
        return None

    def refresh_cluster_list(self):
        # Destroy old cards
        for w in self.cluster_list_frame.winfo_children():
            w.destroy()
        self.cluster_cards.clear()

        query   = self.search_var.get().lower()
        clusters = self.db.get_clusters()

        if not clusters:
            tk.Label(self.cluster_list_frame,
                     text="No clusters yet.\nRun Detect + Cluster Faces.",
                     bg=BG2, fg=MUTED, font=("Segoe UI", 9),
                     justify="center").pack(pady=30)
            return

        for row in clusters:
            cid   = row["cluster_id"]
            name  = row["person_name"] or ("Cluster " + str(cid))
            if query and query not in name.lower():
                continue
            photo = self._get_face_thumb(cid)
            card  = ClusterCard(
                parent        = self.cluster_list_frame,
                cluster_id    = cid,
                name          = name,
                photo_count   = row["photo_count"],
                face_img      = photo,
                is_named      = bool(row["person_name"]),
                on_click      = self._on_cluster_click,
                on_ctrl_click = self._on_cluster_ctrl_click,
                on_double     = self._on_cluster_double
            )
            card.pack(fill=tk.X, padx=4, pady=2)
            # separator
            tk.Frame(self.cluster_list_frame, bg=BORDER, height=1).pack(fill=tk.X, padx=4)
            self.cluster_cards[cid] = card

        # Restore selection highlight
        if self.selected_cluster and self.selected_cluster in self.cluster_cards:
            self.cluster_cards[self.selected_cluster].set_selected(True)

    def _on_cluster_click(self, cluster_id):
        # Deselect previous normal selection
        if self.selected_cluster and self.selected_cluster in self.cluster_cards:
            self.cluster_cards[self.selected_cluster].set_selected(False)
        self.selected_cluster = cluster_id
        if cluster_id in self.cluster_cards:
            self.cluster_cards[cluster_id].set_selected(True)
        self._show_cluster_photos(cluster_id)

    def _on_cluster_ctrl_click(self, cluster_id):
        """Toggle ctrl-click multi-select for merge — does NOT change photo panel."""
        card = self.cluster_cards.get(cluster_id)
        if card is None:
            return
        # toggle
        new_state = not card.ctrl_selected
        card.set_ctrl_selected(new_state)
        count = sum(1 for c in self.cluster_cards.values() if c.ctrl_selected)
        if count > 0:
            self.status(str(count) + " clusters selected for merge. Click 'Merge Selected'.")
        else:
            self.status("Ready.")

    def _on_cluster_double(self, cluster_id):
        self._on_cluster_click(cluster_id)
        self.label_cluster()

    # ── Photo Grid ────────────────────────────────────────────────────────────
    def _show_cluster_photos(self, cluster_id):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.photo_cache.clear()

        row = self.db.conn.execute(
            "SELECT person_name FROM clusters WHERE id=?", (cluster_id,)).fetchone()
        label = row["person_name"] if row and row["person_name"] else "Cluster " + str(cluster_id)
        self.panel_title.config(text="  " + label)

        rows = self.db.get_images_for_cluster(cluster_id)
        if not rows:
            tk.Label(self.grid_frame, text="No photos found for this cluster.",
                     bg=BG, fg=MUTED, font=("Segoe UI", 10)).grid(row=0, column=0, padx=30, pady=40)
            return

        COLS  = 5
        THUMB = 200
        for idx, row in enumerate(rows):
            path = row["path"]
            r, c = divmod(idx, COLS)
            card = tk.Frame(self.grid_frame, bg=CARD, padx=4, pady=4)
            card.grid(row=r, column=c, padx=8, pady=8)
            try:
                img   = Image.open(path)
                img.thumbnail((THUMB, THUMB))
                photo = ImageTk.PhotoImage(img)
                self.photo_cache[path] = photo
                btn = tk.Button(card, image=photo, bg=CARD,
                                activebackground=BTN_HOV, relief="flat",
                                cursor="hand2", bd=0,
                                command=lambda p=path: self._open_file(p))
                btn.pack()
            except:
                tk.Label(card, text="Error", bg=CARD, fg=RED).pack()
            fname = Path(path).name
            if len(fname) > 22:
                fname = fname[:20] + "..."
            tk.Label(card, text=fname, bg=CARD, fg=MUTED,
                     font=("Segoe UI", 8)).pack()
        self.status("Showing " + str(len(rows)) + " photos for " + label)



    # ── Label / Export / Merge ────────────────────────────────────────────────
    def label_cluster(self):
        if self.selected_cluster is None:
            messagebox.showwarning("No Selection", "Click a cluster on the left first.")
            return
        name = simpledialog.askstring("Label Person",
            "Enter name for Cluster " + str(self.selected_cluster) + ":",
            parent=self.root)
        if name and name.strip():
            self.db.update_cluster_name(self.selected_cluster, name.strip())
            self.face_thumb_cache.pop(self.selected_cluster, None)
            self.refresh_cluster_list()
            self.panel_title.config(text="  " + name.strip())
            self.status("Labeled as: " + name.strip())

    def export_photos(self):
        if self.selected_cluster is None:
            messagebox.showwarning("No Selection", "Click a cluster on the left first.")
            return
        dest = filedialog.askdirectory(title="Choose export folder")
        if not dest:
            return
        row = self.db.conn.execute(
            "SELECT person_name FROM clusters WHERE id=?", (self.selected_cluster,)).fetchone()
        folder_name = (row["person_name"].replace(" ", "_")
                       if row and row["person_name"]
                       else "Cluster_" + str(self.selected_cluster))
        out_dir = Path(dest) / folder_name
        out_dir.mkdir(parents=True, exist_ok=True)
        rows  = self.db.get_images_for_cluster(self.selected_cluster)
        count = 0
        for row in rows:
            try:
                shutil.copy2(row["path"], out_dir / Path(row["path"]).name)
                count += 1
            except:
                pass
        messagebox.showinfo("Export Done", "Exported " + str(count) + " photos to:\n" + str(out_dir))
        self.status("Exported " + str(count) + " photos.")

    def merge_selected(self):
        selected_ids = [cid for cid, card in self.cluster_cards.items() if card.ctrl_selected]
        if len(selected_ids) < 2:
            messagebox.showwarning("Select More",
                "Ctrl+Click at least 2 cluster cards to select them\n"
                "(they turn purple with a checkmark),\nthen click Merge Selected.\n\n"
                "Or use the Merge Clusters button in the toolbar.")
            return
        names = []
        for cid in selected_ids:
            row = self.db.conn.execute("SELECT person_name FROM clusters WHERE id=?", (cid,)).fetchone()
            names.append(row["person_name"] if row and row["person_name"] else "Cluster " + str(cid))
        if not messagebox.askyesno("Merge", "Merge " + str(len(selected_ids)) + " clusters?\n\n" + "\n".join(names)):
            return
        keep = selected_ids[0]
        for mid in selected_ids[1:]:
            self.db.merge_clusters(keep, mid)
        self.face_thumb_cache.clear()
        self.selected_cluster = keep
        self.refresh_cluster_list()
        messagebox.showinfo("Done", "Merged " + str(len(selected_ids)) + " clusters successfully!")
        self.status("Merged " + str(len(selected_ids)) + " clusters.")

    def merge_clusters_popup(self):
        win = tk.Toplevel(self.root)
        win.title("Merge Clusters")
        win.geometry("520x580")
        win.configure(bg=BG2)
        win.grab_set()

        tk.Label(win, text="Merge Clusters", bg=BG2, fg=ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(pady=(16, 4))
        tk.Label(win, text="Ctrl+Click rows to select multiple, then click Merge.",
                 bg=BG2, fg=MUTED, font=("Segoe UI", 9)).pack(pady=(0, 8))

        lf = tk.Frame(win, bg=BG2)
        lf.pack(fill=tk.BOTH, expand=True, padx=16, pady=4)

        # Scrollable list with face thumbnails
        merge_canvas = tk.Canvas(lf, bg=BG2, highlightthickness=0)
        msb = tk.Scrollbar(lf, orient=tk.VERTICAL, command=merge_canvas.yview)
        merge_canvas.configure(yscrollcommand=msb.set)
        msb.pack(side=tk.RIGHT, fill=tk.Y)
        merge_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = tk.Frame(merge_canvas, bg=BG2)
        merge_canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
            lambda e: merge_canvas.configure(scrollregion=merge_canvas.bbox("all")))

        selected_merge = set()
        row_frames = {}

        def toggle(cid, frame):
            if cid in selected_merge:
                selected_merge.discard(cid)
                frame.configure(bg=CARD)
                for w in frame.winfo_children():
                    try: w.configure(bg=CARD)
                    except: pass
            else:
                selected_merge.add(cid)
                frame.configure(bg=BTN_HOV)
                for w in frame.winfo_children():
                    try: w.configure(bg=BTN_HOV)
                    except: pass

        for row in self.db.get_clusters():
            cid   = row["cluster_id"]
            name  = row["person_name"] or ("Cluster " + str(cid))
            photo = self._get_face_thumb(cid)
            rf    = tk.Frame(inner, bg=CARD, pady=4, cursor="hand2")
            rf.pack(fill=tk.X, pady=2, padx=4)
            row_frames[cid] = rf
            c = tk.Canvas(rf, width=48, height=48, bg=CARD, highlightthickness=0)
            c.pack(side=tk.LEFT, padx=(6, 4))
            if photo:
                c.create_image(0, 0, anchor="nw", image=photo)
                c.image = photo
            else:
                c.create_oval(4, 4, 44, 44, fill=BORDER, outline=MUTED)
                c.create_text(24, 24, text="?", fill=MUTED, font=("Segoe UI", 14, "bold"))
            txt_f = tk.Frame(rf, bg=CARD)
            txt_f.pack(side=tk.LEFT)
            tk.Label(txt_f, text=name, bg=CARD, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(anchor="w")
            tk.Label(txt_f, text=str(row["photo_count"]) + " photos", bg=CARD, fg=MUTED,
                     font=("Segoe UI", 8)).pack(anchor="w")
            for w in [rf, c, txt_f] + list(txt_f.winfo_children()):
                w.bind("<Button-1>", lambda e, ci=cid, f=rf: toggle(ci, f))
            tk.Frame(inner, bg=BORDER, height=1).pack(fill=tk.X, padx=4)

        name_var = tk.StringVar(value="")
        nf = tk.Frame(win, bg=BG2, padx=16, pady=6)
        nf.pack(fill=tk.X)
        tk.Label(nf, text="New name (optional):", bg=BG2, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        ttk.Entry(nf, textvariable=name_var, width=24).pack(side=tk.LEFT, padx=8)

        def do_merge():
            if len(selected_merge) < 2:
                messagebox.showwarning("Select More", "Click at least 2 clusters.", parent=win)
                return
            ids  = list(selected_merge)
            keep = ids[0]
            for mid in ids[1:]:
                self.db.merge_clusters(keep, mid)
            merged_name = name_var.get().strip()
            if merged_name:
                self.db.update_cluster_name(keep, merged_name)
            self.face_thumb_cache.clear()
            self.selected_cluster = keep
            self.refresh_cluster_list()
            win.destroy()
            messagebox.showinfo("Done", "Merged " + str(len(ids)) + " clusters!")
            self.status("Merged " + str(len(ids)) + " clusters!")

        btn_row = tk.Frame(win, bg=BG2)
        btn_row.pack(pady=12)
        btn_cfg = {"bg": ACCENT2, "fg": "#fffdf9", "relief": "flat", "padx": 14, "pady": 8,
                   "font": ("Segoe UI", 10, "bold"), "cursor": "hand2", "bd": 0}
        tk.Button(btn_row, text="Merge Selected Clusters", command=do_merge, **btn_cfg).pack(side=tk.LEFT, padx=8)
        tk.Button(btn_row, text="Cancel", command=win.destroy,
                  bg=BTN_BG, fg=TEXT, relief="flat", padx=14, pady=8,
                  font=("Segoe UI", 9), cursor="hand2", bd=0).pack(side=tk.LEFT, padx=8)

    # ── Clear / Stats / Utils ─────────────────────────────────────────────────
    def clear_data(self):
        if not messagebox.askyesno("Clear All Data",
                                   "Delete ALL face data?\nYour original photos will NOT be deleted."):
            return
        self.db.clear_all()
        for f in CROP_DIR.iterdir():
            try: f.unlink()
            except: pass
        self.face_thumb_cache.clear()
        self.selected_cluster = None
        self.refresh_cluster_list()
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.panel_title.config(text="Select a cluster to view photos")
        self.status("Cleared. Scan a folder to start fresh.")

    def show_stats(self):
        images, faces, people, clusters = self.db.get_stats()
        messagebox.showinfo("Statistics",
            "Images scanned : " + str(images) + "\n"
            "Faces detected : " + str(faces) + "\n"
            "Clusters found : " + str(clusters) + "\n"
            "People labeled : " + str(people))

    def status(self, msg):
        try:
            self.status_var.set("  " + str(msg))
            self.root.update_idletasks()
        except:
            pass

    def _open_file(self, path):
        try:
            os.startfile(path)
        except:
            try:
                import subprocess
                subprocess.Popen(["explorer", "/select,", path])
            except:
                pass


# ─── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app  = App(root)
    root.mainloop()
