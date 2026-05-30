"""
Face Clustering Module
Groups similar faces together using clustering algorithms
"""

import numpy as np
from sklearn.cluster import DBSCAN, AgglomerativeClustering
from collections import defaultdict
from typing import List, Dict
import face_recognition


class FaceClusterer:
    """Clusters face encodings to group similar faces"""
    
    def __init__(self, face_recognizer, tolerance=0.6, min_cluster_size=2):
        """
        Initialize face clustering
        
        Args:
            face_recognizer: FaceRecognizer instance with detected faces
            tolerance: Distance threshold for clustering (lower = stricter)
            min_cluster_size: Minimum faces needed to form a cluster
        """
        self.face_recognizer = face_recognizer
        self.tolerance = tolerance
        self.min_cluster_size = min_cluster_size
        self.clusters = {}  # cluster_id -> list of face indices
        self.cluster_labels = {}  # cluster_id -> person name
    
    def cluster_faces_dbscan(self) -> Dict[str, List[int]]:
        """
        Cluster faces using DBSCAN algorithm
        Good for finding clusters of varying sizes and handling outliers
        
        Returns:
            Dictionary mapping cluster_id to list of face indices
        """
        faces_data = self.face_recognizer.faces_data
        
        if not faces_data:
            print("No faces to cluster")
            return {}
        
        print(f"\n{'='*60}")
        print(f"FACE CLUSTERING")
        print(f"{'='*60}")
        print(f"Clustering {len(faces_data)} faces...")
        print(f"Algorithm: DBSCAN")
        print(f"Tolerance: {self.tolerance}")
        print(f"Min cluster size: {self.min_cluster_size}")
        print(f"{'='*60}\n")
        
        # Extract encodings
        encodings = np.array([face['encoding'] for face in faces_data])
        
        # Perform DBSCAN clustering
        clustering = DBSCAN(
            eps=self.tolerance,
            min_samples=self.min_cluster_size,
            metric='euclidean'
        )
        
        labels = clustering.fit_predict(encodings)
        
        # Organize results
        self.clusters = defaultdict(list)
        
        for idx, label in enumerate(labels):
            if label == -1:
                # Outlier/noise - create individual cluster
                cluster_id = f"single_{idx}"
            else:
                cluster_id = f"person_{label}"
            
            self.clusters[cluster_id].append(idx)
            
            # Update face data with cluster assignment
            faces_data[idx]['cluster_id'] = cluster_id
        
        # Print statistics
        self._print_cluster_stats()
        
        return dict(self.clusters)
    
    def cluster_faces_hierarchical(self, n_clusters=None) -> Dict[str, List[int]]:
        """
        Cluster faces using Agglomerative (Hierarchical) Clustering
        Good when you know approximately how many people are in the photos
        
        Args:
            n_clusters: Number of clusters to create (if None, uses distance threshold)
            
        Returns:
            Dictionary mapping cluster_id to list of face indices
        """
        faces_data = self.face_recognizer.faces_data
        
        if not faces_data:
            print("No faces to cluster")
            return {}
        
        print(f"\n{'='*60}")
        print(f"FACE CLUSTERING")
        print(f"{'='*60}")
        print(f"Clustering {len(faces_data)} faces...")
        print(f"Algorithm: Hierarchical")
        
        # Extract encodings
        encodings = np.array([face['encoding'] for face in faces_data])
        
        # Perform hierarchical clustering
        if n_clusters:
            print(f"Creating {n_clusters} clusters")
            clustering = AgglomerativeClustering(
                n_clusters=n_clusters,
                metric='euclidean',
                linkage='average'
            )
        else:
            print(f"Using distance threshold: {self.tolerance}")
            clustering = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=self.tolerance,
                metric='euclidean',
                linkage='average'
            )
        
        labels = clustering.fit_predict(encodings)
        
        # Organize results
        self.clusters = defaultdict(list)
        
        for idx, label in enumerate(labels):
            cluster_id = f"person_{label}"
            self.clusters[cluster_id].append(idx)
            
            # Update face data with cluster assignment
            faces_data[idx]['cluster_id'] = cluster_id
        
        print(f"{'='*60}\n")
        
        # Print statistics
        self._print_cluster_stats()
        
        return dict(self.clusters)
    
    def _print_cluster_stats(self):
        """Print clustering statistics"""
        num_clusters = len(self.clusters)
        
        # Count cluster sizes
        cluster_sizes = [len(faces) for faces in self.clusters.values()]
        
        # Separate single-face clusters from multi-face clusters
        single_face_clusters = sum(1 for size in cluster_sizes if size == 1)
        multi_face_clusters = num_clusters - single_face_clusters
        
        print(f"\n{'='*60}")
        print(f"CLUSTERING RESULTS")
        print(f"{'='*60}")
        print(f"Total clusters: {num_clusters}")
        print(f"Multi-face clusters (likely people): {multi_face_clusters}")
        print(f"Single-face clusters (unique/outliers): {single_face_clusters}")
        
        if cluster_sizes:
            print(f"Largest cluster: {max(cluster_sizes)} faces")
            print(f"Average cluster size: {np.mean(cluster_sizes):.1f} faces")
        
        # Show top 10 largest clusters
        sorted_clusters = sorted(
            self.clusters.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )
        
        print(f"\nTop 10 largest clusters:")
        for i, (cluster_id, face_indices) in enumerate(sorted_clusters[:10], 1):
            # Count unique images
            unique_images = set(
                self.face_recognizer.faces_data[idx]['image_path']
                for idx in face_indices
            )
            print(f"  {i}. {cluster_id}: {len(face_indices)} faces in {len(unique_images)} photos")
        
        print(f"{'='*60}\n")
    
    def get_cluster_info(self, cluster_id: str) -> Dict:
        """
        Get detailed information about a specific cluster
        
        Args:
            cluster_id: Cluster identifier
            
        Returns:
            Dictionary with cluster information
        """
        if cluster_id not in self.clusters:
            return None
        
        face_indices = self.clusters[cluster_id]
        faces_data = self.face_recognizer.faces_data
        
        # Get all photos containing faces from this cluster
        photos = set()
        face_details = []
        
        for face_idx in face_indices:
            face_info = faces_data[face_idx]
            photos.add(face_info['image_path'])
            face_details.append({
                'face_id': face_info['face_id'],
                'image_path': face_info['image_path'],
                'location': face_info['location']
            })
        
        # Get person name if assigned
        person_name = self.cluster_labels.get(cluster_id)
        if not person_name:
            # Check if any face in cluster has a person name
            for face_idx in face_indices:
                if faces_data[face_idx].get('person_name'):
                    person_name = faces_data[face_idx]['person_name']
                    break
        
        return {
            'cluster_id': cluster_id,
            'person_name': person_name,
            'num_faces': len(face_indices),
            'num_photos': len(photos),
            'photos': sorted(list(photos)),
            'face_indices': face_indices,
            'face_details': face_details
        }
    
    def get_all_clusters_summary(self) -> List[Dict]:
        """
        Get summary of all clusters
        
        Returns:
            List of cluster summaries sorted by size
        """
        summaries = []
        
        for cluster_id in self.clusters:
            info = self.get_cluster_info(cluster_id)
            if info:
                summaries.append({
                    'cluster_id': cluster_id,
                    'num_faces': info['num_faces'],
                    'num_photos': info['num_photos'],
                    'person_name': info['person_name']
                })
        
        # Sort by number of faces (descending)
        summaries.sort(key=lambda x: x['num_faces'], reverse=True)
        
        return summaries
    
    def assign_name_to_cluster(self, cluster_id: str, person_name: str) -> bool:
        """
        Assign a person name to all faces in a cluster
        
        Args:
            cluster_id: Cluster identifier
            person_name: Name to assign
            
        Returns:
            True if successful
        """
        if cluster_id not in self.clusters:
            print(f"Cluster {cluster_id} not found")
            return False
        
        face_indices = self.clusters[cluster_id]
        faces_data = self.face_recognizer.faces_data
        
        # Update all faces in cluster
        for face_idx in face_indices:
            faces_data[face_idx]['person_name'] = person_name
        
        # Store in cluster labels
        self.cluster_labels[cluster_id] = person_name
        
        print(f"✓ Assigned '{person_name}' to {len(face_indices)} faces in {cluster_id}")
        return True
    
    def merge_clusters(self, cluster_ids: List[str], new_cluster_id: str = None,
                      person_name: str = None) -> bool:
        """
        Merge multiple clusters into one
        
        Args:
            cluster_ids: List of cluster IDs to merge
            new_cluster_id: Optional name for merged cluster
            person_name: Optional person name for merged cluster
            
        Returns:
            True if successful
        """
        # Collect all face indices
        merged_faces = []
        for cluster_id in cluster_ids:
            if cluster_id in self.clusters:
                merged_faces.extend(self.clusters[cluster_id])
            else:
                print(f"Warning: Cluster {cluster_id} not found")
        
        if not merged_faces:
            print("No faces found in specified clusters")
            return False
        
        # Create new cluster ID
        if not new_cluster_id:
            new_cluster_id = f"merged_{'_'.join(cluster_ids[:3])}"
        
        # Remove old clusters
        for cluster_id in cluster_ids:
            if cluster_id in self.clusters:
                del self.clusters[cluster_id]
                if cluster_id in self.cluster_labels:
                    del self.cluster_labels[cluster_id]
        
        # Add new merged cluster
        self.clusters[new_cluster_id] = merged_faces
        
        # Update face data
        faces_data = self.face_recognizer.faces_data
        for face_idx in merged_faces:
            faces_data[face_idx]['cluster_id'] = new_cluster_id
            if person_name:
                faces_data[face_idx]['person_name'] = person_name
        
        if person_name:
            self.cluster_labels[new_cluster_id] = person_name
        
        print(f"✓ Merged {len(cluster_ids)} clusters into '{new_cluster_id}' ({len(merged_faces)} faces)")
        return True
    
    def split_cluster(self, cluster_id: str, face_indices_to_split: List[int],
                     new_cluster_id: str = None) -> bool:
        """
        Split a cluster into two
        
        Args:
            cluster_id: Original cluster ID
            face_indices_to_split: Indices of faces to move to new cluster
            new_cluster_id: Optional name for new cluster
            
        Returns:
            True if successful
        """
        if cluster_id not in self.clusters:
            print(f"Cluster {cluster_id} not found")
            return False
        
        original_faces = self.clusters[cluster_id]
        
        # Validate indices
        invalid_indices = [idx for idx in face_indices_to_split if idx not in original_faces]
        if invalid_indices:
            print(f"Invalid face indices: {invalid_indices}")
            return False
        
        # Create new cluster
        if not new_cluster_id:
            new_cluster_id = f"{cluster_id}_split"
        
        # Update clusters
        remaining_faces = [idx for idx in original_faces if idx not in face_indices_to_split]
        self.clusters[cluster_id] = remaining_faces
        self.clusters[new_cluster_id] = face_indices_to_split
        
        # Update face data
        faces_data = self.face_recognizer.faces_data
        for face_idx in face_indices_to_split:
            faces_data[face_idx]['cluster_id'] = new_cluster_id
        
        print(f"✓ Split {cluster_id} into two clusters:")
        print(f"  {cluster_id}: {len(remaining_faces)} faces")
        print(f"  {new_cluster_id}: {len(face_indices_to_split)} faces")
        
        return True
    
    def get_cluster_representative_faces(self, cluster_id: str, num_faces: int = 5) -> List[Dict]:
        """
        Get representative faces from a cluster (for preview)
        
        Args:
            cluster_id: Cluster identifier
            num_faces: Number of representative faces to return
            
        Returns:
            List of face data dictionaries
        """
        if cluster_id not in self.clusters:
            return []
        
        face_indices = self.clusters[cluster_id]
        faces_data = self.face_recognizer.faces_data
        
        # Select representative faces (evenly distributed)
        if len(face_indices) <= num_faces:
            selected_indices = face_indices
        else:
            step = len(face_indices) // num_faces
            selected_indices = [face_indices[i * step] for i in range(num_faces)]
        
        return [faces_data[idx] for idx in selected_indices]
    
    def search_faces_by_person_name(self, person_name: str) -> List[str]:
        """
        Search for all images containing a specific person
        
        Args:
            person_name: Name of person to search for
            
        Returns:
            List of image paths containing that person
        """
        faces_data = self.face_recognizer.faces_data
        images = set()
        
        for face in faces_data:
            if face.get('person_name', '').lower() == person_name.lower():
                images.add(face['image_path'])
        
        return sorted(list(images))
    
    def get_all_people(self) -> List[str]:
        """
        Get list of all identified people
        
        Returns:
            List of person names
        """
        faces_data = self.face_recognizer.faces_data
        people = set()
        
        for face in faces_data:
            person_name = face.get('person_name')
            if person_name:
                people.add(person_name)
        
        return sorted(list(people))
    
    def get_person_statistics(self) -> Dict[str, Dict]:
        """
        Get statistics for each identified person
        
        Returns:
            Dictionary mapping person names to their statistics
        """
        faces_data = self.face_recognizer.faces_data
        stats = defaultdict(lambda: {'face_count': 0, 'images': set()})
        
        for face in faces_data:
            person_name = face.get('person_name')
            if person_name:
                stats[person_name]['face_count'] += 1
                stats[person_name]['images'].add(face['image_path'])
        
        # Convert to regular dict with image counts
        result = {}
        for person, data in stats.items():
            result[person] = {
                'face_count': data['face_count'],
                'image_count': len(data['images']),
                'images': sorted(list(data['images']))
            }
        
        return result
    
    def auto_suggest_cluster_names(self) -> Dict[str, str]:
        """
        Auto-suggest names for clusters based on patterns
        (e.g., "Person 1", "Person 2", etc.)
        
        Returns:
            Dictionary mapping cluster_id to suggested name
        """
        suggestions = {}
        
        # Get clusters sorted by size
        sorted_clusters = sorted(
            self.clusters.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )
        
        person_number = 1
        for cluster_id, face_indices in sorted_clusters:
            # Skip single-face clusters
            if len(face_indices) <= 1:
                continue
            
            # Skip if already named
            if self.cluster_labels.get(cluster_id):
                continue
            
            suggestions[cluster_id] = f"Person {person_number}"
            person_number += 1
        
        return suggestions


def main():
    """Test function for face clustering"""
    import sys
    from face_recognizer import FaceRecognizer
    
    # Check if face data exists
    face_data_file = 'data/face_data.pkl'
    
    print("Loading face data...")
    recognizer = FaceRecognizer()
    
    if not recognizer.load_face_data(face_data_file):
        print(f"\nNo face data found at {face_data_file}")
        print("Please run face detection first:")
        print("  python src/face_recognizer.py /path/to/images")
        sys.exit(1)
    
    # Create clustering instance
    clusterer = FaceClusterer(recognizer, tolerance=0.6, min_cluster_size=2)
    
    # Perform clustering
    clusters = clusterer.cluster_faces_dbscan()
    
    # Show summary
    summary = clusterer.get_all_clusters_summary()
    print(f"\n{'='*60}")
    print(f"CLUSTER SUMMARY")
    print(f"{'='*60}")
    for i, cluster in enumerate(summary[:20], 1):
        person = cluster['person_name'] or "Unlabeled"
        print(f"{i}. {cluster['cluster_id']}: {cluster['num_faces']} faces, "
              f"{cluster['num_photos']} photos - {person}")
    
    if len(summary) > 20:
        print(f"\n... and {len(summary) - 20} more clusters")
    
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
