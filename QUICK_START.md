# Quick Start Guide - Local Face Finder

Get started in 5 minutes!

## Step 1: Install (2 minutes)

```bash
cd local-face-finder
pip install -r requirements.txt
```

If installation fails, install system dependencies:
```bash
# macOS
brew install cmake

# Ubuntu/Linux  
sudo apt-get install cmake build-essential python3-dev python3-tk

# Windows
# Install Visual Studio C++ Build Tools from Microsoft
```

## Step 2: Launch (30 seconds)

```bash
python face_finder_gui.py
```

## Step 3: Use (3 minutes)

### A. Scan Your Photos
1. Click **"Scan Directory"** button
2. Select your photos folder
3. Wait for scan to complete

### B. Detect Faces
1. Click **"Detect Faces"** button
2. Wait for detection (shows progress)
3. See face count in status bar

### C. Cluster Faces
1. Click **"Cluster Faces"** button
2. Wait for clustering
3. See clusters in left panel

### D. Label People
1. Click on a **[Cluster]** entry
2. View photos on the right
3. Click **"Label Cluster"**
4. Type the person's name
5. Press Enter

### E. Browse Photos
1. Click on a person's name
2. See all their photos
3. Click any photo to open it

### F. Export Photos
1. Select a person
2. Click **"Export Images"**
3. Choose destination folder
4. Done!

## Example Workflow

```
1. Scan: /Users/you/Pictures  →  Found 500 images
2. Detect: Processing...      →  Found 1,234 faces
3. Cluster: Processing...     →  Found 15 clusters
4. Label: "John" "Mary" etc.  →  10 people identified
5. Search: Click "John"       →  Shows 45 photos
6. Export: Save to Desktop    →  John's photos copied
```

## Tips

✅ **Do:**
- Use clear, well-lit photos
- Start with a small folder to test
- Label largest clusters first
- Use HOG model (default) for speed

❌ **Don't:**
- Process 10,000+ photos at once (use batches)
- Use very dark or blurry photos
- Expect 100% accuracy on difficult photos
- Close the app during processing

## Keyboard Shortcuts

- `Ctrl+O` - Scan Directory (may need to add)
- `Ctrl+F` - Focus search box
- `Ctrl+Q` - Quit application

## Common Questions

**Q: How long does it take?**
A: ~1 second per image for detection, clustering is instant

**Q: Can I use this on videos?**
A: Not directly, but you can extract frames first

**Q: Does it need internet?**
A: No! Completely offline

**Q: Will it modify my photos?**
A: No, original photos are never changed

**Q: Can I undo labeling?**
A: Just label the cluster with a new name

## Next Steps

- Read full README.md for advanced features
- Adjust settings in .env file
- Try the search and export features
- Process your entire photo library!

---

**That's it! You're ready to organize thousands of photos! 🎉**
