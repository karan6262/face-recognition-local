"""
Face Recognition Module
Detects faces in images and creates encodings for recognition
"""

import face_recognition
import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Tuple
from tqdm import tqdm
from PIL import Image
import pickle


class FaceRecognizer:
    """Detects and encodes faces from images"""
    
    def __init__(self, detection_model='hog', max_image_size=2000):
        """
        Initialize face recognizer
        
        Args:
            detection_model: 'hog' (faster, CPU) or 'cnn' (more accurate, GPU)
            max_image_size: Resize images larger than this for faster processing
        """
        self.detection_model = detection_model
        self.max_image_size = max_image_size
        self.faces_data = []  # List of face data dictionaries
    
    def detect_faces_in_image(self, image_path: str) -> List[Dict]:
        """
        Detect all faces in a single image
        
        Args:
            image_path: Path to image file
            
        Returns:
            List of face data dictionaries with encoding, location, etc.
        """
        try:
            # Load image
            image = face_recognition.load_image_file(image_path)
            
            # Resize if too large (for performance)
            original_height, original_width = image.shape[:2]
            if max(original_height, original_width) > self.max_image_size:
                scale = self.max_image_size / max(original_height, original_width)
                new_width = int(original_width * scale)
                new_height = int(original_height * scale)
                image = cv2.resize(image, (new_width, new_height))
            else:
                scale = 1.0
            
            # Detect face locations
            face_locations = face_recognition.face_locations(
                image,
                model=self.detection_model
            )
            
            if not face_locations:
                return []
            
            # Generate face encodings
            face_encodings = face_recognition.face_encodings(image, face_locations)
            
            # Create face data
            faces = []
            for idx, (encoding, location) in enumerate(zip(face_encodings, face_locations)):
                # Scale location back to original size
                if scale != 1.0:
                    top, right, bottom, left = location
                    location = (
                        int(top / scale),
                        int(right / scale),
                        int(bottom / scale),
                        int(left / scale)
                    )
                
                face_data = {
                    'image_path': str(image_path),
                    'encoding': encoding,
                    'location': location,  # (top, right, bottom, left)
                    'face_index': idx,
                    'cluster_id': None,  # To be assigned by clustering
                    'person_name': None,  # To be labeled by user
                }
                
                faces.append(face_data)
            
            return faces
            
        except Exception as e:
            print(f"Error processing {Path(image_path).name}: {e}")
            return []
    
    def process_images(self, image_paths: List[str], save_face_crops=True, 
                      face_crop_dir=None) -> int:
        """
        Process multiple images and extract all faces
        
        Args:
            image_paths: List of paths to image files
            save_face_crops: If True, save cropped face images
            face_crop_dir: Directory to save face crops
            
        Returns:
            Number of faces detected
        """
        print(f"\n{'='*60}")
        print(f"FACE DETECTION")
        print(f"{'='*60}")
        print(f"Processing {len(image_paths)} images...")
        print(f"Detection model: {self.detection_model}")
        print(f"{'='*60}\n")
        
        self.faces_data = []
        face_count = 0
        images_with_faces = 0
        errors = []
        
        for image_path in tqdm(image_paths, desc="Detecting faces", unit="image"):
            faces = self.detect_faces_in_image(image_path)
            
            if faces:
                images_with_faces += 1
                
                for face_data in faces:
                    # Assign unique face ID
                    face_id = f"{Path(image_path).stem}_face_{face_data['face_index']}"
                    face_data['face_id'] = face_id
                    
                    # Save cropped face image
                    if save_face_crops and face_crop_dir:
                        self._save_face_crop(
                            image_path,
                            face_data['location'],
                            face_id,
                            face_crop_dir
                        )
                    
                    self.faces_data.append(face_data)
                    face_count += 1
        
        # Print summary
        self._print_detection_summary(
            len(image_paths),
            images_with_faces,
            face_count
        )
        
        return face_count
    
    def _save_face_crop(self, image_path: str, location: Tuple[int, int, int, int],
                        face_id: str, output_dir: str):
        """
        Save a cropped face image
        
        Args:
            image_path: Path to original image
            location: Face location tuple (top, right, bottom, left)
            face_id: Unique identifier for this face
            output_dir: Directory to save crop
        """
        try:
            # Load original image
            image = cv2.imread(str(image_path))
            if image is None:
                return
            
            # Extract face region
            top, right, bottom, left = location
            
            # Add padding
            padding = 20
            height, width = image.shape[:2]
            top = max(0, top - padding)
            bottom = min(height, bottom + padding)
            left = max(0, left - padding)
            right = min(width, right + padding)
            
            face_image = image[top:bottom, left:right]
            
            # Create output directory
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Save face crop
            crop_file = output_path / f"{face_id}.jpg"
            cv2.imwrite(str(crop_file), face_image)
            
        except Exception as e:
            print(f"Warning: Could not save face crop {face_id}: {e}")
    
    def _print_detection_summary(self, total_images: int, images_with_faces: int,
                                 total_faces: int):
        """Print summary of detection results"""
        print(f"\n{'='*60}")
        print(f"DETECTION SUMMARY")
        print(f"{'='*60}")
        print(f"Total images processed: {total_images}")
        print(f"Images with faces: {images_with_faces} ({images_with_faces/total_images*100:.1f}%)")
        print(f"Total faces detected: {total_faces}")
        
        if images_with_faces > 0:
            print(f"Average faces per image: {total_faces/images_with_faces:.1f}")
        
        print(f"{'='*60}\n")
    
    def compare_faces(self, face_encoding, tolerance=0.6) -> List[int]:
        """
        Compare a face encoding against all known faces
        
        Args:
            face_encoding: Face encoding to compare (128-dimensional array)
            tolerance: How much distance between faces to consider a match (lower = stricter)
            
        Returns:
            List of indices of matching faces
        """
        if not self.faces_data:
            return []
        
        # Get all encodings
        known_encodings = [face['encoding'] for face in self.faces_data]
        
        # Calculate face distances
        face_distances = face_recognition.face_distance(known_encodings, face_encoding)
        
        # Find matches within tolerance
        matches = [i for i, distance in enumerate(face_distances) if distance <= tolerance]
        
        return matches
    
    def find_similar_faces(self, face_index: int, tolerance=0.6, max_results=10) -> List[Dict]:
        """
        Find faces similar to a given face
        
        Args:
            face_index: Index of face in faces_data
            tolerance: Matching tolerance
            max_results: Maximum number of results to return
            
        Returns:
            List of similar face data dictionaries with distance scores
        """
        if face_index >= len(self.faces_data):
            return []
        
        target_encoding = self.faces_data[face_index]['encoding']
        
        # Get all encodings
        known_encodings = [face['encoding'] for face in self.faces_data]
        
        # Calculate distances
        distances = face_recognition.face_distance(known_encodings, target_encoding)
        
        # Create results with distances
        results = []
        for i, distance in enumerate(distances):
            if i != face_index and distance <= tolerance:
                face_data = self.faces_data[i].copy()
                face_data['distance'] = distance
                face_data['similarity'] = 1.0 - distance  # Convert to similarity score
                results.append(face_data)
        
        # Sort by distance (most similar first)
        results.sort(key=lambda x: x['distance'])
        
        return results[:max_results]
    
    def get_faces_from_image(self, image_path: str) -> List[Dict]:
        """
        Get all faces detected in a specific image
        
        Args:
            image_path: Path to image
            
        Returns:
            List of face data for that image
        """
        return [face for face in self.faces_data if face['image_path'] == image_path]
    
    def get_images_with_face(self, face_id: str) -> List[str]:
        """
        Get all images containing faces from the same cluster as the given face
        
        Args:
            face_id: Face ID to search for
            
        Returns:
            List of image paths
        """
        # Find the face
        target_face = None
        for face in self.faces_data:
            if face['face_id'] == face_id:
                target_face = face
                break
        
        if not target_face or not target_face.get('cluster_id'):
            return []
        
        # Get all images with faces from same cluster
        cluster_id = target_face['cluster_id']
        images = set()
        
        for face in self.faces_data:
            if face.get('cluster_id') == cluster_id:
                images.add(face['image_path'])
        
        return sorted(list(images))
    
    def save_face_data(self, output_file: str):
        """
        Save face data to file
        
        Args:
            output_file: Path to output file (.pkl)
        """
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'wb') as f:
            pickle.dump(self.faces_data, f)
        
        print(f"✓ Saved {len(self.faces_data)} face records to {output_file}")
    
    def load_face_data(self, input_file: str) -> bool:
        """
        Load face data from file
        
        Args:
            input_file: Path to input file (.pkl)
            
        Returns:
            True if successful
        """
        input_path = Path(input_file)
        
        if not input_path.exists():
            print(f"Face data file not found: {input_file}")
            return False
        
        with open(input_file, 'rb') as f:
            self.faces_data = pickle.load(f)
        
        print(f"✓ Loaded {len(self.faces_data)} face records from {input_file}")
        return True
    
    def get_statistics(self) -> Dict:
        """
        Get statistics about detected faces
        
        Returns:
            Dictionary with statistics
        """
        if not self.faces_data:
            return {}
        
        # Count unique images
        unique_images = set(face['image_path'] for face in self.faces_data)
        
        # Count labeled faces
        labeled = sum(1 for face in self.faces_data if face.get('person_name'))
        
        # Count clustered faces
        clustered = sum(1 for face in self.faces_data if face.get('cluster_id') is not None)
        
        # Count unique clusters
        clusters = set(face['cluster_id'] for face in self.faces_data if face.get('cluster_id') is not None)
        
        # Count unique people
        people = set(face['person_name'] for face in self.faces_data if face.get('person_name'))
        
        stats = {
            'total_faces': len(self.faces_data),
            'unique_images': len(unique_images),
            'labeled_faces': labeled,
            'unlabeled_faces': len(self.faces_data) - labeled,
            'clustered_faces': clustered,
            'num_clusters': len(clusters),
            'num_people': len(people),
            'people_names': sorted(list(people))
        }
        
        return stats
    
    def create_thumbnail(self, image_path: str, output_path: str, size=(200, 200)):
        """
        Create thumbnail of an image
        
        Args:
            image_path: Path to original image
            output_path: Path to save thumbnail
            size: Thumbnail size (width, height)
        """
        try:
            with Image.open(image_path) as img:
                img.thumbnail(size, Image.Resampling.LANCZOS)
                img.save(output_path, "JPEG", quality=85)
        except Exception as e:
            print(f"Error creating thumbnail for {image_path}: {e}")


