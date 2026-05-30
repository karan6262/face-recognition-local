"""
Face Database Module
SQLite database for storing and searching face data
"""

import sqlite3
import pickle
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime


class FaceDatabase:
    """SQLite database for face recognition data"""
    
    def __init__(self, db_path='data/faces.db'):
        """
        Initialize face database
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
        self._init_database()
    
    def _init_database(self):
        """Initialize database and create tables"""
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row  # Return rows as dictionaries
        
        cursor = self.conn.cursor()
        
        # Images table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                file_name TEXT NOT NULL,
                file_size INTEGER,
                width INTEGER,
                height INTEGER,
                date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                date_modified TIMESTAMP,
                scan_id INTEGER
            )
        ''')
        
        # Faces table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS faces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                face_id TEXT UNIQUE NOT NULL,
                image_id INTEGER NOT NULL,
                encoding BLOB NOT NULL,
                location TEXT NOT NULL,
                face_index INTEGER,
                cluster_id TEXT,
                person_name TEXT,
                confidence REAL,
                date_detected TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            )
        ''')
        
        # People table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                notes TEXT,
                date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                date_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Clusters table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS clusters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_id TEXT UNIQUE NOT NULL,
                person_id INTEGER,
                num_faces INTEGER,
                date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE SET NULL
            )
        ''')
        
        # Scans table (track scanning sessions)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                directory_path TEXT,
                num_images INTEGER,
                num_faces INTEGER
            )
        ''')
        
        # Create indexes for faster queries
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_faces_image_id ON faces(image_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_faces_cluster_id ON faces(cluster_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_faces_person_name ON faces(person_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_file_path ON images(file_path)')
        
        self.conn.commit()
    
    def add_scan_session(self, directory_path: str) -> int:
        """
        Add a new scan session
        
        Args:
            directory_path: Path of directory that was scanned
            
        Returns:
            Scan ID
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO scans (directory_path, num_images, num_faces)
            VALUES (?, 0, 0)
        ''', (directory_path,))
        self.conn.commit()
        return cursor.lastrowid
    
    def update_scan_session(self, scan_id: int, num_images: int, num_faces: int):
        """Update scan session with final counts"""
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE scans
            SET num_images = ?, num_faces = ?
            WHERE id = ?
        ''', (num_images, num_faces, scan_id))
        self.conn.commit()
    
    def add_image(self, file_path: str, file_size: int = None, 
                  width: int = None, height: int = None, scan_id: int = None) -> int:
        """
        Add an image to the database
        
        Args:
            file_path: Path to image file
            file_size: File size in bytes
            width: Image width
            height: Image height
            scan_id: ID of scan session
            
        Returns:
            Image ID
        """
        path = Path(file_path)
        file_name = path.name
        date_modified = datetime.fromtimestamp(path.stat().st_mtime) if path.exists() else None
        
        cursor = self.conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO images (file_path, file_name, file_size, width, height, date_modified, scan_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (str(file_path), file_name, file_size, width, height, date_modified, scan_id))
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # Image already exists, return its ID
            cursor.execute('SELECT id FROM images WHERE file_path = ?', (str(file_path),))
            row = cursor.fetchone()
            return row['id'] if row else None
    
    def add_face(self, face_data: Dict, image_id: int) -> int:
        """
        Add a face to the database
        
        Args:
            face_data: Dictionary with face information
            image_id: ID of the image containing this face
            
        Returns:
            Face ID
        """
        # Serialize encoding as binary
        encoding_blob = pickle.dumps(face_data['encoding'])
        
        # Serialize location as JSON
        location_json = json.dumps(face_data['location'])
        
        cursor = self.conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO faces (
                    face_id, image_id, encoding, location, face_index,
                    cluster_id, person_name, confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                face_data['face_id'],
                image_id,
                encoding_blob,
                location_json,
                face_data.get('face_index', 0),
                face_data.get('cluster_id'),
                face_data.get('person_name'),
                face_data.get('confidence', 1.0)
            ))
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # Face already exists
            return None
    
    def update_face_cluster(self, face_id: str, cluster_id: str):
        """Update the cluster assignment for a face"""
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE faces
            SET cluster_id = ?
            WHERE face_id = ?
        ''', (cluster_id, face_id))
        self.conn.commit()
    
    def update_face_person(self, face_id: str, person_name: str):
        """Update the person name for a face"""
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE faces
            SET person_name = ?
            WHERE face_id = ?
        ''', (person_name, face_id))
        self.conn.commit()
    
    def update_cluster_person(self, cluster_id: str, person_name: str):
        """Update person name for all faces in a cluster"""
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE faces
            SET person_name = ?
            WHERE cluster_id = ?
        ''', (person_name, cluster_id))
        self.conn.commit()
    
    def add_person(self, name: str, notes: str = None) -> int:
        """
        Add a person to the database
        
        Args:
            name: Person's name
            notes: Optional notes about the person
            
        Returns:
            Person ID
        """
        cursor = self.conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO people (name, notes)
                VALUES (?, ?)
            ''', (name, notes))
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # Person already exists
            cursor.execute('SELECT id FROM people WHERE name = ?', (name,))
            row = cursor.fetchone()
            return row['id'] if row else None
    
    def search_images_by_person(self, person_name: str) -> List[Dict]:
        """
        Search for all images containing a specific person
        
        Args:
            person_name: Name of person to search for
            
        Returns:
            List of image dictionaries
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT DISTINCT i.*
            FROM images i
            JOIN faces f ON i.id = f.image_id
            WHERE f.person_name = ?
            ORDER BY i.date_added DESC
        ''', (person_name,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def search_faces_by_person(self, person_name: str) -> List[Dict]:
        """
        Search for all faces of a specific person
        
        Args:
            person_name: Name of person to search for
            
        Returns:
            List of face dictionaries
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT f.*, i.file_path, i.file_name
            FROM faces f
            JOIN images i ON f.image_id = i.id
            WHERE f.person_name = ?
            ORDER BY i.date_added DESC
        ''', (person_name,))
        
        rows = cursor.fetchall()
        faces = []
        
        for row in rows:
            face = dict(row)
            # Deserialize encoding
            face['encoding'] = pickle.loads(face['encoding'])
            # Deserialize location
            face['location'] = json.loads(face['location'])
            faces.append(face)
        
        return faces
    
    def get_all_people(self) -> List[str]:
        """
        Get list of all identified people
        
        Returns:
            List of person names
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT DISTINCT person_name
            FROM faces
            WHERE person_name IS NOT NULL
            ORDER BY person_name
        ''')
        
        return [row['person_name'] for row in cursor.fetchall()]
    
    def get_person_statistics(self, person_name: str) -> Dict:
        """
        Get statistics for a specific person
        
        Args:
            person_name: Name of person
            
        Returns:
            Dictionary with statistics
        """
        cursor = self.conn.cursor()
        
        # Count faces
        cursor.execute('''
            SELECT COUNT(*) as face_count
            FROM faces
            WHERE person_name = ?
        ''', (person_name,))
        face_count = cursor.fetchone()['face_count']
        
        # Count images
        cursor.execute('''
            SELECT COUNT(DISTINCT image_id) as image_count
            FROM faces
            WHERE person_name = ?
        ''', (person_name,))
        image_count = cursor.fetchone()['image_count']
        
        return {
            'person_name': person_name,
            'face_count': face_count,
            'image_count': image_count
        }
    
    def get_all_people_statistics(self) -> List[Dict]:
        """
        Get statistics for all people
        
        Returns:
            List of statistics dictionaries
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT 
                person_name,
                COUNT(*) as face_count,
                COUNT(DISTINCT image_id) as image_count
            FROM faces
            WHERE person_name IS NOT NULL
            GROUP BY person_name
            ORDER BY face_count DESC
        ''')
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_cluster_info(self, cluster_id: str) -> Dict:
        """
        Get information about a cluster
        
        Args:
            cluster_id: Cluster identifier
            
        Returns:
            Dictionary with cluster information
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT 
                cluster_id,
                COUNT(*) as num_faces,
                COUNT(DISTINCT image_id) as num_images,
                person_name
            FROM faces
            WHERE cluster_id = ?
            GROUP BY cluster_id, person_name
        ''', (cluster_id,))
        
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_all_clusters(self) -> List[Dict]:
        """
        Get information about all clusters
        
        Returns:
            List of cluster dictionaries
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT 
                cluster_id,
                COUNT(*) as num_faces,
                COUNT(DISTINCT image_id) as num_images,
                person_name
            FROM faces
            WHERE cluster_id IS NOT NULL
            GROUP BY cluster_id
            ORDER BY num_faces DESC
        ''')
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_unlabeled_clusters(self) -> List[Dict]:
        """
        Get all clusters that haven't been labeled with a person name
        
        Returns:
            List of unlabeled cluster dictionaries
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT 
                cluster_id,
                COUNT(*) as num_faces,
                COUNT(DISTINCT image_id) as num_images
            FROM faces
            WHERE cluster_id IS NOT NULL AND person_name IS NULL
            GROUP BY cluster_id
            ORDER BY num_faces DESC
        ''')
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_faces_in_cluster(self, cluster_id: str) -> List[Dict]:
        """
        Get all faces in a specific cluster
        
        Args:
            cluster_id: Cluster identifier
            
        Returns:
            List of face dictionaries
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT f.*, i.file_path, i.file_name
            FROM faces f
            JOIN images i ON f.image_id = i.id
            WHERE f.cluster_id = ?
            ORDER BY i.file_name
        ''', (cluster_id,))
        
        rows = cursor.fetchall()
        faces = []
        
        for row in rows:
            face = dict(row)
            # Deserialize encoding
            face['encoding'] = pickle.loads(face['encoding'])
            # Deserialize location
            face['location'] = json.loads(face['location'])
            faces.append(face)
        
        return faces
    
    def get_image_info(self, image_path: str) -> Dict:
        """
        Get information about an image
        
        Args:
            image_path: Path to image
            
        Returns:
            Image dictionary
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM images WHERE file_path = ?
        ''', (str(image_path),))
        
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_faces_in_image(self, image_path: str) -> List[Dict]:
        """
        Get all faces detected in a specific image
        
        Args:
            image_path: Path to image
            
        Returns:
            List of face dictionaries
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT f.*
            FROM faces f
            JOIN images i ON f.image_id = i.id
            WHERE i.file_path = ?
            ORDER BY f.face_index
        ''', (str(image_path),))
        
        rows = cursor.fetchall()
        faces = []
        
        for row in rows:
            face = dict(row)
            # Deserialize encoding
            face['encoding'] = pickle.loads(face['encoding'])
            # Deserialize location
            face['location'] = json.loads(face['location'])
            faces.append(face)
        
        return faces
    
    def get_database_statistics(self) -> Dict:
        """
        Get overall database statistics
        
        Returns:
            Dictionary with statistics
        """
        cursor = self.conn.cursor()
        
        # Count images
        cursor.execute('SELECT COUNT(*) as count FROM images')
        num_images = cursor.fetchone()['count']
        
        # Count faces
        cursor.execute('SELECT COUNT(*) as count FROM faces')
        num_faces = cursor.fetchone()['count']
        
        # Count labeled faces
        cursor.execute('SELECT COUNT(*) as count FROM faces WHERE person_name IS NOT NULL')
        num_labeled = cursor.fetchone()['count']
        
        # Count people
        cursor.execute('SELECT COUNT(DISTINCT person_name) as count FROM faces WHERE person_name IS NOT NULL')
        num_people = cursor.fetchone()['count']
        
        # Count clusters
        cursor.execute('SELECT COUNT(DISTINCT cluster_id) as count FROM faces WHERE cluster_id IS NOT NULL')
        num_clusters = cursor.fetchone()['count']
        
        return {
            'num_images': num_images,
            'num_faces': num_faces,
            'num_labeled_faces': num_labeled,
            'num_unlabeled_faces': num_faces - num_labeled,
            'num_people': num_people,
            'num_clusters': num_clusters
        }
    
    def search_images(self, query: str = None, person_name: str = None, 
                     date_from: datetime = None, date_to: datetime = None,
                     limit: int = 100) -> List[Dict]:
        """
        Advanced search for images
        
        Args:
            query: Search query for file name
            person_name: Filter by person name
            date_from: Filter by date added (from)
            date_to: Filter by date added (to)
            limit: Maximum results
            
        Returns:
            List of image dictionaries
        """
        cursor = self.conn.cursor()
        
        sql = 'SELECT DISTINCT i.* FROM images i'
        conditions = []
        params = []
        
        if person_name:
            sql += ' JOIN faces f ON i.id = f.image_id'
            conditions.append('f.person_name = ?')
            params.append(person_name)
        
        if query:
            conditions.append('i.file_name LIKE ?')
            params.append(f'%{query}%')
        
        if date_from:
            conditions.append('i.date_added >= ?')
            params.append(date_from)
        
        if date_to:
            conditions.append('i.date_added <= ?')
            params.append(date_to)
        
        if conditions:
            sql += ' WHERE ' + ' AND '.join(conditions)
        
        sql += ' ORDER BY i.date_added DESC LIMIT ?'
        params.append(limit)
        
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
    
    def export_person_images(self, person_name: str) -> List[str]:
        """
        Get list of all image paths for a specific person
        
        Args:
            person_name: Name of person
            
        Returns:
            List of image file paths
        """
        images = self.search_images_by_person(person_name)
        return [img['file_path'] for img in images]
    
    def clear_database(self):
        """Clear all data from database (use with caution!)"""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM faces')
        cursor.execute('DELETE FROM images')
        cursor.execute('DELETE FROM people')
        cursor.execute('DELETE FROM clusters')
        cursor.execute('DELETE FROM scans')
        self.conn.commit()
        print("✓ Database cleared")
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()


def main():
    """Test function for face database"""
    db = FaceDatabase('data/test_faces.db')
    
    # Print statistics
    stats = db.get_database_statistics()
    print("\n" + "="*60)
    print("DATABASE STATISTICS")
    print("="*60)
    print(f"Images: {stats['num_images']}")
    print(f"Faces: {stats['num_faces']}")
    print(f"Labeled faces: {stats['num_labeled_faces']}")
    print(f"Unlabeled faces: {stats['num_unlabeled_faces']}")
    print(f"People: {stats['num_people']}")
    print(f"Clusters: {stats['num_clusters']}")
    print("="*60 + "\n")
    
    # List all people
    people = db.get_all_people()
    if people:
        print("People in database:")
        for person in people:
            person_stats = db.get_person_statistics(person)
            print(f"  - {person}: {person_stats['face_count']} faces in {person_stats['image_count']} images")
    
    db.close()


if __name__ == "__main__":
    main()
