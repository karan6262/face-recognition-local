#!/usr/bin/env python3
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

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "faces.db"
CROP_DIR = DATA_DIR / "face_crops"
THUMB_DIR = DATA_DIR / "thumbnails"
for d in [DATA_DIR, CROP_DIR, THUMB_DIR]:
    d.mkdir(parents=True, exist_ok=True)
SUPPORTED = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}



class DB:
    def __init__(self):
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE,
                scanned INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS faces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id INTEGER,
                crop_path TEXT,
                embedding TEXT,
                cluster_id INTEGER DEFAULT -1,
                person_name TEXT DEFAULT '',
                face_index INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS clusters (
                id INTEGER PRIMARY KEY,
                person_name TEXT DEFAULT ''
            );
        """)
        self.conn.commit()

    def add_image(self, path):
        try:
            self.conn.execute("INSERT OR IGNORE INTO images (path) VALUES (?)", (str(path),))
            self.conn.commit()
            row = self.conn.execute("SELECT id FROM images WHERE path=?", (str(path),)).fetchone()
            return row[0]
        except:
            return None

    def add_face(self, image_id, crop_path, embedding, face_index):
        self.conn.execute(
            "INSERT INTO faces (image_id, crop_path, embedding, face_index) VALUES (?,?,?,?)",
            (image_id, str(crop_path), json.dumps(embedding), face_index)
        )
        self.conn.commit()


    def get_all_faces(self):
        return self.conn.execute(
            "SELECT f.*, i.path as image_path FROM faces f JOIN images i ON f.image_id=i.id"
        ).fetchall()

    def update_face_cluster(self, face_id, cluster_id):
        self.conn.execute("UPDATE faces SET cluster_id=? WHERE id=?", (cluster_id, face_id))
        self.conn.commit()

    def update_cluster_name(self, cluster_id, name):
        self.conn.execute("INSERT OR REPLACE INTO clusters (id, person_name) VALUES (?,?)", (cluster_id, name))
        self.conn.execute("UPDATE faces SET person_name=? WHERE cluster_id=?", (name, cluster_id))
        self.conn.commit()

    def merge_clusters(self, keep_id, merge_id):
        row = self.conn.execute("SELECT person_name FROM clusters WHERE id=?", (keep_id,)).fetchone()
        name = row["person_name"] if row else ""
        self.conn.execute(
            "UPDATE faces SET cluster_id=?, person_name=? WHERE cluster_id=?",
            (keep_id, name, merge_id)
        )
        self.conn.execute("DELETE FROM clusters WHERE id=?", (merge_id,))
        self.conn.commit()

    def get_clusters(self):
        return self.conn.execute("""
            SELECT f.cluster_id,
                   COALESCE(c.person_name,'') as person_name,
                   COUNT(DISTINCT f.id) as face_count,
                   COUNT(DISTINCT f.image_id) as photo_count
            FROM faces f
            LEFT JOIN clusters c ON f.cluster_id = c.id
            WHERE f.cluster_id >= 0
            GROUP BY f.cluster_id
            ORDER BY face_count DESC
        """).fetchall()

    def get_first_crop(self, cluster_id):
        row = self.conn.execute(
            "SELECT crop_path FROM faces WHERE cluster_id=? AND crop_path != '' LIMIT 1",
            (cluster_id,)
        ).fetchone()
        return row["crop_path"] if row else None

    def get_images_for_cluster(self, cluster_id):
        return self.conn.execute("""
            SELECT DISTINCT i.path FROM faces f
            JOIN images i ON f.image_id = i.id
            WHERE f.cluster_id = ?
        """, (cluster_id,)).fetchall()


    def get_stats(self):
        images = self.conn.execute("SELECT COUNT(*) FROM images WHERE scanned=1").fetchone()[0]
        faces = self.conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0]
        people = self.conn.execute("SELECT COUNT(DISTINCT person_name) FROM faces WHERE person_name != ''").fetchone()[0]
        clusters = self.conn.execute("SELECT COUNT(DISTINCT cluster_id) FROM faces WHERE cluster_id >= 0").fetchone()[0]
        return images, faces, people, clusters

    def mark_scanned(self, image_id):
        self.conn.execute("UPDATE images SET scanned=1 WHERE id=?", (image_id,))
        self.conn.commit()

    def reset_scanned(self):
        self.conn.execute("UPDATE images SET scanned=0")
        self.conn.execute("DELETE FROM faces")
        self.conn.execute("DELETE FROM clusters")
        self.conn.commit()

    def clear_all(self):
        self.conn.executescript("""
            DELETE FROM faces;
            DELETE FROM images;
            DELETE FROM clusters;
        """)
        self.conn.commit()



class FaceEngine:
    def __init__(self, log_fn=None):
        self.log = log_fn or print
        self._load()

    def _load(self):
        try:
            from deepface import DeepFace
            import numpy as np
            import cv2
            self.DeepFace = DeepFace
            self.np = np
            self.cv2 = cv2
            self.log("DeepFace loaded OK")
        except ImportError as e:
            self.log("ERROR DeepFace not installed: " + str(e))
            raise

    def detect_and_encode(self, image_path):
        results = []
        try:
            faces = self.DeepFace.represent(
                img_path=str(image_path),
                model_name="Facenet",
                enforce_detection=True,
                detector_backend="opencv"
            )
            img = self.cv2.imread(str(image_path))
            if img is None:
                return results
            h, w = img.shape[:2]
            for i, fd in enumerate(faces):
                emb = fd["embedding"]
                reg = fd.get("facial_area", {})
                x = reg.get("x", 0)
                y = reg.get("y", 0)
                fw = reg.get("w", 100)
                fh = reg.get("h", 100)
                p = 20
                x1 = max(0, x - p)
                y1 = max(0, y - p)
                x2 = min(w, x + fw + p)
                y2 = min(h, y + fh + p)
                crop = img[y1:y2, x1:x2]
                results.append((emb, crop, i))
        except Exception as e:
            msg = str(e)
            if "Face could not be detected" not in msg:
                self.log("SKIP " + Path(image_path).name + " " + msg)
        return results

    def cluster_embeddings(self, embeddings, tolerance=0.45):
        import numpy as np
        if not embeddings:
            return []
        arr = np.array(embeddings)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1
        arr = arr / norms
        n = len(arr)
        labels = [-1] * n
        cid = 0
        for i in range(n):
            if labels[i] != -1:
                continue
            labels[i] = cid
            for j in range(i + 1, n):
                if labels[j] != -1:
                    continue
                if float(np.linalg.norm(arr[i] - arr[j])) < tolerance:
                    labels[j] = cid
            cid += 1
        return labels



class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Local Face Finder")
        self.root.geometry("1280x820")
        self.root.configure(bg="#1e1e2e")
        self.db = DB()
        self.engine = None
        self.photo_cache = {}
        self.face_thumb_cache = {}
        self.selected_cluster = None
        self._build_ui()
        self._load_engine_async()

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#1e1e2e")
        style.configure("TLabel", background="#1e1e2e", foreground="#cdd6f4")
        style.configure("TButton", background="#313244", foreground="#cdd6f4", padding=6)
        style.configure("Treeview", background="#181825", foreground="#cdd6f4",
                        fieldbackground="#181825", rowheight=52)
        style.configure("Treeview.Heading", background="#313244", foreground="#cdd6f4")
        style.configure("TScrollbar", background="#313244")
        style.configure("TEntry", fieldbackground="#313244", foreground="#cdd6f4")
        tb = ttk.Frame(self.root, padding=8)
        tb.pack(fill=tk.X)
        ttk.Button(tb, text="Scan Folder", command=self.scan_folder).pack(side=tk.LEFT, padx=4)
        ttk.Button(tb, text="Detect Faces", command=self.detect_faces).pack(side=tk.LEFT, padx=4)
        ttk.Button(tb, text="Re-Detect All", command=self.redetect_faces).pack(side=tk.LEFT, padx=4)
        ttk.Button(tb, text="Cluster Faces", command=self.cluster_faces).pack(side=tk.LEFT, padx=4)
        ttk.Button(tb, text="Merge Clusters", command=self.merge_clusters_popup).pack(side=tk.LEFT, padx=4)
        ttk.Button(tb, text="Clear All Data", command=self.clear_data).pack(side=tk.LEFT, padx=4)
        ttk.Button(tb, text="Statistics", command=self.show_stats).pack(side=tk.LEFT, padx=4)
        self.status_var = tk.StringVar(value="Starting...")
        tk.Label(self.root, textvariable=self.status_var, bg="#313244", fg="#a6e3a1",
                 anchor="w", padx=10, pady=5, font=("Segoe UI", 9)).pack(fill=tk.X, side=tk.BOTTOM)
        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill=tk.X, side=tk.BOTTOM)
        pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        left = ttk.Frame(pane, width=300)
        pane.add(left, weight=1)
        self._build_left(left)
        right = ttk.Frame(pane)
        pane.add(right, weight=4)
        self._build_right(right)


    def _build_left(self, parent):
        ttk.Label(parent, text="People and Clusters",
                  font=("Segoe UI", 11, "bold")).pack(pady=(8, 2))
        sf = ttk.Frame(parent)
        sf.pack(fill=tk.X, padx=6, pady=4)
        ttk.Label(sf, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh_cluster_list())
        ttk.Entry(sf, textvariable=self.search_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, padx=6)
        self.tree = ttk.Treeview(frame, columns=("face", "name", "photos"),
                                 show="headings", selectmode="extended")
        self.tree.heading("face", text="")
        self.tree.heading("name", text="Name / Cluster")
        self.tree.heading("photos", text="Pics")
        self.tree.column("face", width=52, anchor="center", stretch=False)
        self.tree.column("name", width=160)
        self.tree.column("photos", width=40, anchor="center")
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_cluster_select)
        bf = ttk.Frame(parent)
        bf.pack(fill=tk.X, padx=6, pady=8)
        ttk.Button(bf, text="Label Selected", command=self.label_cluster).pack(fill=tk.X, pady=2)
        ttk.Button(bf, text="Merge Selected (Ctrl+Click)", command=self.merge_selected).pack(fill=tk.X, pady=2)
        ttk.Button(bf, text="Export Photos", command=self.export_photos).pack(fill=tk.X, pady=2)

    def _build_right(self, parent):
        self.panel_title = ttk.Label(parent, text="Select a cluster to view photos",
                                     font=("Segoe UI", 11, "bold"))
        self.panel_title.pack(pady=8)
        cf = ttk.Frame(parent)
        cf.pack(fill=tk.BOTH, expand=True)
        vscroll = ttk.Scrollbar(cf, orient=tk.VERTICAL)
        vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        hscroll = ttk.Scrollbar(cf, orient=tk.HORIZONTAL)
        hscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas = tk.Canvas(cf, bg="#181825",
                                yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vscroll.config(command=self.canvas.yview)
        hscroll.config(command=self.canvas.xview)
        self.grid_frame = ttk.Frame(self.canvas)
        self.canvas_win = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>",
                             lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self.canvas_win, width=e.width))
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))


    def _load_engine_async(self):
        self.status("Loading AI engine... first launch downloads models 300MB")
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

    def scan_folder(self):
        folder = filedialog.askdirectory(title="Select folder containing photos")
        if not folder:
            return
        images = [str(p) for p in Path(folder).rglob("*") if p.suffix.lower() in SUPPORTED]
        if not images:
            messagebox.showinfo("No Images", "No supported images found.")
            return
        for path in images:
            self.db.add_image(path)
        count = str(len(images))
        self.status("Found " + count + " images. Click Detect Faces.")
        messagebox.showinfo("Done", "Found " + count + " images. Now click Detect Faces.")

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

    def _open_scan_popup(self, total):
        popup = tk.Toplevel(self.root)
        popup.title("Scanning Photos")
        popup.geometry("520x440")
        popup.resizable(False, False)
        popup.configure(bg="#1e1e2e")
        tk.Label(popup, text="Scanning Photos for Faces", bg="#1e1e2e", fg="#89b4fa",
                 font=("Segoe UI", 13, "bold")).pack(pady=(16, 4))
        pf = tk.Frame(popup, bg="#313244", width=200, height=200)
        pf.pack(pady=4)
        pf.pack_propagate(False)
        preview_label = tk.Label(pf, bg="#313244", text="Loading...")
        preview_label.place(relx=0.5, rely=0.5, anchor="center")
        fname_var = tk.StringVar(value="Starting...")
        tk.Label(popup, textvariable=fname_var, bg="#1e1e2e", fg="#cdd6f4",
                 font=("Segoe UI", 9), wraplength=480).pack(pady=(4, 1))
        counter_var = tk.StringVar(value="0 / " + str(total))
        tk.Label(popup, textvariable=counter_var, bg="#1e1e2e", fg="#a6e3a1",
                 font=("Segoe UI", 10, "bold")).pack(pady=1)
        faces_var = tk.StringVar(value="Faces found: 0")
        tk.Label(popup, textvariable=faces_var, bg="#1e1e2e", fg="#f9e2af",
                 font=("Segoe UI", 9)).pack(pady=1)
        pbar = ttk.Progressbar(popup, mode="determinate", maximum=total, length=460)
        pbar.pack(pady=8, padx=20)
        return popup, preview_label, fname_var, counter_var, faces_var, pbar


    def detect_faces(self):
        if not self.engine:
            messagebox.showerror("Not Ready", "AI engine is still loading. Please wait.")
            return
        images = self.db.conn.execute("SELECT id, path FROM images WHERE scanned=0").fetchall()
        if not images:
            messagebox.showinfo("Nothing To Do", "No unscanned images. Scan a folder first or use Re-Detect All.")
            return
        total = len(images)
        if not messagebox.askyesno("Detect Faces", "Detect faces in " + str(total) + " images?"):
            return
        popup, preview_label, fname_var, counter_var, faces_var, pbar = self._open_scan_popup(total)
        def update_preview(img_path):
            try:
                img = Image.open(img_path)
                img.thumbnail((200, 200))
                photo = ImageTk.PhotoImage(img)
                preview_label.config(image=photo, text="")
                preview_label.image = photo
            except:
                preview_label.config(image="", text="Preview N/A")
        def run():
            found = 0
            n = len(images)
            for idx, row in enumerate(images):
                img_id = row[0]
                img_path = row[1]
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
                    crop_name = str(img_id) + "_" + str(fi) + ".jpg"
                    crop_path = CROP_DIR / crop_name
                    try:
                        import cv2
                        cv2.imwrite(str(crop_path), crop)
                    except:
                        pass
                    self.db.add_face(img_id, crop_path, emb, fi)
                    found += 1
                self.db.mark_scanned(img_id)
                f2 = found
                def upd(x=f2):
                    try:
                        faces_var.set("Faces found: " + str(x))
                    except:
                        pass
                self.root.after(0, upd)
            self.root.after(0, lambda: self._detect_done(found, popup))
        threading.Thread(target=run, daemon=True).start()

    def _detect_done(self, found, popup=None):
        if popup:
            try:
                popup.destroy()
            except:
                pass
        self.progress.stop()
        self.status("Done! Found " + str(found) + " faces. Click Cluster Faces.")
        messagebox.showinfo("Done", "Found " + str(found) + " faces. Now click Cluster Faces.")


    def cluster_faces(self):
        if not self.engine:
            messagebox.showerror("Not Ready", "AI engine is still loading.")
            return
        rows = self.db.get_all_faces()
        if not rows:
            messagebox.showinfo("No Faces", "No faces found. Run Detect Faces first.")
            return
        tol = simpledialog.askfloat("Tolerance",
            "Enter tolerance (0.3=strict, 0.45=balanced, 0.6=loose)",
            initialvalue=0.45, minvalue=0.1, maxvalue=1.0, parent=self.root)
        if tol is None:
            return
        self.progress.start()
        self.status("Clustering faces...")
        def run():
            embs = [json.loads(r["embedding"]) for r in rows]
            labels = self.engine.cluster_embeddings(embs, tolerance=tol)
            for row, label in zip(rows, labels):
                self.db.update_face_cluster(row["id"], label)
            clusters = len(set(l for l in labels if l >= 0))
            self.root.after(0, lambda: self._cluster_done(clusters))
        threading.Thread(target=run, daemon=True).start()

    def _cluster_done(self, n):
        self.progress.stop()
        self.face_thumb_cache.clear()
        self.status("Found " + str(n) + " clusters. Select one on the left.")
        self.refresh_cluster_list()
        messagebox.showinfo("Done", "Found " + str(n) + " clusters. Select one on the left.")

    def _get_face_thumb(self, cluster_id):
        if cluster_id in self.face_thumb_cache:
            return self.face_thumb_cache[cluster_id]
        crop_path = self.db.get_first_crop(cluster_id)
        if crop_path and Path(crop_path).exists():
            try:
                img = Image.open(crop_path).resize((44, 44), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.face_thumb_cache[cluster_id] = photo
                return photo
            except:
                pass
        return None

    def refresh_cluster_list(self):
        self.tree.delete(*self.tree.get_children())
        query = self.search_var.get().lower()
        for row in self.db.get_clusters():
            cid = row["cluster_id"]
            name = row["person_name"] or ("Cluster " + str(cid))
            if query and query not in name.lower():
                continue
            tag = "named" if row["person_name"] else "unnamed"
            photo = self._get_face_thumb(cid)
            if photo:
                self.tree.insert("", "end", iid=str(cid), image=photo,
                                 values=("", name, row["photo_count"]), tags=(tag,))
                self.tree.item(str(cid), image=photo)
            else:
                self.tree.insert("", "end", iid=str(cid),
                                 values=("?", name, row["photo_count"]), tags=(tag,))
        self.tree.tag_configure("named", foreground="#a6e3a1")
        self.tree.tag_configure("unnamed", foreground="#f38ba8")

    def _on_cluster_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        self.selected_cluster = int(sel[0])
        self._show_cluster_photos(self.selected_cluster)


    def _show_cluster_photos(self, cluster_id):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.photo_cache.clear()
        name_row = self.db.conn.execute(
            "SELECT person_name FROM clusters WHERE id=?", (cluster_id,)).fetchone()
        label = (name_row["person_name"] if name_row and name_row["person_name"]
                 else "Cluster " + str(cluster_id))
        self.panel_title.config(text="Photos: " + label)
        rows = self.db.get_images_for_cluster(cluster_id)
        if not rows:
            ttk.Label(self.grid_frame, text="No photos found.").grid(row=0, column=0, padx=20, pady=20)
            return
        COLS = 5
        THUMB = 200
        for idx, row in enumerate(rows):
            path = row["path"]
            r, c = divmod(idx, COLS)
            frame = ttk.Frame(self.grid_frame, padding=4)
            frame.grid(row=r, column=c, padx=6, pady=6)
            try:
                img = Image.open(path)
                img.thumbnail((THUMB, THUMB))
                photo = ImageTk.PhotoImage(img)
                self.photo_cache[path] = photo
                tk.Button(frame, image=photo, bg="#313244", activebackground="#45475a",
                          relief="flat", cursor="hand2",
                          command=lambda p=path: self._open_file(p)).pack()
            except:
                ttk.Label(frame, text="Error").pack()
            fname = Path(path).name
            if len(fname) > 22:
                fname = fname[:20] + "..."
            ttk.Label(frame, text=fname, font=("Segoe UI", 8)).pack()
        self.status("Showing " + str(len(rows)) + " photos for " + label)

    def label_cluster(self):
        if self.selected_cluster is None:
            messagebox.showwarning("No Selection", "Select a cluster first.")
            return
        name = simpledialog.askstring("Label Person",
            "Enter name for Cluster " + str(self.selected_cluster) + ":",
            parent=self.root)
        if name and name.strip():
            self.db.update_cluster_name(self.selected_cluster, name.strip())
            self.face_thumb_cache.pop(self.selected_cluster, None)
            self.refresh_cluster_list()
            self.panel_title.config(text="Photos: " + name.strip())
            self.status("Labeled as: " + name.strip())

    def export_photos(self):
        if self.selected_cluster is None:
            messagebox.showwarning("No Selection", "Select a cluster first.")
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
        rows = self.db.get_images_for_cluster(self.selected_cluster)
        count = 0
        for row in rows:
            try:
                shutil.copy2(row["path"], out_dir / Path(row["path"]).name)
                count += 1
            except:
                pass
        messagebox.showinfo("Done", "Exported " + str(count) + " photos to " + str(out_dir))
        self.status("Exported " + str(count) + " photos.")


    def merge_clusters_popup(self):
        win = tk.Toplevel(self.root)
        win.title("Merge Clusters")
        win.geometry("500x520")
        win.configure(bg="#1e1e2e")
        win.grab_set()
        tk.Label(win, text="Merge Clusters", bg="#1e1e2e", fg="#89b4fa",
                 font=("Segoe UI", 13, "bold")).pack(pady=(14, 4))
        tk.Label(win, text="Ctrl+Click to select multiple, then click Merge.",
                 bg="#1e1e2e", fg="#cdd6f4", font=("Segoe UI", 9)).pack(pady=(0, 8))
        lf = ttk.Frame(win)
        lf.pack(fill=tk.BOTH, expand=True, padx=16, pady=4)
        mt = ttk.Treeview(lf, columns=("face", "name", "photos"),
                          show="headings", selectmode="extended")
        mt.heading("face", text="")
        mt.heading("name", text="Name / Cluster")
        mt.heading("photos", text="Pics")
        mt.column("face", width=52, anchor="center", stretch=False)
        mt.column("name", width=300)
        mt.column("photos", width=50, anchor="center")
        msb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=mt.yview)
        mt.configure(yscrollcommand=msb.set)
        mt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        msb.pack(side=tk.RIGHT, fill=tk.Y)
        for row in self.db.get_clusters():
            cid = row["cluster_id"]
            name = row["person_name"] or ("Cluster " + str(cid))
            photo = self._get_face_thumb(cid)
            if photo:
                mt.insert("", "end", iid=str(cid), image=photo,
                          values=("", name, row["photo_count"]))
                mt.item(str(cid), image=photo)
            else:
                mt.insert("", "end", iid=str(cid), values=("?", name, row["photo_count"]))
        name_var = tk.StringVar(value="")
        nf = ttk.Frame(win)
        nf.pack(fill=tk.X, padx=16, pady=6)
        tk.Label(nf, text="New name (optional):", bg="#1e1e2e", fg="#cdd6f4",
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        ttk.Entry(nf, textvariable=name_var, width=24).pack(side=tk.LEFT, padx=8)
        def do_merge():
            sel = mt.selection()
            if len(sel) < 2:
                messagebox.showwarning("Select More", "Select at least 2 clusters.", parent=win)
                return
            ids = [int(s) for s in sel]
            keep = ids[0]
            for mid in ids[1:]:
                self.db.merge_clusters(keep, mid)
            merged_name = name_var.get().strip()
            if merged_name:
                self.db.update_cluster_name(keep, merged_name)
            self.face_thumb_cache.clear()
            self.refresh_cluster_list()
            self.status("Merged " + str(len(ids)) + " clusters!")
            win.destroy()
            messagebox.showinfo("Done", "Merged " + str(len(ids)) + " clusters!")
        bf = ttk.Frame(win)
        bf.pack(pady=10)
        ttk.Button(bf, text="Merge Selected Clusters", command=do_merge).pack(side=tk.LEFT, padx=8)
        ttk.Button(bf, text="Cancel", command=win.destroy).pack(side=tk.LEFT, padx=8)

    def merge_selected(self):
        sel = self.tree.selection()
        if len(sel) < 2:
            messagebox.showwarning("Select More", "Ctrl+Click at least 2 clusters to merge.")
            return
        ids = [int(s) for s in sel]
        names = []
        for cid in ids:
            row = self.db.conn.execute(
                "SELECT person_name FROM clusters WHERE id=?", (cid,)).fetchone()
            names.append(row["person_name"] if row and row["person_name"] else "Cluster " + str(cid))
        if not messagebox.askyesno("Merge", "Merge these clusters?\n\n" + ", ".join(names)):
            return
        keep = ids[0]
        for mid in ids[1:]:
            self.db.merge_clusters(keep, mid)
        self.face_thumb_cache.clear()
        self.refresh_cluster_list()
        self.selected_cluster = keep
        self.status("Merged " + str(len(ids)) + " clusters.")
        messagebox.showinfo("Done", "Merged " + str(len(ids)) + " clusters!")


    def clear_data(self):
        if not messagebox.askyesno("Clear All Data",
                                   "Delete ALL face data? Photos will NOT be deleted."):
            return
        self.db.clear_all()
        for f in CROP_DIR.iterdir():
            try:
                f.unlink()
            except:
                pass
        self.face_thumb_cache.clear()
        self.selected_cluster = None
        self.refresh_cluster_list()
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.panel_title.config(text="Select a cluster to view photos")
        self.status("Cleared. Scan a folder to start fresh.")

    def show_stats(self):
        images, faces, people, clusters = self.db.get_stats()
        msg = ("Images scanned: " + str(images) + "\n"
               + "Faces detected: " + str(faces) + "\n"
               + "Clusters found: " + str(clusters) + "\n"
               + "People labeled: " + str(people))
        messagebox.showinfo("Statistics", msg)

    def status(self, msg):
        try:
            self.status_var.set(str(msg))
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


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