def main():
    """Test function for face recognizer"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python face_recognizer.py <image_path_or_directory>")
        print("\nExample:")
        print("  python face_recognizer.py /path/to/photo.jpg")
        print("  python face_recognizer.py /path/to/photos/")
        sys.exit(1)
    
    path = sys.argv[1]
    path_obj = Path(path)
    
    # Determine if single file or directory
    if path_obj.is_file():
        image_paths = [str(path_obj)]
    elif path_obj.is_dir():
        # Scan directory for images
        from image_scanner import ImageScanner
        scanner = ImageScanner()
        image_paths = scanner.scan_directory(str(path_obj), recursive=False)
    else:
        print(f"Invalid path: {path}")
        sys.exit(1)
    
    if not image_paths:
        print("No images found")
        sys.exit(1)
    
    # Create recognizer
    recognizer = FaceRecognizer(detection_model='hog')
    
    # Process images
    face_count = recognizer.process_images(
        image_paths,
        save_face_crops=True,
        face_crop_dir='data/face_crops'
    )
    
    # Show statistics
    stats = recognizer.get_statistics()
    print("\nStatistics:")
    print(f"  Total faces: {stats['total_faces']}")
    print(f"  Unique images: {stats['unique_images']}")
    
    # Show first few faces
    if recognizer.faces_data:
        print(f"\nFirst 5 faces detected:")
        for i, face in enumerate(recognizer.faces_data[:5], 1):
            print(f"  {i}. {face['face_id']} in {Path(face['image_path']).name}")


if __name__ == "__main__":
    main()
