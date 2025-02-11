"""Spotisub constants"""
import os


SPLIT_TOKENS = ["(", "-", "feat"]


# Configuration constants
ARTIST_GEN_SCHED = "ARTIST_GEN_SCHED"
ARTIST_TOP_GEN_SCHED = "ARTIST_TOP_GEN_SCHED"
ARTIST_PLAYLIST_ENABLED = "ARTIST_PLAYLIST_ENABLED"
EXCLUDED_WORDS = "EXCLUDED_WORDS"
ITEMS_PER_PLAYLIST = "ITEMS_PER_PLAYLIST"
LIDARR_BASE_API_PATH = "LIDARR_BASE_API_PATH"
LIDARR_ENABLED = "LIDARR_ENABLED"
LIDARR_IP = "LIDARR_IP"
LIDARR_PORT = "LIDARR_PORT"
LIDARR_TOKEN = "LIDARR_TOKEN"
LIDARR_USE_SSL = "LIDARR_USE_SSL"
LOG_LEVEL = "LOG_LEVEL"
NUM_USER_PLAYLISTS = "NUM_USER_PLAYLISTS"
PLAYLIST_GEN_SCHED = "PLAYLIST_GEN_SCHED"
PLAYLIST_PREFIX = "PLAYLIST_PREFIX"
RECOMMEND_GEN_SCHED = "RECOMMEND_GEN_SCHED"
SAVED_GEN_SCHED = "SAVED_GEN_SCHED"
SCHEDULER_ENABLED = "SCHEDULER_ENABLED"
SPOTDL_ENABLED = "SPOTDL_ENABLED"
SPOTDL_FORMAT = "SPOTDL_FORMAT"
SPOTIPY_CLIENT_ID = "SPOTIPY_CLIENT_ID"
SPOTIPY_CLIENT_SECRET = "SPOTIPY_CLIENT_SECRET"
SPOTIPY_REDIRECT_URI = "SPOTIPY_REDIRECT_URI"
SUBSONIC_API_BASE_URL = "SUBSONIC_API_BASE_URL"
SUBSONIC_API_HOST = "SUBSONIC_API_HOST"
SUBSONIC_API_USER = "SUBSONIC_API_USER"
SUBSONIC_API_PASS = "SUBSONIC_API_PASS"
SUBSONIC_API_PORT = "SUBSONIC_API_PORT"
TEXT_COMAPRE_MATCHING_ENABLED = "TEXT_COMAPRE_MATCHING_ENABLED"

# Default configuration values constants
ARTIST_GEN_SCHED_DEFAULT_VALUE = "1"
ARTIST_TOP_GEN_SCHED_DEFAULT_VALUE = "1"
ARTIST_PLAYLIST_ENABLED_DEFAULT_VALUE = "0"
EXCLUDED_WORDS_DEFAULT_VALUE = "acoustic,instrumental,demo"
ITEMS_PER_PLAYLIST_DEFAULT_VALUE = "1000"
LIDARR_BASE_API_PATH_DEFAULT_VALUE = ""
LIDARR_ENABLED_DEFAULT_VALUE = "0"
LIDARR_USE_SSL_DEFAULT_VALUE = "0"
LOG_LEVEL_DEFAULT_VALUE = "40"
NUM_USER_PLAYLISTS_DEFAULT_VALUE = "5"
PLAYLIST_GEN_SCHED_DEFAULT_VALUE = "3"
PLAYLIST_PREFIX_DEFAULT_VALUE = "Spotisub - "
RECOMMEND_GEN_SCHED_DEFAULT_VALUE = "4"
SAVED_GEN_SCHED_DEFAULT_VALUE = "2"
SCHEDULER_ENABLED_DEFAULT_VALUE = "1"
SPOTDL_ENABLED_DEFAULT_VALUE = "0"
SPOTDL_FORMAT_DEFAULT_VALUE = "/music/{artist}/{artists} - {album} ({year}) - {track-number} - {title}.{output-ext}"
SPOTIPY_CLIENT_ID_DEFAULT_VALUE = ""
SPOTIPY_CLIENT_SECRET_DEFAULT_VALUE = ""
SPOTIPY_REDIRECT_URI_DEFAULT_VALUE = "http://127.0.0.1:8080/"
SUBSONIC_API_BASE_URL_DEFAULT_VALUE = ""
TEXT_COMAPRE_MATCHING_ENABLED_DEFAULT_VALUE = "0"


# Scheduler constants
JOB_AR_ID = 'artist_recommendations'
JOB_ATT_ID = 'artist_top_tracks'
JOB_MR_ID = 'my_recommendations'
JOB_UP_ID = 'user_playlists'
JOB_ST_ID = 'saved_tracks'


# Cache constants
CACHE_DIR = os.path.join(os.path.abspath(os.curdir), 'cache')
SPOTIFY_OBJECT_CACHE_FILENAME = 'spotify_object_cache.pkl'
SUBSONIC_CACHE_FILENAME = 'subsonic_cache.pkl'
