# Local Face Finder

A powerful desktop application that scans images from your computer, recognizes faces, and organizes photos by person - all completely offline!

## 🌟 Features

- **📁 Local Scanning** - Scan any directory on your computer for images
- **👤 Face Detection** - Automatically detect faces using AI
- **🔄 Smart Clustering** - Group similar faces together automatically
- **🏷️ Easy Labeling** - Label face clusters with names
- **🔍 Search by Person** - Find all photos of a specific person instantly
- **📤 Export Photos** - Export all photos of a person to a folder
- **🖥️ Desktop GUI** - User-friendly graphical interface
- **🔒 Completely Offline** - No internet required, all processing local
- **💾 SQLite Database** - Fast searching and organization

## 📋 Prerequisites

- Python 3.7 or higher
- At least 2GB RAM (4GB+ recommended)
- For CNN model: GPU recommended (optional)

## 🚀 Quick Start

### 1. Installation

```bash
# Navigate to project directory
cd local-face-finder

# Install dependencies
pip install -r requirements.txt

# Note: If face_recognition fails to install, you may need:
# - macOS: brew install cmake
# - Ubuntu/Debian: sudo apt-get install cmake build-essential python3-dev
# - Windows: Install Visual Studio C++ Build Tools
```

### 2. Run the Application

```bash
# Launch the GUI
python face_finder_gui.py

# Or make it executable (Unix/Mac)
chmod +x face_finder_gui.py
./face_finder_gui.py
```

### 3. Basic Workflow

1. **Scan Directory** - Click "Scan Directory" and select your photos folder
2. **Detect Faces** - Click "Detect Faces" to find all faces
3. **Cluster Faces** - Click "Cluster Faces" to group similar faces
4. **Label Clusters** - Select a cluster, click "Label Cluster", enter name
5. **Browse Photos** - Click on a person's name to see all their photos
6. **Export** - Select a person and click "Export Images"

## 📖 Detailed Usage

### Scanning for Images

The application scans directories recursively for supported image formats:
- `.jpg`, `.jpeg` - JPEG images
- `.png` - PNG images
- `.bmp` - Bitmap images
- `.gif` - GIF images
- `.tiff` - TIFF images
- `.webp` - WebP images

### Face Detection

Two detection models available:

**HOG (Default)**
- Fast, works on CPU
- Good for clear frontal faces
- Recommended for most users
- ~0.5-1 second per image

**CNN**
- More accurate, handles difficult angles
- Requires GPU for speed
- Better for challenging photos
- ~2-5 seconds per image on CPU

### Face Clustering

Uses DBSCAN algorithm to automatically group similar faces:
- **Tolerance**: 0.6 (default)
  - Lower (0.4-0.5): Stricter, may split same person
  - Higher (0.7+): More forgiving, may merge different people
- **Min Cluster Size**: 2 faces minimum

### Labeling

1. Select an "[Cluster]" entry from the list
2. View the photos on the right
3. Click "Label Cluster"
4. Enter the person's name
5. The cluster becomes a named person

### Searching

Use the search box to filter people by name. Results update as you type.

### Exporting

1. Select a person from the list
2. Click "Export Images"
3. Choose destination folder
4. All photos of that person are copied there

## ⚙️ Configuration

Edit `.env` file to customize settings:

```bash
# Face Detection
FACE_DETECTION_MODEL=hog  # or 'cnn'
FACE_CLUSTERING_TOLERANCE=0.6  # 0.4-0.7
MIN_CLUSTER_SIZE=2

# Image Processing
MAX_IMAGE_SIZE=2000  # Resize large images for speed
THUMBNAIL_SIZE=200  # Thumbnail size in GUI
FACE_CROP_SIZE=150  # Face crop size

# Supported Formats
SUPPORTED_FORMATS=.jpg,.jpeg,.png,.bmp,.gif,.tiff,.webp
```

## 📁 Project Structure

```
local-face-finder/
├── face_finder_gui.py      # Main GUI application
├── config.py               # Configuration
├── requirements.txt        # Python dependencies
├── .env.example           # Configuration template
│
├── src/                   # Source modules
│   ├── image_scanner.py    # Scan directories
│   ├── face_recognizer.py  # Detect & encode faces
│   ├── face_clustering.py  # Cluster faces
│   └── face_database.py    # SQLite database
│
└── data/                  # Application data
    ├── faces.db           # SQLite database
    ├── face_crops/        # Cropped face images
    └── thumbnails/        # Image thumbnails
```

