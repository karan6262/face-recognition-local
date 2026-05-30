"""
Local Image Scanner Module
Recursively scans directories for image files
"""

import os
from pathlib import Path
from typing import List, Set
from tqdm import tqdm
import hashlib


class ImageScanner:
    """Scans local directories for image files"""
    
    def __init__(self, supported_formats=None):
        """
        Initialize image scanner
        
        Args:
            supported_formats: List of supported file extensions (e.g., ['.jpg', '.png'])
        """
        if supported_formats is None:
            supported_formats = ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp']
        
        self.supported_formats = [fmt.lower() for fmt in supported_formats]
        self.scanned_files = []
        self.skipped_files = []
        self.total_size = 0
    
    def scan_directory(self, directory_path: str, recursive: bool = True) -> List[str]:
        """
        Scan a directory for image files
        
        Args:
            directory_path: Path to directory to scan
            recursive: If True, scan subdirectories
            
        Returns:
            List of image file paths
        """
        directory = Path(directory_path)
        
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory_path}")
        
        if not directory.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory_path}")
        
        print(f"\nScanning directory: {directory}")
        print(f"Recursive: {recursive}")
        print(f"Supported formats: {', '.join(self.supported_formats)}")
        print("-" * 60)
        
        # Reset counters
        self.scanned_files = []
        self.skipped_files = []
        self.total_size = 0
        
        # Scan for files
        if recursive:
            files = directory.rglob('*')
        else:
            files = directory.glob('*')
        
        # Filter image files
        image_files = []
        for file_path in tqdm(files, desc="Scanning", unit="files"):
            if file_path.is_file() and self._is_image_file(file_path):
                try:
                    # Check if file is readable
                    file_size = file_path.stat().st_size
                    if file_size == 0:
                        self.skipped_files.append((str(file_path), "Empty file"))
                        continue
                    
                    image_files.append(str(file_path))
                    self.total_size += file_size
                    
                except Exception as e:
                    self.skipped_files.append((str(file_path), str(e)))
        
        self.scanned_files = image_files
        
        # Print summary
        self._print_scan_summary()
        
        return image_files
    
    def scan_multiple_directories(self, directory_paths: List[str], recursive: bool = True) -> List[str]:
        """
        Scan multiple directories for image files
        
        Args:
            directory_paths: List of directory paths to scan
            recursive: If True, scan subdirectories
            
        Returns:
            List of all image file paths found
        """
        all_files = []
        
        for dir_path in directory_paths:
            try:
                files = self.scan_directory(dir_path, recursive)
                all_files.extend(files)
            except Exception as e:
                print(f"Error scanning {dir_path}: {e}")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_files = []
        for f in all_files:
            if f not in seen:
                seen.add(f)
                unique_files.append(f)
        
        self.scanned_files = unique_files
        return unique_files
    
    def _is_image_file(self, file_path: Path) -> bool:
        """
        Check if file is a supported image format
        
        Args:
            file_path: Path to file
            
        Returns:
            True if file is a supported image
        """
        return file_path.suffix.lower() in self.supported_formats
    
    def _print_scan_summary(self):
        """Print summary of scan results"""
        print("\n" + "=" * 60)
        print("SCAN SUMMARY")
        print("=" * 60)
        print(f"Images found: {len(self.scanned_files)}")
        print(f"Total size: {self._format_size(self.total_size)}")
        
        if self.skipped_files:
            print(f"Skipped files: {len(self.skipped_files)}")
            if len(self.skipped_files) <= 5:
                for file_path, reason in self.skipped_files:
                    print(f"  - {Path(file_path).name}: {reason}")
            else:
                print(f"  (showing first 5)")
                for file_path, reason in self.skipped_files[:5]:
                    print(f"  - {Path(file_path).name}: {reason}")
        
        # Show format breakdown
        if self.scanned_files:
            formats = {}
            for file_path in self.scanned_files:
                ext = Path(file_path).suffix.lower()
                formats[ext] = formats.get(ext, 0) + 1
            
            print("\nFile formats:")
            for ext, count in sorted(formats.items(), key=lambda x: x[1], reverse=True):
                print(f"  {ext}: {count} files")
        
        print("=" * 60 + "\n")
    
    def _format_size(self, size_bytes: int) -> str:
        """
        Format byte size to human-readable string
        
        Args:
            size_bytes: Size in bytes
            
        Returns:
            Formatted string (e.g., "1.5 MB")
        """
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"
    
    def get_file_hash(self, file_path: str) -> str:
        """
        Calculate SHA-256 hash of file
        Useful for detecting duplicate images
        
        Args:
            file_path: Path to file
            
        Returns:
            SHA-256 hash as hex string
        """
        sha256 = hashlib.sha256()
        
        with open(file_path, 'rb') as f:
            # Read in chunks to handle large files
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        
        return sha256.hexdigest()
    
    def find_duplicate_images(self, file_paths: List[str] = None) -> dict:
        """
        Find duplicate images based on file hash
        
        Args:
            file_paths: List of file paths to check (uses scanned_files if None)
            
        Returns:
            Dictionary mapping hash to list of file paths with that hash
        """
        if file_paths is None:
            file_paths = self.scanned_files
        
        print(f"\nChecking for duplicate images in {len(file_paths)} files...")
        
        hash_map = {}
        
        for file_path in tqdm(file_paths, desc="Computing hashes", unit="files"):
            try:
                file_hash = self.get_file_hash(file_path)
                
                if file_hash not in hash_map:
                    hash_map[file_hash] = []
                hash_map[file_hash].append(file_path)
                
            except Exception as e:
                print(f"Error hashing {file_path}: {e}")
        
        # Filter to only duplicates
        duplicates = {h: paths for h, paths in hash_map.items() if len(paths) > 1}
        
        if duplicates:
            print(f"\nFound {len(duplicates)} sets of duplicate images:")
            for i, (file_hash, paths) in enumerate(duplicates.items(), 1):
                if i <= 5:  # Show first 5
                    print(f"\n  Set {i} ({len(paths)} copies):")
                    for path in paths:
                        print(f"    - {path}")
            
            if len(duplicates) > 5:
                print(f"\n  ... and {len(duplicates) - 5} more duplicate sets")
        else:
            print("No duplicate images found.")
        
        return duplicates
    
    def get_directory_statistics(self, directory_path: str = None) -> dict:
        """
        Get statistics about images in a directory
        
        Args:
            directory_path: Directory to analyze (uses current scan if None)
            
        Returns:
            Dictionary with statistics
        """
        if directory_path:
            self.scan_directory(directory_path)
        
        if not self.scanned_files:
            return {}
        
        stats = {
            'total_files': len(self.scanned_files),
            'total_size': self.total_size,
            'total_size_formatted': self._format_size(self.total_size),
            'formats': {},
            'subdirectories': set(),
        }
        
        for file_path in self.scanned_files:
            path = Path(file_path)
            
            # Format count
            ext = path.suffix.lower()
            stats['formats'][ext] = stats['formats'].get(ext, 0) + 1
            
            # Subdirectory
            stats['subdirectories'].add(str(path.parent))
        
        stats['num_subdirectories'] = len(stats['subdirectories'])
        stats['subdirectories'] = list(stats['subdirectories'])
        
        return stats
    
    def filter_by_format(self, formats: List[str]) -> List[str]:
        """
        Filter scanned files by format
        
        Args:
            formats: List of formats to include (e.g., ['.jpg', '.png'])
            
        Returns:
            Filtered list of file paths
        """
        formats = [fmt.lower() for fmt in formats]
        return [f for f in self.scanned_files if Path(f).suffix.lower() in formats]
    
    def filter_by_size(self, min_size: int = 0, max_size: int = None) -> List[str]:
        """
        Filter scanned files by file size
        
        Args:
            min_size: Minimum file size in bytes
            max_size: Maximum file size in bytes (None for no limit)
            
        Returns:
            Filtered list of file paths
        """
        filtered = []
        
        for file_path in self.scanned_files:
            try:
                size = Path(file_path).stat().st_size
                if size >= min_size and (max_size is None or size <= max_size):
                    filtered.append(file_path)
            except:
                continue
        
        return filtered


def main():
    """Test function for image scanner"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python image_scanner.py <directory_path>")
        print("\nExample: python image_scanner.py /path/to/photos")
        sys.exit(1)
    
    directory = sys.argv[1]
    
    # Create scanner
    scanner = ImageScanner()
    
    # Scan directory
    image_files = scanner.scan_directory(directory, recursive=True)
    
    print(f"\nFound {len(image_files)} images")
    
    if image_files:
        # Show first 10 files
        print("\nFirst 10 images:")
        for i, file_path in enumerate(image_files[:10], 1):
            print(f"  {i}. {file_path}")
        
        if len(image_files) > 10:
            print(f"  ... and {len(image_files) - 10} more")
        
        # Get statistics
        stats = scanner.get_directory_statistics()
        print(f"\nStatistics:")
        print(f"  Subdirectories: {stats['num_subdirectories']}")
        print(f"  Total size: {stats['total_size_formatted']}")
        
        # Check for duplicates
        duplicates = scanner.find_duplicate_images()
        if duplicates:
            print(f"\nFound {len(duplicates)} sets of duplicate images")


if __name__ == "__main__":
    main()
