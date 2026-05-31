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

    def move_image_to_cluster(self, image_path, from_cluster_id, to_cluster_id):
        """Move all faces of an image from one cluster to another. to_cluster_id=-1 means unassign."""
        img_row = self.conn.execute("SELECT id FROM images WHERE path=?", (image_path,)).fetchone()
        if not img_row:
            return
        img_id = img_row["id"]
        if to_cluster_id == -1:
            # Unassign — just set cluster_id to -1
            self.conn.execute(
                "UPDATE faces SET cluster_id=-1, person_name='' WHERE image_id=? AND cluster_id=?",
                (img_id, from_cluster_id))
        else:
            name_row = self.conn.execute("SELECT person_name FROM clusters WHERE id=?",
                                         (to_cluster_id,)).fetchone()
            name = name_row["person_name"] if name_row else ""
            self.conn.execute(
                "UPDATE faces SET cluster_id=?, person_name=? WHERE image_id=? AND cluster_id=?",
                (to_cluster_id, name, img_id, from_cluster_id))
            self.conn.execute("INSERT OR IGNORE INTO clusters (id, person_name) VALUES (?,?)",
                              (to_cluster_id, name))
        self.conn.commit()

    def get_next_cluster_id(self):
        """Get the next available cluster ID (max + 1)."""
        row = self.conn.execute("SELECT MAX(cluster_id) FROM faces").fetchone()
        return (row[0] or 0) + 1
        # Returns path + the crop_path of the first detected face in that image
        return self.conn.execute("""
            SELECT i.path,
                   (SELECT f2.crop_path FROM faces f2
                    WHERE f2.image_id=i.id AND f2.cluster_id=?
                    AND f2.crop_path!='' LIMIT 1) as face_crop
            FROM faces f
            JOIN images i ON f.image_id=i.id
            WHERE f.cluster_id=?
            GROUP BY i.path
            ORDER BY i.id
        """, (cluster_id, cluster_id)).fetchall()

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

    # ── Loading overlay ──────────────────────────────────────────────────────
    def show_loading(self, message="Please wait..."):
        """Show a full-window loading overlay so user knows work is happening."""
        self._loading_win = tk.Toplevel(self.root)
        self._loading_win.overrideredirect(True)  # no title bar
        self._loading_win.configure(bg=BG2)
        # Center over main window
        self.root.update_idletasks()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        rx, ry = self.root.winfo_x(), self.root.winfo_y()
        w, h = 380, 140
        x = rx + (rw - w) // 2
        y = ry + (rh - h) // 2
        self._loading_win.geometry(str(w) + "x" + str(h) + "+" + str(x) + "+" + str(y))
        self._loading_win.grab_set()
        # Content
        tk.Frame(self._loading_win, bg=BORDER, height=2).pack(fill=tk.X)
        inner = tk.Frame(self._loading_win, bg=BG2, padx=20, pady=20)
        inner.pack(fill=tk.BOTH, expand=True)
        self._loading_msg_var = tk.StringVar(value=message)
        tk.Label(inner, textvariable=self._loading_msg_var,
                 bg=BG2, fg=ACCENT, font=("Segoe UI", 11, "bold")).pack(pady=(0, 10))
        self._loading_bar = ttk.Progressbar(inner, mode="indeterminate", length=320)
        self._loading_bar.pack()
        self._loading_bar.start(12)
        tk.Frame(self._loading_win, bg=BORDER, height=2).pack(fill=tk.X)
        self._loading_win.update()

    def update_loading(self, message):
        """Update the loading overlay message."""
        try:
            self._loading_msg_var.set(message)
            self._loading_win.update()
        except:
            pass

    def hide_loading(self):
        """Destroy the loading overlay."""
        try:
            self._loading_bar.stop()
            self._loading_win.grab_release()
            self._loading_win.destroy()
        except:
            pass

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

    # ── Google Photos helpers ─────────────────────────────────────────────────

    def _ensure_playwright(self, log_fn):
        import subprocess, sys
        try:
            import playwright
        except ImportError:
            log_fn("Installing playwright...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "playwright", "--quiet"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
            except Exception as e:
                log_fn("pip install playwright failed: " + str(e))
                return False
        try:
            log_fn("Installing Chromium browser (one-time ~100MB)...")
            subprocess.check_call(
                [sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        except Exception as e:
            log_fn("Chromium install note: " + str(e)[:60])
        return True

    def _playwright_fetch_album(self, url, log_fn):
        from playwright.sync_api import sync_playwright
        import re, time

        log_fn("Opening album in headless browser...")
        image_urls = set()

        with sync_playwright() as p:
            # Use a large viewport — Google Photos loads more thumbnails in a wider window
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080}
            )
            page = context.new_page()

            # Intercept ALL network responses — grab every lh3 CDN URL
            def handle_response(response):
                try:
                    req_url = response.url
                    if "lh3.googleusercontent.com" in req_url:
                        base = re.sub(r'[=?].*$', '', req_url)
                        if len(base) > 55:
                            image_urls.add(base)
                except:
                    pass

            page.on("response", handle_response)

            log_fn("Loading album page...")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except:
                pass

            # Wait longer for JS to fully render the album grid
            time.sleep(5)

            log_fn("Scrolling to load all photos...")

            # ── Smart infinite scroll ──────────────────────────────────────
            # Stop only after 10 consecutive rounds with zero new images
            # This handles slow network and large albums correctly
            no_new_count = 0
            max_no_new   = 10         # 10 empty rounds = definitely finished
            round_num    = 0
            max_rounds   = 600        # safety cap for huge albums (1000+ photos)

            def scrape_dom():
                """Grab all visible img src + data-src from the DOM directly."""
                try:
                    srcs = page.evaluate("""
                        () => {
                            const imgs = document.querySelectorAll('img');
                            return Array.from(imgs).map(i =>
                                i.src || i.getAttribute('data-src') || ''
                            ).filter(s => s.includes('lh3.googleusercontent.com'));
                        }
                    """)
                    for src in (srcs or []):
                        base = re.sub(r'[=?].*$', '', src)
                        if len(base) > 55:
                            image_urls.add(base)
                except:
                    pass

            while no_new_count < max_no_new and round_num < max_rounds:
                before = len(image_urls)

                # Scroll down using multiple methods to trigger all lazy loaders
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(0.3)
                page.keyboard.press("End")
                time.sleep(0.3)
                page.mouse.wheel(0, 5000)
                time.sleep(0.3)

                scrape_dom()

                # Give network requests time to fire and complete
                try:
                    page.wait_for_load_state("networkidle", timeout=4000)
                except:
                    pass

                # Extra wait every 10 rounds to let slow connections catch up
                if round_num % 10 == 0 and round_num > 0:
                    time.sleep(1.5)

                after = len(image_urls)
                if after == before:
                    no_new_count += 1
                else:
                    no_new_count = 0  # found new ones — reset counter

                round_num += 1

                if after > 0 and round_num % 5 == 0:
                    log_fn("Found " + str(after) + " photos, scrolling... (round " + str(round_num) + ")")

            # Final thorough DOM scrape
            scrape_dom()

            log_fn("Finished! Total photos found: " + str(len(image_urls)))
            browser.close()

        return list(image_urls)

    def _gphoto_get_credentials(self, log_fn):
        pass

    def _gphoto_list_album_items(self, creds, album_id_or_url, log_fn):
        pass

    # ── Import from Google Photos — Main Dialog ───────────────────────────────
    def import_google_photos(self):
        """
        Playwright headless browser opens the public shared album,
        intercepts image URLs, downloads at full resolution.
        Works for any public photos.app.goo.gl link — no login needed.
        """
        win = tk.Toplevel(self.root)
        win.title("Import Google Photos Album")
        win.geometry("620x400")
        win.resizable(False, False)
        win.configure(bg=BG2)
        win.grab_set()

        tk.Label(win, text="Import Google Photos Album",
                 bg=BG2, fg=ACCENT, font=("Segoe UI", 14, "bold")).pack(pady=(16, 2))
        tk.Label(win, text="Works with any PUBLIC shared album — no login or API key needed.",
                 bg=BG2, fg=MUTED, font=("Segoe UI", 9)).pack()
        tk.Frame(win, bg=BORDER, height=1).pack(fill=tk.X, padx=20, pady=10)

        uf = tk.Frame(win, bg=BG2)
        uf.pack(fill=tk.X, padx=20, pady=4)
        tk.Label(uf, text="Shared album URL:", bg=BG2, fg=TEXT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        url_var = tk.StringVar()
        url_entry = ttk.Entry(uf, textvariable=url_var, width=68, font=("Segoe UI", 9))
        url_entry.pack(fill=tk.X, pady=(2, 0))
        url_entry.focus()
        tk.Label(uf, text="e.g. https://photos.app.goo.gl/ABC123",
                 bg=BG2, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")

        sf = tk.Frame(win, bg=BG2)
        sf.pack(fill=tk.X, padx=20, pady=8)
        tk.Label(sf, text="Save photos to:", bg=BG2, fg=TEXT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        sf2 = tk.Frame(sf, bg=BG2)
        sf2.pack(fill=tk.X)
        save_dir_var = tk.StringVar(value=str(DATA_DIR / "google_photos"))
        ttk.Entry(sf2, textvariable=save_dir_var, width=58,
                  font=("Segoe UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True)

        def pick_folder():
            d = filedialog.askdirectory(title="Choose save folder",
                                        initialdir=save_dir_var.get())
            if d:
                save_dir_var.set(d)

        tk.Button(sf2, text="Browse", command=pick_folder,
                  bg=BTN_BG, fg=TEXT, relief="flat", padx=8, pady=4,
                  font=("Segoe UI", 9), cursor="hand2", bd=0,
                  activebackground=BTN_HOV).pack(side=tk.LEFT, padx=(6, 0))

        tk.Frame(win, bg=BORDER, height=1).pack(fill=tk.X, padx=20, pady=8)

        info_var   = tk.StringVar(value="Click 'Check Album' to count photos before downloading.")
        status_var = tk.StringVar(value="")
        tk.Label(win, textvariable=info_var, bg=BG2, fg=TEXT,
                 font=("Segoe UI", 9), justify="left").pack(padx=20, anchor="w")
        status_lbl = tk.Label(win, textvariable=status_var, bg=BG2, fg=MUTED, font=("Segoe UI", 8))
        status_lbl.pack(padx=20, anchor="w", pady=(2, 0))

        pbar_frame = tk.Frame(win, bg=BG2)
        pbar_frame.pack(fill=tk.X, padx=20, pady=4)
        pbar = ttk.Progressbar(pbar_frame, mode="determinate", length=570)
        pbar_lbl = tk.Label(pbar_frame, text="", bg=BG2, fg=MUTED, font=("Segoe UI", 8))

        tk.Frame(win, bg=BORDER, height=1).pack(fill=tk.X, padx=20, pady=(4, 0))
        btn_row = tk.Frame(win, bg=BG2)
        btn_row.pack(pady=8)
        BS = {"relief": "flat", "padx": 12, "pady": 7, "font": ("Segoe UI", 9, "bold"),
              "cursor": "hand2", "bd": 0}

        check_btn = tk.Button(btn_row, text="Check Album",
                              bg=ACCENT2, fg="#fffdf9", activebackground=ACCENT, **BS)
        check_btn.pack(side=tk.LEFT, padx=4)
        dl_btn = tk.Button(btn_row, text="Download & Detect Faces",
                           bg=GREEN, fg="#fffdf9", activebackground="#4a7a4a",
                           state="disabled", **BS)
        dl_btn.pack(side=tk.LEFT, padx=4)
        tk.Button(btn_row, text="Cancel", command=win.destroy,
                  bg=BTN_BG, fg=TEXT, relief="flat", padx=12, pady=7,
                  font=("Segoe UI", 9), cursor="hand2", bd=0,
                  activebackground=BTN_HOV).pack(side=tk.LEFT, padx=4)
        tk.Label(win, text="First run installs Playwright + Chromium (~100MB, one-time only)",
                 bg=BG2, fg=MUTED, font=("Segoe UI", 8)).pack(pady=(0, 6))

        album = {"urls": []}

        def set_info(msg):
            info_var.set(msg)
            win.update_idletasks()

        def set_status(msg, color=MUTED):
            status_var.set(msg)
            status_lbl.config(fg=color)
            win.update_idletasks()

        def check_album():
            url = url_var.get().strip()
            if not url:
                set_status("Please paste an album URL.", RED)
                return
            if "photos.app.goo.gl" not in url and "photos.google.com" not in url:
                set_status("Not a valid Google Photos link.", RED)
                return
            check_btn.config(state="disabled", text="Checking...")
            dl_btn.config(state="disabled")
            pbar.pack_forget()
            pbar_lbl.pack_forget()
            set_info("Installing Playwright and loading album...")
            set_status("May take 1-2 min on first run (installs ~100MB Chromium).", YELLOW)

            def run():
                try:
                    if not self._ensure_playwright(
                            lambda m: self.root.after(0, lambda msg=m: set_status(msg, YELLOW))):
                        self.root.after(0, lambda: set_status("Playwright install failed.", RED))
                        self.root.after(0, lambda: check_btn.config(
                            state="normal", text="Check Album"))
                        return
                    urls = self._playwright_fetch_album(
                        url,
                        lambda m: self.root.after(0, lambda msg=m: set_status(msg, MUTED))
                    )
                    if not urls:
                        self.root.after(0, lambda: set_info(
                            "No photos found.\n\n"
                            "Make sure the album is set to PUBLIC:\n"
                            "  Google Photos app → Album → Share\n"
                            "  → Turn on 'Anyone with the link can view'"))
                        self.root.after(0, lambda: set_status("Album not accessible.", RED))
                        self.root.after(0, lambda: check_btn.config(
                            state="normal", text="Check Album"))
                        return
                    album["urls"] = urls
                    count  = len(urls)
                    est_mb = round(count * 3.5, 1)
                    sz_str = (str(round(est_mb/1024, 2)) + " GB") if est_mb > 1024 else (str(est_mb) + " MB")
                    msg = ("Album ready!\n\n"
                           "   Photos found   :  " + str(count) + " images\n"
                           "   Estimated size :  " + sz_str + "  (~3.5 MB/photo)\n"
                           "   Save location  :  " + save_dir_var.get())
                    self.root.after(0, lambda: set_info(msg))
                    self.root.after(0, lambda: set_status(
                        "Ready! Click Download & Detect Faces.", GREEN))
                    self.root.after(0, lambda: dl_btn.config(state="normal"))
                    self.root.after(0, lambda: check_btn.config(
                        state="normal", text="Re-Check"))
                except Exception as e:
                    self.root.after(0, lambda: set_status("Error: " + str(e)[:120], RED))
                    self.root.after(0, lambda: check_btn.config(
                        state="normal", text="Check Album"))

            threading.Thread(target=run, daemon=True).start()

        check_btn.config(command=check_album)

        def start_download():
            urls  = album["urls"]
            count = len(urls)
            if count == 0:
                set_status("Check album first.", RED)
                return
            save_dir = Path(save_dir_var.get().strip())
            est_mb   = round(count * 3.5, 1)
            sz_str   = (str(round(est_mb/1024, 2)) + " GB") if est_mb > 1024 else (str(est_mb) + " MB")
            confirmed = messagebox.askyesno(
                "Confirm Download",
                "Download " + str(count) + " photos (" + sz_str + ")?\n"
                "Save to: " + str(save_dir) + "\n\n"
                "Face detection starts automatically after download.\nProceed?",
                parent=win
            )
            if not confirmed:
                return
            save_dir.mkdir(parents=True, exist_ok=True)
            check_btn.config(state="disabled")
            dl_btn.config(state="disabled", text="Downloading...")
            pbar.config(maximum=count, value=0)
            pbar.pack(fill=tk.X, pady=(4, 0))
            pbar_lbl.config(text="Starting download...")
            pbar_lbl.pack(anchor="w")

            def run():
                try:
                    import requests as rlib
                    headers = {"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0"}
                    saved = 0
                    total_bytes = 0
                    for i, base_url in enumerate(urls):
                        try:
                            r = rlib.get(base_url + "=d", headers=headers, timeout=60)
                            r.raise_for_status()
                            ct  = r.headers.get("Content-Type", "image/jpeg")
                            ext = (".jpg" if "jpeg" in ct else
                                   ".png" if "png"  in ct else
                                   ".webp" if "webp" in ct else ".jpg")
                            out = save_dir / ("photo_" + str(i+1).zfill(4) + ext)
                            out.write_bytes(r.content)
                            self.db.add_image(str(out))
                            saved += 1
                            total_bytes += len(r.content)
                        except:
                            pass
                        done = i + 1
                        rem  = count - done
                        mb   = round(total_bytes / 1024 / 1024, 1)
                        def upd(d=done, r2=rem, m=mb):
                            try:
                                pbar["value"] = d
                                pbar_lbl.config(text=(
                                    str(d) + " / " + str(count) +
                                    "   |   " + str(r2) + " remaining" +
                                    "   |   " + str(m) + " MB downloaded"))
                                set_status("Downloading " + str(d) + " of " + str(count) + "...", MUTED)
                            except:
                                pass
                        self.root.after(0, upd)
                    self.root.after(0, lambda: self._gphoto_done(win, saved, auto_detect=True))
                except Exception as e:
                    self.root.after(0, lambda: set_status("Error: " + str(e)[:100], RED))
                    self.root.after(0, lambda: dl_btn.config(
                        state="normal", text="Download & Detect Faces"))

            threading.Thread(target=run, daemon=True).start()

        dl_btn.config(command=start_download)

        def set_info(msg):
            info_var.set(msg)
            win.update_idletasks()

        def set_status(msg, color=MUTED):
            status_var.set(msg)
            status_lbl.config(fg=color)
            win.update_idletasks()

        # ────────────────────────────────────────────────────────────────────
        # Helper: install gallery-dl once
        # ────────────────────────────────────────────────────────────────────
        def ensure_gallery_dl():
            """Install gallery-dl if not present. Returns True on success."""
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "gallery_dl", "--version"],
                    capture_output=True, timeout=15
                )
                return result.returncode == 0
            except:
                pass
            try:
                self.root.after(0, lambda: set_status("Installing gallery-dl (one time)...", YELLOW))
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "gallery-dl", "--quiet"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120
                )
                return True
            except:
                return False

        # ────────────────────────────────────────────────────────────────────
        # STEP 1 — CHECK ALBUM INFO using gallery-dl --dump-json (no download)
        # gallery-dl is the ONLY reliable way to get Google Photos album info
        # because the page is JS-rendered — requests.get() returns empty HTML
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
            set_status("Google Photos uses JavaScript — using gallery-dl to read album...", MUTED)
            pbar.pack_forget()
            pbar_lbl.pack_forget()

            def run():
                try:
                    if not ensure_gallery_dl():
                        self.root.after(0, lambda: set_status(
                            "gallery-dl install failed. Check your internet connection.", RED))
                        self.root.after(0, lambda: fetch_btn.config(
                            state="normal", text="Check Album"))
                        return

                    # Use gallery-dl --dump-json to list URLs without downloading
                    self.root.after(0, lambda: set_status("Fetching album contents...", MUTED))
                    result = subprocess.run(
                        [sys.executable, "-m", "gallery_dl",
                         "--dump-json",      # list files without downloading
                         "--no-download",
                         url],
                        capture_output=True, text=True, timeout=60
                    )

                    lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
                    # gallery-dl outputs JSON lines — count image entries
                    count = sum(1 for l in lines if '"url"' in l or l.startswith("http"))

                    # Fallback: count lines that look like image paths
                    if count == 0:
                        count = sum(1 for l in lines if any(
                            ext in l.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]
                        ))

                    # If still 0, try a simpler line count of stdout
                    if count == 0 and lines:
                        count = len(lines)

                    album["count"] = count

                    if count == 0:
                        err_out = (result.stderr or "")[:300]
                        hint = ""
                        if "403" in err_out or "unauthorized" in err_out.lower():
                            hint = "Album is set to private. Set it to 'Anyone with link can view'."
                        elif "404" in err_out:
                            hint = "Album not found. Check the URL is correct."
                        else:
                            hint = "Could not read album. Make sure it is a public shared album."
                        self.root.after(0, lambda h=hint: set_info(
                            "No photos found.\n\n" + h))
                        self.root.after(0, lambda: set_status("", RED))
                        self.root.after(0, lambda: fetch_btn.config(
                            state="normal", text="Check Album"))
                        return

                    est_mb = round(count * 3.5, 1)
                    sz_str = (str(round(est_mb/1024, 2)) + " GB") if est_mb > 1024 else (str(est_mb) + " MB")
                    album["est_mb"] = est_mb

                    msg = (
                        "Album found!\n\n"
                        "   Photos found    :  " + str(count) + " images\n"
                        "   Estimated size  :  " + sz_str + "  (~3.5 MB per photo)\n"
                        "   Save location   :  " + save_dir_var.get()
                    )
                    self.root.after(0, lambda: set_info(msg))
                    self.root.after(0, lambda: set_status(
                        "Ready. Click 'Download & Detect Faces' to proceed.", GREEN))
                    self.root.after(0, lambda: download_btn.config(state="normal"))
                    self.root.after(0, lambda: fetch_btn.config(
                        state="normal", text="Re-Check"))

                except subprocess.TimeoutExpired:
                    self.root.after(0, lambda: set_status(
                        "Timeout connecting to album. Check your internet.", RED))
                    self.root.after(0, lambda: fetch_btn.config(
                        state="normal", text="Check Album"))
                except Exception as e:
                    self.root.after(0, lambda: set_status("Error: " + str(e)[:100], RED))
                    self.root.after(0, lambda: fetch_btn.config(
                        state="normal", text="Check Album"))

            threading.Thread(target=run, daemon=True).start()

        fetch_btn.config(command=check_album)

        # ────────────────────────────────────────────────────────────────────
        # STEP 2 — DOWNLOAD with gallery-dl + live file-count progress + auto detect
        # ────────────────────────────────────────────────────────────────────
        def start_download():
            count  = album["count"]
            est_mb = album["est_mb"]
            sz_str = (str(round(est_mb/1024, 2)) + " GB") if est_mb > 1024 else (str(est_mb) + " MB")

            if count == 0:
                set_status("Click 'Check Album' first.", RED)
                return

            url      = url_var.get().strip()
            save_dir = Path(save_dir_var.get().strip())

            # ── Confirmation dialog ──────────────────────────────────────────
            confirmed = messagebox.askyesno(
                "Confirm Download",
                "You are about to download:\n\n"
                "   Photos    :  " + str(count) + " images\n"
                "   Est. size :  " + sz_str + "\n"
                "   Save to   :  " + str(save_dir) + "\n\n"
                "Face detection will start automatically\n"
                "after download completes.\n\nProceed?",
                parent=win
            )
            if not confirmed:
                return

            save_dir.mkdir(parents=True, exist_ok=True)
            fetch_btn.config(state="disabled")
            download_btn.config(state="disabled", text="Downloading...")

            pbar.config(maximum=max(count, 1), value=0, mode="determinate")
            pbar.pack(fill=tk.X, pady=(4, 0))
            pbar_lbl.config(text="Starting gallery-dl download...")
            pbar_lbl.pack(anchor="w")
            set_info("Downloading photos to:\n" + str(save_dir))

            def run():
                try:
                    # Run gallery-dl — it downloads directly, no auth needed for public albums
                    proc = subprocess.Popen(
                        [sys.executable, "-m", "gallery_dl",
                         "--dest",     str(save_dir),
                         "--no-mtime",
                         url],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True
                    )

                    downloaded = 0
                    for line in proc.stdout:
                        line = line.strip()
                        # gallery-dl prints a line for each downloaded file
                        if line and ("Downloading" in line or ".jpg" in line.lower()
                                     or ".jpeg" in line.lower() or ".png" in line.lower()):
                            downloaded += 1
                            done = downloaded
                            rem  = max(0, count - done)
                            def upd(d=done, r=rem):
                                try:
                                    pbar["value"] = d
                                    pbar_lbl.config(text=(
                                        str(d) + " downloaded"
                                        + ("   |   " + str(r) + " remaining" if r > 0 else "   |   Done!")
                                    ))
                                    set_status("Downloading... " + str(d) + " photos saved.", MUTED)
                                except:
                                    pass
                            self.root.after(0, upd)

                    proc.wait()

                    # Count what was actually saved
                    saved_files = [f for f in save_dir.rglob("*")
                                   if f.is_file() and f.suffix.lower() in SUPPORTED]

                    if not saved_files:
                        self.root.after(0, lambda: set_status(
                            "No files saved. gallery-dl may have failed.", RED))
                        self.root.after(0, lambda: download_btn.config(
                            state="normal", text="Download & Detect Faces"))
                        return

                    for f in saved_files:
                        self.db.add_image(str(f))

                    n = len(saved_files)
                    self.root.after(0, lambda: self._gphoto_done(win, n, auto_detect=True))

                except Exception as e:
                    err = str(e)[:120]
                    self.root.after(0, lambda: set_status("Download error: " + err, RED))
                    self.root.after(0, lambda: download_btn.config(
                        state="normal", text="Download & Detect Faces"))

            threading.Thread(target=run, daemon=True).start()

        download_btn.config(command=start_download)

    def _gphoto_clear_token(self):
        pass  # kept for compatibility

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
        self.show_loading("Clearing old data...")
        self.db.reset_scanned()
        for f in CROP_DIR.iterdir():
            try:
                f.unlink()
            except:
                pass
        self.face_thumb_cache.clear()
        self.refresh_cluster_list()
        self.hide_loading()
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
        self.show_loading("Clustering " + str(len(rows)) + " faces...\nThis may take a moment.")
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
        self.hide_loading()
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
                     bg=BG, fg=MUTED, font=("Segoe UI", 10)).grid(
                row=0, column=0, padx=30, pady=40)
            return

        COLS     = 5
        THUMB    = 200
        FACE_SZ  = 56

        # ── Selection state for multi-select move ────────────────────────────
        selected_paths = set()

        # ── Action bar (shown above grid) ────────────────────────────────────
        action_bar = tk.Frame(self.grid_frame, bg=BG, pady=4)
        action_bar.grid(row=0, column=0, columnspan=COLS, sticky="ew", padx=8, pady=(0, 4))
        tk.Label(action_bar,
                 text="Right-click or Ctrl+Click a photo to move/remove it from this cluster",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        sel_lbl = tk.Label(action_bar, text="", bg=BG, fg=ACCENT2,
                           font=("Segoe UI", 8, "bold"))
        sel_lbl.pack(side=tk.LEFT, padx=10)

        def update_sel_label():
            n = len(selected_paths)
            if n > 0:
                sel_lbl.config(text=str(n) + " selected  —  right-click to move/remove")
            else:
                sel_lbl.config(text="")

        def build_context_menu(path, canv, card):
            menu = tk.Menu(self.root, tearoff=0, bg=CARD, fg=TEXT,
                           activebackground=BTN_HOV, activeforeground=TEXT,
                           font=("Segoe UI", 9))
            menu.add_command(label="Open photo",
                             command=lambda: self._open_file(path))
            menu.add_separator()
            menu.add_command(label="Move to New Cluster",
                             command=lambda: self._move_photos_to_new_cluster(
                                 selected_paths if selected_paths else {path},
                                 cluster_id))
            menu.add_command(label="Move to Existing Cluster...",
                             command=lambda: self._move_photos_to_existing_cluster(
                                 selected_paths if selected_paths else {path},
                                 cluster_id))
            menu.add_separator()
            menu.add_command(label="Remove from this cluster (unassign)",
                             command=lambda: self._remove_photos_from_cluster(
                                 selected_paths if selected_paths else {path},
                                 cluster_id))
            return menu

        def toggle_select(path, canv, card, overlay_id):
            if path in selected_paths:
                selected_paths.discard(path)
                canv.itemconfig(overlay_id, state="hidden")
                card.configure(bg=CARD)
            else:
                selected_paths.add(path)
                canv.itemconfig(overlay_id, state="normal")
                card.configure(bg=BTN_HOV)
            update_sel_label()

        for idx, row in enumerate(rows):
            path      = row["path"]
            face_crop = row["face_crop"] if row["face_crop"] else None
            r, c = divmod(idx, COLS)

            card = tk.Frame(self.grid_frame, bg=CARD, padx=4, pady=4)
            card.grid(row=r + 1, column=c, padx=8, pady=8)  # +1 for action_bar row

            try:
                img = Image.open(path)
                img.thumbnail((THUMB, THUMB))
                photo = ImageTk.PhotoImage(img)
                self.photo_cache[path] = photo

                canv = tk.Canvas(card, width=photo.width(), height=photo.height(),
                                 bg=CARD, highlightthickness=0, cursor="hand2")
                canv.pack()
                canv.create_image(0, 0, anchor="nw", image=photo)

                # Blue selection overlay (hidden by default)
                overlay_id = canv.create_rectangle(
                    0, 0, photo.width(), photo.height(),
                    fill=ACCENT, outline="", stipple="gray25", state="hidden")

                # Checkmark shown when selected
                check_id = canv.create_text(
                    photo.width() - 12, 12,
                    text="✓", fill="#fffdf9",
                    font=("Segoe UI", 14, "bold"), state="hidden")

                # Left-click → open; Ctrl+Click → select/deselect
                def on_click(e, p=path, cv=canv, cd=card, ov=overlay_id, ck=check_id):
                    if e.state & 0x0004:  # Ctrl held
                        if p in selected_paths:
                            selected_paths.discard(p)
                            cv.itemconfig(ov, state="hidden")
                            cv.itemconfig(ck, state="hidden")
                            cd.configure(bg=CARD)
                        else:
                            selected_paths.add(p)
                            cv.itemconfig(ov, state="normal")
                            cv.itemconfig(ck, state="normal")
                            cd.configure(bg=BTN_HOV)
                        update_sel_label()
                    else:
                        self._open_file(p)

                def on_right_click(e, p=path, cv=canv, cd=card):
                    menu = build_context_menu(p, cv, cd)
                    menu.tk_popup(e.x_root, e.y_root)

                canv.bind("<Button-1>", on_click)
                canv.bind("<Button-3>", on_right_click)  # Right-click

                # Face crop badge top-right
                if face_crop and Path(face_crop).exists():
                    try:
                        fc_img = Image.open(face_crop).resize((FACE_SZ, FACE_SZ), Image.LANCZOS)
                        bordered = Image.new("RGB", (FACE_SZ + 4, FACE_SZ + 4), ACCENT2)
                        bordered.paste(fc_img, (2, 2))
                        fc_photo = ImageTk.PhotoImage(bordered)
                        canv._face_photo = fc_photo
                        bx = photo.width() - (FACE_SZ + 4) - 4
                        canv.create_image(bx, 4, anchor="nw", image=fc_photo)
                        canv.create_rectangle(bx - 2, FACE_SZ + 8,
                                              bx + (FACE_SZ + 6), FACE_SZ + 22,
                                              fill=ACCENT2, outline="")
                        canv.create_text(bx + (FACE_SZ // 2) + 2, FACE_SZ + 15,
                                         text="face", fill="#fffdf9",
                                         font=("Segoe UI", 7, "bold"))
                    except:
                        pass

            except:
                tk.Label(card, text="Error loading", bg=CARD, fg=RED).pack()

            fname = Path(path).name
            if len(fname) > 22:
                fname = fname[:20] + "..."
            tk.Label(card, text=fname, bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack()

        self.status("Showing " + str(len(rows)) + " photos for " + label +
                    "  |  Ctrl+Click to select  |  Right-click for options")

    # ── Remove / Move photos between clusters ─────────────────────────────────
    def _move_photos_to_new_cluster(self, paths, from_cluster_id):
        """Move selected photos to a brand-new cluster."""
        if not paths:
            return
        new_id = self.db.get_next_cluster_id()
        for path in paths:
            self.db.move_image_to_cluster(path, from_cluster_id, new_id)
        self.face_thumb_cache.clear()
        self.refresh_cluster_list()
        self._show_cluster_photos(from_cluster_id)
        self.status("Moved " + str(len(paths)) + " photo(s) to new Cluster " + str(new_id))
        messagebox.showinfo("Done",
                            "Moved " + str(len(paths)) + " photo(s) to a new cluster!\n"
                            "You can find it in the left panel as Cluster " + str(new_id))

    def _move_photos_to_existing_cluster(self, paths, from_cluster_id):
        """Show a picker to choose which existing cluster to move photos to."""
        if not paths:
            return
        clusters = self.db.get_clusters()
        if not clusters:
            messagebox.showinfo("No Clusters", "No other clusters exist yet.")
            return

        win = tk.Toplevel(self.root)
        win.title("Move to Cluster")
        win.geometry("420x480")
        win.configure(bg=BG2)
        win.grab_set()

        tk.Label(win, text="Move " + str(len(paths)) + " photo(s) to:",
                 bg=BG2, fg=ACCENT, font=("Segoe UI", 12, "bold")).pack(pady=(14, 4))
        tk.Label(win, text="Click a cluster to move selected photos into it.",
                 bg=BG2, fg=MUTED, font=("Segoe UI", 9)).pack(pady=(0, 8))

        lf = tk.Frame(win, bg=BG2)
        lf.pack(fill=tk.BOTH, expand=True, padx=14)

        scroll_canvas = tk.Canvas(lf, bg=BG2, highlightthickness=0)
        sb = tk.Scrollbar(lf, orient=tk.VERTICAL, command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = tk.Frame(scroll_canvas, bg=BG2)
        scroll_canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: scroll_canvas.configure(
            scrollregion=scroll_canvas.bbox("all")))

        def do_move(target_id):
            for path in paths:
                self.db.move_image_to_cluster(path, from_cluster_id, target_id)
            self.face_thumb_cache.clear()
            self.refresh_cluster_list()
            self._show_cluster_photos(from_cluster_id)
            win.destroy()
            self.status("Moved " + str(len(paths)) + " photo(s) to Cluster " + str(target_id))

        for row in clusters:
            cid  = row["cluster_id"]
            if cid == from_cluster_id:
                continue
            name = row["person_name"] or ("Cluster " + str(cid))
            photo = self._get_face_thumb(cid)
            rf = tk.Frame(inner, bg=CARD, pady=4, cursor="hand2")
            rf.pack(fill=tk.X, padx=4, pady=2)
            if photo:
                c = tk.Canvas(rf, width=48, height=48, bg=CARD, highlightthickness=0)
                c.pack(side=tk.LEFT, padx=(6, 4))
                c.create_image(0, 0, anchor="nw", image=photo)
                c.image = photo
            txt = tk.Frame(rf, bg=CARD)
            txt.pack(side=tk.LEFT, fill=tk.X)
            tk.Label(txt, text=name, bg=CARD, fg=TEXT,
                     font=("Segoe UI", 10, "bold")).pack(anchor="w")
            tk.Label(txt, text=str(row["photo_count"]) + " photos",
                     bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
            for w in [rf, txt] + list(txt.winfo_children()):
                w.bind("<Button-1>", lambda e, ci=cid: do_move(ci))
                w.bind("<Enter>", lambda e, f=rf: f.configure(bg=BTN_HOV))
                w.bind("<Leave>", lambda e, f=rf: f.configure(bg=CARD))
            tk.Frame(inner, bg=BORDER, height=1).pack(fill=tk.X, padx=4)

        tk.Button(win, text="Cancel", command=win.destroy,
                  bg=BTN_BG, fg=TEXT, relief="flat", padx=14, pady=7,
                  font=("Segoe UI", 9), cursor="hand2", bd=0,
                  activebackground=BTN_HOV).pack(pady=8)

    def _remove_photos_from_cluster(self, paths, from_cluster_id):
        """Remove photos from cluster (set cluster_id to -1 = unassigned)."""
        if not paths:
            return
        if not messagebox.askyesno("Remove from Cluster",
                                   "Remove " + str(len(paths)) + " photo(s) from this cluster?\n"
                                   "They will become unassigned (not deleted)."):
            return
        for path in paths:
            self.db.move_image_to_cluster(path, from_cluster_id, -1)
        self.face_thumb_cache.clear()
        self.refresh_cluster_list()
        self._show_cluster_photos(from_cluster_id)
        self.status("Removed " + str(len(paths)) + " photo(s) from cluster.")



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