## 🎯 Use Cases

### Family Photo Organization
- Scan family photo albums
- Automatically find all photos of each family member
- Create personalized photo collections

### Event Photos
- Process photos from events/parties
- Quickly identify who appears in which photos
- Send each person their photos

### Photo Archive Management
- Organize large photo archives
- Find photos of specific people across years
- Rediscover forgotten photos

### Professional Use
- Organize client photo shoots
- Catalog portrait collections
- Manage team photos

## 🔧 Troubleshooting

### Installation Issues

**Problem**: `face_recognition` won't install
```bash
# macOS
brew install cmake
pip install face_recognition

# Ubuntu/Debian
sudo apt-get install cmake build-essential python3-dev
pip install face_recognition

# Windows
# Install Visual Studio C++ Build Tools
# Then: pip install face_recognition
```

**Problem**: `tkinter` not found
```bash
# Ubuntu/Debian
sudo apt-get install python3-tk

# macOS (should be included)
# If missing: brew install python-tk
```

### Detection Issues

**Problem**: No faces detected
- Ensure photos have clear, visible faces
- Try CNN model for better accuracy
- Check that images aren't corrupted

**Problem**: Detection is slow
- Use HOG model instead of CNN
- Reduce MAX_IMAGE_SIZE in config
- Process images in smaller batches

### Clustering Issues

**Problem**: Same person split into multiple clusters
- Increase FACE_CLUSTERING_TOLERANCE (try 0.65-0.7)
- Manually merge clusters after labeling

**Problem**: Different people grouped together
- Decrease FACE_CLUSTERING_TOLERANCE (try 0.5-0.55)
- Manually split clusters after detection

### GUI Issues

**Problem**: Images don't display
- Check that PIL/Pillow is installed
- Verify image files aren't corrupted
- Check file permissions

**Problem**: Application freezes
- This is normal during long operations
- Processing happens in background threads
- Wait for operation to complete

## 💡 Tips for Best Results

1. **Photo Quality**
   - Use clear, well-lit photos
   - Front-facing or slight angles work best
   - Avoid very small faces in images

2. **Clustering**
   - Start with default tolerance (0.6)
   - Adjust based on results
   - It's easier to merge clusters than split them

3. **Labeling**
   - Review cluster photos before labeling
   - Use consistent naming
   - Label largest clusters first

4. **Performance**
   - Close other applications during processing
   - Process large collections in batches
   - Use HOG model for faster processing

5. **Backups**
   - Backup `data/faces.db` regularly
   - Original images are never modified
   - Database can be recreated by re-scanning

## 🔒 Privacy & Security

- **100% Offline** - No data sent anywhere
- **Local Processing** - Everything runs on your computer
- **No Cloud** - No accounts, no uploads
- **Your Data** - You own and control everything
- **No Tracking** - No analytics or telemetry

## 📊 Performance

Typical performance on modern hardware:

| Task | HOG Model | CNN Model |
|------|-----------|-----------|
| Face Detection | 0.5-1 sec/image | 2-5 sec/image |
| Clustering (1000 faces) | ~2 seconds | ~2 seconds |
| Database Search | Instant | Instant |

## 🆘 Getting Help

1. Check this README for solutions
2. Review the Troubleshooting section
3. Check that all dependencies are installed
4. Verify your Python version (3.7+)

## 📝 Command Line Tools

Advanced users can use individual modules:

```bash
# Scan directory
python src/image_scanner.py /path/to/photos

# Detect faces
python src/face_recognizer.py /path/to/photos

# Cluster faces
python src/face_clustering.py

# Database operations
python src/face_database.py
```

## 🔄 Updating

To update the application:

```bash
# Pull latest changes (if using git)
git pull

# Update dependencies
pip install -r requirements.txt --upgrade
```

## 📄 License

This project is provided as-is for personal use.

## 🙏 Acknowledgments

Built using:
- [face_recognition](https://github.com/ageitgey/face_recognition) by Adam Geitgey
- [OpenCV](https://opencv.org/) for image processing
- [scikit-learn](https://scikit-learn.org/) for clustering
- [tkinter](https://docs.python.org/3/library/tkinter.html) for GUI
- [SQLite](https://www.sqlite.org/) for database

---

**Happy Face Finding! 📸✨**

Find all your photos instantly - no internet required, completely private!
