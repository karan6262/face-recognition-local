# Features - Local Face Finder

## 🎯 Core Features

### 1. Local Directory Scanning
- **Recursive Scanning** - Scan folders and all subfolders
- **Multiple Formats** - JPG, PNG, BMP, GIF, TIFF, WebP
- **Duplicate Detection** - Find duplicate images by hash
- **Statistics** - File counts, sizes, format breakdown
- **Fast Scanning** - Progress bars and efficient processing

### 2. Face Detection
- **Automatic Detection** - AI-powered face recognition
- **Two Detection Models**:
  - HOG: Fast, CPU-friendly, good accuracy
  - CNN: High accuracy, GPU-optimized, slower
- **Face Encoding** - 128-dimensional vectors for comparison
- **Face Crops** - Saves cropped face images for preview
- **Batch Processing** - Process hundreds of images
- **Progress Tracking** - Real-time progress updates

### 3. Face Clustering
- **DBSCAN Algorithm** - Automatically determines number of people
- **Hierarchical Clustering** - Alternative algorithm option
- **Adjustable Tolerance** - Fine-tune clustering strictness
- **Outlier Detection** - Handles faces that don't match clusters
- **Cluster Statistics** - Size, photo count for each cluster
- **Cluster Management**:
  - Merge clusters (combine split people)
  - Split clusters (separate merged people)
  - Rename clusters

### 4. Person Labeling
- **Interactive Labeling** - Easy name assignment
- **Preview Images** - See cluster photos before labeling
- **Bulk Labeling** - Label entire cluster at once
- **Name Management** - Edit, update person names
- **Unlabeled Tracking** - See which clusters need labels

### 5. Search & Browse
- **Search by Name** - Real-time search filtering
- **Browse by Person** - See all photos of one person
- **Browse by Cluster** - View unlabeled face groups
- **Image Grid View** - Thumbnail grid display
- **Click to Open** - Open images in default viewer
- **Fast Database** - Instant search results

### 6. Data Export
- **Export by Person** - Copy all photos of one person
- **Organized Folders** - Creates person-specific folders
- **Preserve Originals** - Never modifies source files
- **Batch Export** - Export multiple people at once
- **Shareable** - Ready to share with friends/family

### 7. Desktop GUI
- **User-Friendly Interface** - Clean, intuitive design
- **Left Panel** - People and cluster list
- **Right Panel** - Image grid view
- **Toolbar** - Quick access to common actions
- **Status Bar** - Operation feedback
- **Responsive** - Threading for smooth operation
- **Resizable** - Adjust window size
- **Cross-Platform** - Works on Windows, Mac, Linux

### 8. Database Storage
- **SQLite Database** - Fast, reliable storage
- **Organized Schema**:
  - Images table
  - Faces table
  - People table
  - Clusters table
  - Scans table
- **Indexed Queries** - Fast search operations
- **Data Persistence** - Save work between sessions
- **Statistics** - Track faces, people, images
- **Export Data** - Get lists of images by person

## 🔧 Technical Features

### Performance
- **Efficient Processing** - Optimized algorithms
- **Progress Tracking** - Know how long operations take
- **Background Threading** - GUI stays responsive
- **Image Resizing** - Handle large images efficiently
- **Batch Operations** - Process multiple items together

### Privacy & Security
- **100% Offline** - No internet required
- **No Cloud Storage** - Everything local
- **No Accounts** - No sign-up or login
- **No Tracking** - No analytics or telemetry
- **Your Data** - Complete control and ownership

### Configurability
- **Environment Variables** - Configure via .env file
- **Detection Model** - Choose HOG or CNN
- **Clustering Parameters** - Adjust tolerance
- **Image Size Limits** - Control processing speed
- **Thumbnail Sizes** - Customize display
- **Supported Formats** - Add/remove file types

### Reliability
- **Error Handling** - Graceful error recovery
- **File Validation** - Check images before processing
- **Database Integrity** - Foreign keys and constraints
- **Safe Operations** - Never modify originals
- **Backup Friendly** - Simple data folder structure

## 📊 Statistics & Reporting

### Database Statistics
- Total images scanned
- Total faces detected
- Labeled vs unlabeled faces
- Number of identified people
- Number of clusters
- Storage space used

### Person Statistics
- Face count per person
- Photo count per person
- Most/least photographed people
- Photos per cluster

### Scan History
- Track scanning sessions
- Date and location of scans
- Images and faces per scan
- Historical data

## 🎨 User Interface Features

### Main Window
- **Split Panel Layout** - List and grid view
- **Search Bar** - Filter people quickly
- **Toolbar** - Common actions accessible
- **Status Bar** - Real-time feedback
- **Menu Bar** - All features organized

### Image Display
- **Grid Layout** - Multiple images visible
- **Thumbnails** - Fast loading preview
- **Scrollable** - Handle many images
- **Click to View** - Open full resolution
- **Responsive Grid** - Adapts to window size

### Dialogs & Windows
- **Progress Dialogs** - Show operation status
- **Confirmation Dialogs** - Prevent accidents
- **Info Windows** - Statistics and details
- **File Choosers** - Select folders easily
- **Input Dialogs** - Enter names

## 🚀 Advanced Features

### Command Line Tools
- Run individual modules standalone
- Batch processing scripts
- Database queries
- Automation possibilities

### Module API
- Reusable Python modules
- Import into other projects
- Extend functionality
- Build custom tools

### Database Access
- Direct SQLite access
- SQL queries for analysis
- Data export options
- Integration with other tools

## 🔄 Future Enhancement Ideas

### Potential Features
- Video frame extraction
- Bulk rename operations
- Photo timeline view
- Advanced filters (date, location)
- Face comparison tool
- Similar face suggestions
- Tag management
- Notes per person
- Photo albums
- Slideshow mode

### Advanced Clustering
- Multiple clustering algorithms
- Manual cluster adjustment
- Confidence scores
- Face quality metrics
- Age grouping
- Photo quality filtering

### Enhanced UI
- Dark mode theme
- Customizable layouts
- Keyboard shortcuts
- Drag-and-drop
- Multi-select operations
- Context menus
- Preview pane

### Export Options
- Create photo albums
- Generate HTML galleries
- ZIP file export
- Cloud upload integration
- Social media export
- Print layouts

---

**All features designed with privacy, speed, and ease-of-use in mind!**
