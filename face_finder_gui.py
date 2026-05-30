#!/usr/bin/env python3
"""
Local Face Finder - GUI Application
Desktop application for face recognition and photo organization
"""

import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path
from PIL import Image, ImageTk
import threading

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from image_scanner import ImageScanner
from face_recognizer import FaceRecognizer
from face_clustering import FaceClusterer
from face_database import FaceDatabase


class FaceFinderApp:
    """Main application window"""
    
    def __init__(self, root):
        """Initialize the application"""
        self.root = root
        self.root.title("Local Face Finder")
        self.root.geometry("1200x800")
        
        # Initialize components
        self.scanner = ImageScanner()
        self.recognizer = FaceRecognizer()
        self.clusterer = None
        self.database = FaceDatabase()
        
        # State variables
        self.scanned_images = []
        self.current_cluster = None
        self.current_images = []
        
        # Setup UI
        self._create_menu()
        self._create_main_layout()
        self._create_status_bar()
        
        # Load existing data if available
        self._load_existing_data()

    
    def _create_menu(self):
        """Create menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Scan Directory...", command=self.scan_directory)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        
        # Process menu
        process_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Process", menu=process_menu)
        process_menu.add_command(label="Detect Faces", command=self.detect_faces)
        process_menu.add_command(label="Cluster Faces", command=self.cluster_faces)
        
        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="View All Clusters", command=self.view_clusters)
        view_menu.add_command(label="View All People", command=self.view_people)
        view_menu.add_command(label="Statistics", command=self.show_statistics)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)

    
    def _create_main_layout(self):
        """Create main application layout"""
        # Main container
        main_container = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left panel - People/Clusters list
        left_panel = ttk.Frame(main_container, width=250)
        main_container.add(left_panel, weight=1)
        
        # Search box
        search_frame = ttk.Frame(left_panel)
        search_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace('w', self.on_search)
        ttk.Entry(search_frame, textvariable=self.search_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # Listbox for people/clusters
        list_frame = ttk.Frame(left_panel)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.people_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set)
        self.people_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.people_listbox.bind('<<ListboxSelect>>', self.on_person_select)
        scrollbar.config(command=self.people_listbox.yview)
        
        # Right panel - Image grid and details
        right_panel = ttk.Frame(main_container)
        main_container.add(right_panel, weight=4)

        
        # Toolbar
        toolbar = ttk.Frame(right_panel)
        toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Button(toolbar, text="Scan Directory", command=self.scan_directory).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Detect Faces", command=self.detect_faces).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Cluster Faces", command=self.cluster_faces).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Label Cluster", command=self.label_cluster).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Export Images", command=self.export_images).pack(side=tk.LEFT, padx=2)
        
        # Canvas for image grid (with scrollbar)
        canvas_frame = ttk.Frame(right_panel)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        canvas_scrollbar_y = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
        canvas_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        
        canvas_scrollbar_x = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
        canvas_scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.image_canvas = tk.Canvas(
            canvas_frame,
            yscrollcommand=canvas_scrollbar_y.set,
            xscrollcommand=canvas_scrollbar_x.set,
            bg='#f0f0f0'
        )
        self.image_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        canvas_scrollbar_y.config(command=self.image_canvas.yview)
        canvas_scrollbar_x.config(command=self.image_canvas.xview)
        
        # Inner frame for images
        self.images_frame = ttk.Frame(self.image_canvas)
        self.image_canvas.create_window((0, 0), window=self.images_frame, anchor=tk.NW)
        
        self.images_frame.bind('<Configure>', self._on_frame_configure)

    
    def _create_status_bar(self):
        """Create status bar"""
        self.status_bar = ttk.Label(
            self.root,
            text="Ready",
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    
    def _on_frame_configure(self, event=None):
        """Update scroll region when frame changes"""
        self.image_canvas.configure(scrollregion=self.image_canvas.bbox("all"))
    
    def set_status(self, message):
        """Update status bar"""
        self.status_bar.config(text=message)
        self.root.update_idletasks()
    
    def _load_existing_data(self):
        """Load existing face data from database"""
        stats = self.database.get_database_statistics()
        if stats['num_faces'] > 0:
            self.set_status(f"Loaded: {stats['num_faces']} faces, {stats['num_people']} people")
            self.refresh_people_list()
    
    def scan_directory(self):
        """Scan a directory for images"""
        directory = filedialog.askdirectory(title="Select Directory to Scan")
        if not directory:
            return
        
        self.set_status("Scanning directory...")
        
        def scan_thread():
            try:
                self.scanned_images = self.scanner.scan_directory(directory, recursive=True)
                self.root.after(0, lambda: self._scan_complete())
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", f"Scan failed: {str(e)}"))
        
        threading.Thread(target=scan_thread, daemon=True).start()

    
    def _scan_complete(self):
        """Called when scanning is complete"""
        num_images = len(self.scanned_images)
        self.set_status(f"Scan complete: {num_images} images found")
        messagebox.showinfo("Scan Complete", f"Found {num_images} images")
    
    def detect_faces(self):
        """Detect faces in scanned images"""
        if not self.scanned_images:
            messagebox.showwarning("No Images", "Please scan a directory first")
            return
        
        self.set_status("Detecting faces...")
        
        def detect_thread():
            try:
                scan_id = self.database.add_scan_session(self.scanner.scanned_files[0] if self.scanner.scanned_files else "")
                
                # Process images
                face_count = self.recognizer.process_images(
                    self.scanned_images,
                    save_face_crops=True,
                    face_crop_dir='data/face_crops'
                )
                
                # Save to database
                for face in self.recognizer.faces_data:
                    image_id = self.database.add_image(face['image_path'], scan_id=scan_id)
                    self.database.add_face(face, image_id)
                
                self.database.update_scan_session(scan_id, len(self.scanned_images), face_count)
                
                self.root.after(0, lambda: self._detection_complete(face_count))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", f"Detection failed: {str(e)}"))
        
        threading.Thread(target=detect_thread, daemon=True).start()
    
    def _detection_complete(self, face_count):
        """Called when detection is complete"""
        self.set_status(f"Detection complete: {face_count} faces found")
        messagebox.showinfo("Detection Complete", f"Found {face_count} faces")

    
    def cluster_faces(self):
        """Cluster detected faces"""
        if not self.recognizer.faces_data:
            messagebox.showwarning("No Faces", "Please detect faces first")
            return
        
        self.set_status("Clustering faces...")
        
        def cluster_thread():
            try:
                self.clusterer = FaceClusterer(self.recognizer, tolerance=0.6, min_cluster_size=2)
                clusters = self.clusterer.cluster_faces_dbscan()
                
                # Update database
                for face in self.recognizer.faces_data:
                    self.database.update_face_cluster(face['face_id'], face['cluster_id'])
                
                self.root.after(0, lambda: self._clustering_complete(len(clusters)))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", f"Clustering failed: {str(e)}"))
        
        threading.Thread(target=cluster_thread, daemon=True).start()
    
    def _clustering_complete(self, num_clusters):
        """Called when clustering is complete"""
        self.set_status(f"Clustering complete: {num_clusters} clusters found")
        messagebox.showinfo("Clustering Complete", f"Found {num_clusters} clusters")
        self.refresh_people_list()

    
    def refresh_people_list(self):
        """Refresh the list of people and clusters"""
        self.people_listbox.delete(0, tk.END)
        
        # Get all people from database
        people_stats = self.database.get_all_people_statistics()
        for person in people_stats:
            self.people_listbox.insert(
                tk.END,
                f"{person['person_name']} ({person['image_count']} photos)"
            )
        
        # Get unlabeled clusters
        unlabeled = self.database.get_unlabeled_clusters()
        if unlabeled:
            self.people_listbox.insert(tk.END, "--- Unlabeled Clusters ---")
            for cluster in unlabeled[:20]:  # Show first 20
                self.people_listbox.insert(
                    tk.END,
                    f"[Cluster] {cluster['cluster_id']} ({cluster['num_images']} photos)"
                )
    
    def on_person_select(self, event):
        """Called when a person/cluster is selected"""
        selection = self.people_listbox.curselection()
        if not selection:
            return
        
        item = self.people_listbox.get(selection[0])
        
        if item == "--- Unlabeled Clusters ---":
            return
        
        # Parse selection
        if item.startswith("[Cluster]"):
            # Unlabeled cluster selected
            cluster_id = item.split()[1]
            self.show_cluster_images(cluster_id)
        else:
            # Person selected
            person_name = item.split(" (")[0]
            self.show_person_images(person_name)

    
    def show_person_images(self, person_name):
        """Show all images containing a specific person"""
        self.set_status(f"Loading images for {person_name}...")
        images = self.database.search_images_by_person(person_name)
        self.current_images = [img['file_path'] for img in images]
        self.display_image_grid(self.current_images, f"Photos of {person_name}")
    
    def show_cluster_images(self, cluster_id):
        """Show all images in a cluster"""
        self.current_cluster = cluster_id
        self.set_status(f"Loading images for {cluster_id}...")
        
        faces = self.database.get_faces_in_cluster(cluster_id)
        image_paths = list(set(face['file_path'] for face in faces))
        self.current_images = image_paths
        self.display_image_grid(image_paths, f"Cluster: {cluster_id}")
    
    def display_image_grid(self, image_paths, title="Images"):
        """Display images in a grid"""
        # Clear existing images
        for widget in self.images_frame.winfo_children():
            widget.destroy()
        
        if not image_paths:
            ttk.Label(self.images_frame, text="No images to display").pack()
            self.set_status("No images")
            return
        
        # Display images in grid
        cols = 4
        for i, image_path in enumerate(image_paths[:100]):  # Limit to 100 images
            try:
                # Load and resize image
                img = Image.open(image_path)
                img.thumbnail((200, 200))
                photo = ImageTk.PhotoImage(img)
                
                # Create image button
                row = i // cols
                col = i % cols
                
                btn = tk.Button(
                    self.images_frame,
                    image=photo,
                    command=lambda p=image_path: self.open_image(p)
                )
                btn.image = photo  # Keep a reference
                btn.grid(row=row, column=col, padx=5, pady=5)
                
            except Exception as e:
                print(f"Error loading {image_path}: {e}")
        
        self.set_status(f"{title}: {len(image_paths)} images")
        self._on_frame_configure()

    
    def label_cluster(self):
        """Label the currently selected cluster"""
        if not self.current_cluster:
            messagebox.showwarning("No Cluster", "Please select an unlabeled cluster first")
            return
        
        # Ask for person name
        name = tk.simpledialog.askstring(
            "Label Cluster",
            f"Enter name for {self.current_cluster}:",
            parent=self.root
        )
        
        if name:
            # Update database
            self.database.update_cluster_person(self.current_cluster, name)
            self.database.add_person(name)
            
            # Update in-memory data
            if self.clusterer:
                self.clusterer.assign_name_to_cluster(self.current_cluster, name)
            
            messagebox.showinfo("Success", f"Labeled {self.current_cluster} as '{name}'")
            self.refresh_people_list()
            self.current_cluster = None
    
    def export_images(self):
        """Export images of selected person"""
        selection = self.people_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a person first")
            return
        
        item = self.people_listbox.get(selection[0])
        if item.startswith("[Cluster]") or item == "--- Unlabeled Clusters ---":
            messagebox.showwarning("Cannot Export", "Please label the cluster first")
            return
        
        person_name = item.split(" (")[0]
        
        # Ask for destination directory
        dest_dir = filedialog.askdirectory(title=f"Export photos of {person_name}")
        if not dest_dir:
            return
        
        # Export images
        self.export_person_images(person_name, dest_dir)

    
    def export_person_images(self, person_name, dest_dir):
        """Export all images of a person to a directory"""
        import shutil
        
        image_paths = self.database.export_person_images(person_name)
        dest_path = Path(dest_dir) / person_name.replace(" ", "_")
        dest_path.mkdir(parents=True, exist_ok=True)
        
        for img_path in image_paths:
            try:
                shutil.copy2(img_path, dest_path / Path(img_path).name)
            except Exception as e:
                print(f"Error copying {img_path}: {e}")
        
        messagebox.showinfo(
            "Export Complete",
            f"Exported {len(image_paths)} images of {person_name} to:\n{dest_path}"
        )
    
    def open_image(self, image_path):
        """Open an image in default viewer"""
        import os
        import platform
        
        if platform.system() == 'Darwin':  # macOS
            os.system(f'open "{image_path}"')
        elif platform.system() == 'Windows':
            os.startfile(image_path)
        else:  # Linux
            os.system(f'xdg-open "{image_path}"')
    
    def on_search(self, *args):
        """Filter people list by search query"""
        query = self.search_var.get().lower()
        
        self.people_listbox.delete(0, tk.END)
        
        # Get all people
        people_stats = self.database.get_all_people_statistics()
        
        for person in people_stats:
            if query in person['person_name'].lower():
                self.people_listbox.insert(
                    tk.END,
                    f"{person['person_name']} ({person['image_count']} photos)"
                )

    
    def view_clusters(self):
        """View all clusters"""
        clusters = self.database.get_all_clusters()
        
        window = tk.Toplevel(self.root)
        window.title("All Clusters")
        window.geometry("600x400")
        
        # Create treeview
        tree = ttk.Treeview(window, columns=('Faces', 'Images', 'Person'), show='tree headings')
        tree.heading('#0', text='Cluster ID')
        tree.heading('Faces', text='Faces')
        tree.heading('Images', text='Images')
        tree.heading('Person', text='Person')
        
        tree.column('#0', width=200)
        tree.column('Faces', width=100)
        tree.column('Images', width=100)
        tree.column('Person', width=150)
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(window, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Populate tree
        for cluster in clusters:
            person = cluster.get('person_name') or "Unlabeled"
            tree.insert('', 'end', text=cluster['cluster_id'],
                       values=(cluster['num_faces'], cluster['num_images'], person))

    
    def view_people(self):
        """View all identified people"""
        people_stats = self.database.get_all_people_statistics()
        
        window = tk.Toplevel(self.root)
        window.title("All People")
        window.geometry("500x400")
        
        # Create treeview
        tree = ttk.Treeview(window, columns=('Faces', 'Images'), show='tree headings')
        tree.heading('#0', text='Name')
        tree.heading('Faces', text='Faces')
        tree.heading('Images', text='Images')
        
        tree.column('#0', width=250)
        tree.column('Faces', width=100)
        tree.column('Images', width=100)
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(window, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Populate tree
        for person in people_stats:
            tree.insert('', 'end', text=person['person_name'],
                       values=(person['face_count'], person['image_count']))
    
    def show_statistics(self):
        """Show database statistics"""
        stats = self.database.get_database_statistics()
        
        msg = f"""Database Statistics:
        
Images: {stats['num_images']}
Faces: {stats['num_faces']}
Labeled Faces: {stats['num_labeled_faces']}
Unlabeled Faces: {stats['num_unlabeled_faces']}
People: {stats['num_people']}
Clusters: {stats['num_clusters']}"""
        
        messagebox.showinfo("Statistics", msg)
    
    def show_about(self):
        """Show about dialog"""
        about_text = """Local Face Finder
Version 1.0

A desktop application for face recognition
and photo organization.

Features:
- Scan local directories for images
- Detect and cluster faces automatically  
- Label people and search photos
- Export photos by person"""
        
        messagebox.showinfo("About", about_text)


def main():
    """Main entry point"""
    root = tk.Tk()
    app = FaceFinderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
