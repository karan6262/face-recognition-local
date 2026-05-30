"""
Configuration module for Local Face Finder
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Base paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
CONFIG_DIR = BASE_DIR / 'config'

# Create directories
DATA_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)
(DATA_DIR / 'thumbnails').mkdir(exist_ok=True)
(DATA_DIR / 'face_crops').mkdir(exist_ok=True)

# Face detection settings
FACE_DETECTION_MODEL = os.getenv('FACE_DETECTION_MODEL', 'hog')
FACE_CLUSTERING_TOLERANCE = float(os.getenv('FACE_CLUSTERING_TOLERANCE', '0.6'))
MIN_CLUSTER_SIZE = int(os.getenv('MIN_CLUSTER_SIZE', '2'))

# Image settings
SUPPORTED_FORMATS = os.getenv('SUPPORTED_FORMATS', '.jpg,.jpeg,.png,.bmp,.gif,.tiff,.webp').split(',')
THUMBNAIL_SIZE = int(os.getenv('THUMBNAIL_SIZE', '200'))
FACE_CROP_SIZE = int(os.getenv('FACE_CROP_SIZE', '150'))

# Database
DB_PATH = DATA_DIR / 'faces.db'

# Performance
MAX_IMAGE_SIZE = int(os.getenv('MAX_IMAGE_SIZE', '2000'))
BATCH_SIZE = int(os.getenv('BATCH_SIZE', '100'))
