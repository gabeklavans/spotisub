"""Subsonic helper"""
import logging
import os
import time
import pickle
import threading
import libsonic
import string
from concurrent.futures import ThreadPoolExecutor
from expiringdict import ExpiringDict
from libsonic.errors import DataNotFoundError
from spotipy.exceptions import SpotifyException
from spotisub import database
from spotisub import constants
from spotisub import utils
from spotisub.helpers import spotdl_helper
from spotisub.exceptions import SubsonicDataException, SubsonicOfflineException
from spotisub.classes import ComparisonHelper, SubsonicCache
from spotisub.helpers import musicbrainz_helper

cache_executor = ThreadPoolExecutor(max_workers=1)
spotdl_executor = ThreadPoolExecutor(max_workers=1)

if os.environ.get(constants.SPOTDL_ENABLED,
                  constants.SPOTDL_ENABLED_DEFAULT_VALUE) == "1":
    logging.warning(
        "You have enabled SPOTDL integration, " +
        "make sure to configure the correct download " +
        "path and check that you have enough disk space " +
        "for music downloading.")

if os.environ.get(constants.LIDARR_ENABLED,
                  constants.LIDARR_ENABLED_DEFAULT_VALUE) == "1":
    from spotisub.helpers import lidarr_helper
    logging.warning(
        "You have enabled LIDARR integration, " +
        "if an artist won't be found inside the " +
        "lidarr database, the download process will be skipped.")

pysonic = libsonic.Connection(
    os.environ.get(
        constants.SUBSONIC_API_HOST),
    os.environ.get(
        constants.SUBSONIC_API_USER),
    os.environ.get(
        constants.SUBSONIC_API_PASS),
    appName="Spotisub",
    serverPath=os.environ.get(
        constants.SUBSONIC_API_BASE_URL,
        constants.SUBSONIC_API_BASE_URL_DEFAULT_VALUE) +
    "/rest",
    port=int(
        os.environ.get(
            constants.SUBSONIC_API_PORT)))


def load_subsonic_cache_from_file() -> SubsonicCache:
    cache = SubsonicCache(0, {})
    path = os.path.join(constants.CACHE_DIR, constants.SUBSONIC_CACHE_FILENAME)
    if os.path.exists(path):
        if os.stat(path).st_size == 0:
            os.remove(path)
        else:
            with open(path, 'rb') as f:
                cache = pickle.load(f)
    return cache


def load_spotify_cache_from_file():
    object = ExpiringDict(max_len=10000, max_age_seconds=43200)
    path = os.path.join(constants.CACHE_DIR, constants.SPOTIFY_OBJECT_CACHE_FILENAME)
    if os.path.exists(path):
        if os.stat(path).st_size == 0:
            os.remove(path)
        else:
            with open(path, 'rb') as f:
                old_cache_obj = pickle.load(f)
                for key, value in old_cache_obj.items():
                    object[key] = value
    return object


# caches
playlist_cache = ExpiringDict(max_len=500, max_age_seconds=300)
spotify_cache = None
subsonic_cache = load_subsonic_cache_from_file()


def save_cache_object_to_file(obj, filename: str):
    path = os.path.join(constants.CACHE_DIR, filename)
    with open(path, 'wb') as f:
        pickle.dump(obj, f)


def get_spotify_object_from_cache(sp, spotify_uri, force=False):
    if not force and spotify_uri in spotify_cache:
        return spotify_cache[spotify_uri]
    elif force:
        load_spotify_object_to_cache(sp, spotify_uri)
        return spotify_cache[spotify_uri]
    else:
        cache_executor.submit(load_spotify_object_to_cache, sp, spotify_uri)
    return None


def load_spotify_object_to_cache(sp, spotify_uri):
    try:
        global spotify_cache
        if spotify_uri in spotify_cache:
            return
        spotify_object = None
        if "track" in spotify_uri:
            spotify_object = sp.track(spotify_uri)
        elif "album" in spotify_uri:
            spotify_object = sp.album(spotify_uri)
        elif "artist" in spotify_uri:
            spotify_object = sp.artist(spotify_uri)
        elif "playlist" in spotify_uri:
            spotify_object = sp.playlist(spotify_uri)
        if spotify_object is not None:
            spotify_cache[spotify_uri] = spotify_object
            save_cache_object_to_file(spotify_cache, constants.SPOTIFY_OBJECT_CACHE_FILENAME)
    except SpotifyException:
        utils.write_exception()
        pass


def is_subsonic_cache_stale() -> bool:
    try:
        # fetch what should be the last song in the subsonic library, according to the cache
        subsonic_search = check_pysonic_connection().search2("", songCount=2, songOffset=subsonic_cache.total_song_count - 1, artistCount=0, albumCount=0)
        if "searchResult2" not in subsonic_search:
            raise SubsonicDataException(f'({threading.current_thread().ident}) search2 failed for checking subsonic cache.')

        if "song" not in subsonic_search["searchResult2"]:
            return True

        # the cache count is out of sync with the subsonic library; needs rebuilding
        if len(subsonic_search["searchResult2"]["song"]) != 1:
            return True
    except Exception:
        utils.write_exception()
        return True

    return False


def build_subsonic_cache() -> SubsonicCache:
    SONG_COUNT = 500
    song_offset = 0
    total_song_count = 0
    subsonic_songs_dict = {}
    try:
        while True:
            logging.debug(f'Fetching {SONG_COUNT} songs from subsonic library...')
            subsonic_search = check_pysonic_connection().search2("", songCount=SONG_COUNT, songOffset=song_offset, artistCount=0, albumCount=0)
            if "searchResult2" not in subsonic_search: # this should probably be an exception
                break

            if "song" not in subsonic_search["searchResult2"]:
                # done searching
                break

            num_retrieved_songs = len(subsonic_search["searchResult2"]["song"]);

            if num_retrieved_songs == 0:
                # done searching, though this shouldn't get here
                break

            song_offset += num_retrieved_songs

            if num_retrieved_songs < SONG_COUNT:
                total_song_count = song_offset

            for song in subsonic_search["searchResult2"]["song"]:
                if "musicBrainzId" in song:
                    subsonic_songs_dict[song["musicBrainzId"]] = song 
    except Exception:
        utils.write_exception()
        return SubsonicCache(0, {})

    cache = SubsonicCache(total_song_count, subsonic_songs_dict)

    logging.debug(f'Found {cache.total_song_count} songs and {len(subsonic_songs_dict)} MBIDs in subsonic library.')

    save_cache_object_to_file(cache, constants.SUBSONIC_CACHE_FILENAME)

    return cache


def check_and_get_subsonic_cache():
    if not is_subsonic_cache_stale():
        return subsonic_cache

    logging.info(f'({threading.current_thread().ident}) subsonic cache is stale, rebuilding...')

    return build_subsonic_cache()


def check_pysonic_connection():
    """Return SubsonicOfflineException if pysonic is offline"""
    if pysonic.ping():
        return pysonic
    raise SubsonicOfflineException()


def get_artists_array_names():
    """get artists array names"""
    check_pysonic_connection().getArtists()

    artist_names = []

    for index in check_pysonic_connection().getArtists()["artists"]["index"]:
        for artist in index["artist"]:
            if "name" in artist:
                artist_names.append(artist["name"])

    return artist_names


def search_artist(artist_name):
    """search artist"""

    for index in check_pysonic_connection().getArtists()["artists"]["index"]:
        for artist in index["artist"]:
            if "name" in artist:
                if artist_name.strip().lower(
                ) == artist["name"].strip().lower():
                    return artist["name"]

    return None


def get_subsonic_search_results(text_to_search):
    """get subsonic search results"""
    result = {}
    set_searches = utils.generate_compare_array(text_to_search)
    for set_search in set_searches:
        subsonic_search = check_pysonic_connection().search2(set_search, songCount=500)
        if ("searchResult2" in subsonic_search
            and len(subsonic_search["searchResult2"]) > 0
                and "song" in subsonic_search["searchResult2"]):
            for song in subsonic_search["searchResult2"]["song"]:
                if "id" in song and song["id"] not in result:
                    result[song["id"]] = song
    return result


def get_playlist_id_by_name(playlist_name):
    """get playlist id by name"""
    playlist_id = None
    playlists_search = check_pysonic_connection().getPlaylists()
    if "playlists" in playlists_search and len(
            playlists_search["playlists"]) > 0:
        single_playlist_search = playlists_search["playlists"]
        if "playlist" in single_playlist_search and len(
                single_playlist_search["playlist"]) > 0:
            for playlist in single_playlist_search["playlist"]:
                if playlist["name"].strip() == playlist_name.strip():
                    playlist_id = playlist["id"]
                    break
    return playlist_id


def has_isrc(track):
    """check if spotify track has isrc"""
    if ("external_ids" not in track
        or track["external_ids"] is None
        or "isrc" not in track["external_ids"]
        or track["external_ids"]["isrc"] is None
            or track["external_ids"]["isrc"] == ""):
        return False
    return True


def add_missing_values_to_track(sp, track):
    """calls spotify if tracks has missing album or isrc or uri"""
    if "id" in track:
        uri = 'spotify:track:' + track['id']
        if "album" not in track or not has_isrc(track):
            spotify_track = get_spotify_object_from_cache(sp, uri, force=True)
            if spotify_track is not None:
                track = spotify_track
            time.sleep(0.25)
        if "uri" not in track:
            track["uri"] = uri
        return track
    return None


def generate_playlist(playlist_info):
    """generate empty playlist if not exists"""
    playlist_info["prefix"] = os.environ.get(
        constants.PLAYLIST_PREFIX, constants.PLAYLIST_PREFIX_DEFAULT_VALUE).replace("\"", "")
    return database.create_playlist(playlist_info)


def write_playlist(sp, playlist_info, results):
    """write playlist to subsonic db"""
    try:
        playlist_info["prefix"] = os.environ.get(
            constants.PLAYLIST_PREFIX,
            constants.PLAYLIST_PREFIX_DEFAULT_VALUE)
        playlist_id = get_playlist_id_by_name(
            playlist_info["prefix"].replace("\"", "") + playlist_info["name"])
        song_ids = []
        old_song_ids = []
        if playlist_id is None:
            check_pysonic_connection().createPlaylist(
                name=playlist_info["prefix"].replace("\"", "") + playlist_info["name"], songIds=[])
            logging.info(
                '(%s) Creating playlist %s', str(
                    threading.current_thread().ident), playlist_info["name"])
            playlist_id = get_playlist_id_by_name(
                playlist_info["prefix"].replace("\"", "") + playlist_info["name"])
            database.delete_playlist_relation_by_id(playlist_id)
        else:
            old_song_ids = get_playlist_songs_ids_by_id(playlist_id)

        if playlist_id is not None:
            pl_info_db = database.select_playlist_info_by_uuid(
                playlist_info["uuid"])
            if pl_info_db is not None and pl_info_db.ignored is not None and pl_info_db.ignored == 1:
                logging.warning(
                    '(%s) Skipping playlist %s because it was marked as ignored',
                    playlist_info["name"])
            else:
                playlist_info["subsonic_playlist_id"] = playlist_id
                track_helper = []
                subsonic_cache = check_and_get_subsonic_cache()
                for track in results['tracks']:
                    track = add_missing_values_to_track(sp, track)

                    if track is None:
                        logging.error(f'({threading.current_thread().ident}) track was set to None when adding missing values, skipping.')
                        continue

                    found = False
                    excluded = False
                    logging.info(
                        '(%s) Searching %s in your music library',
                        str(threading.current_thread().ident),
                        track['name'])
                    comparison_helper = ComparisonHelper(
                        track, track["artists"][0], found, excluded, song_ids, track_helper)
                    comparison_helper = match_with_subsonic_track(
                        comparison_helper,
                        playlist_info,
                        old_song_ids,
                        subsonic_cache.song_mbid_dict)

                    track = comparison_helper.track
                    artist_spotify = comparison_helper.artist_spotify
                    found = comparison_helper.found
                    excluded = comparison_helper.excluded
                    song_ids = comparison_helper.song_ids
                    track_helper = comparison_helper.track_helper
                    if not excluded:
                        if (os.environ.get(constants.SPOTDL_ENABLED,
                                           constants.SPOTDL_ENABLED_DEFAULT_VALUE) == "1"
                                and found is False):
                            if "external_urls" in track and track["external_urls"] is not None and "spotify" in track[
                                    "external_urls"] and track["external_urls"]["spotify"] is not None:
                                is_monitored = True
                                if (os.environ.get(constants.LIDARR_ENABLED,
                                                   constants.LIDARR_ENABLED_DEFAULT_VALUE) == "1"):
                                    is_monitored = lidarr_helper.is_artist_monitored(
                                        artist_spotify["name"])
                                if is_monitored:
                                    logging.warning(
                                        '(%s) Track %s - %s not found in your music ' +
                                        'library, using SPOTDL downloader',
                                        str(threading.current_thread().ident),
                                        artist_spotify["name"],
                                        track['name'])
                                    logging.warning(
                                        '(%s) This track will be available after ' +
                                        'navidrome rescans your music dir',
                                        str(threading.current_thread().ident))
                                    spotdl_executor.submit(
                                        spotdl_helper.download_track, track["external_urls"]["spotify"])
                                else:
                                    logging.warning(
                                        '(%s) Track %s - %s not found in your music library',
                                        str(threading.current_thread().ident),
                                        artist_spotify["name"],
                                        track['name'])
                                    logging.warning(
                                        '(%s) This track hasn'
                                        't been found in your Lidarr database, ' +
                                        'skipping download process',
                                        str(threading.current_thread().ident))
                        elif found is False:
                            logging.warning(
                                '(%s) Track %s - %s not found in your music library',
                                str(threading.current_thread().ident),
                                artist_spotify["name"],
                                track['name'])
                            insert_result = database.insert_song(
                                playlist_info, None, artist_spotify, track)

                if len(song_ids) > 0:
                    check_pysonic_connection().createPlaylist(
                        playlistId=playlist_info["subsonic_playlist_id"], songIds=song_ids)
                    logging.info('(%s) Success! Created playlist %s', str(
                        threading.current_thread().ident), playlist_info["name"])
                elif len(song_ids) == 0:
                    try:
                        check_pysonic_connection().deletePlaylist(
                            playlist_info["subsonic_playlist_id"])
                        logging.info('(%s) Fail! No songs found for playlist %s', str(
                            threading.current_thread().ident), playlist_info["name"])
                    except DataNotFoundError:
                        pass

    except SubsonicOfflineException:
        logging.error(
            '(%s) There was an error creating a Playlist, perhaps is your Subsonic server offline?',
            str(threading.current_thread().ident))


def get_subsonic_track_via_mbid(comparison_helper, subsonic_tracks_dict: dict[str, dict]) -> dict | None:
    isrc = comparison_helper.track["external_ids"]["isrc"]
    spotify_track_mbids = musicbrainz_helper.get_mbids_from_isrc(isrc)
    matched_track = None
    for mbid in spotify_track_mbids:
        if mbid in subsonic_tracks_dict:
            matched_track = subsonic_tracks_dict[mbid]
            break

    if matched_track is None:
        logging.debug(f'({threading.current_thread().ident}) Spotify track with mbids {spotify_track_mbids} was not found in library.')

    return matched_track


def get_subsonic_track_via_string_compare(comparison_helper, subsonic_tracks_dict: dict[str, dict]) -> dict | None:
    matched_tracks = [s_t for s_t in subsonic_tracks_dict.values() if utils.compare_track_metadata(comparison_helper, s_t)]
    
    if len(matched_tracks) == 0:
        logging.debug(f'({threading.current_thread().ident}) Spotify track {comparison_helper.track["name"]} - {comparison_helper.artist_spotify["name"]} was not found in library via string compare.')
        return

    # TODO: add some sort of UI where the user can ensure the proper track is matched if there are multiple possibilities.
    # for now just pick the first one
    matched_track = matched_tracks[0]

    if (utils.compare_string_to_exclusion(matched_track["title"],
        utils.get_excluded_words_array())
        or utils.compare_string_to_exclusion(matched_track["album"],
                                             utils.get_excluded_words_array())):
        comparison_helper.excluded = True
        # NOTE: do we need to handle removing the excluded song if it was previously in the playlist but is now excluded?

    return matched_track

def match_with_subsonic_track(
        comparison_helper: ComparisonHelper, playlist_info, old_song_ids, subsonic_tracks_dict) -> ComparisonHelper:
    """compare spotify track to subsonic one"""
    matched_track = None
    if has_isrc(comparison_helper.track):
        matched_track = get_subsonic_track_via_mbid(comparison_helper, subsonic_tracks_dict)

    if matched_track is None and os.environ.get(constants.TEXT_COMAPRE_MATCHING_ENABLED, constants.TEXT_COMAPRE_MATCHING_ENABLED_DEFAULT_VALUE) == "1":
        logging.info(f'({threading.current_thread().ident}) Spotify track {comparison_helper.track["name"]} - {comparison_helper.artist_spotify["name"]} not found via ISRC; searching via string comparison...')
        matched_track = get_subsonic_track_via_string_compare(comparison_helper, subsonic_tracks_dict)

    if matched_track is None:
        return comparison_helper

    if comparison_helper.excluded:
        logging.info(f'({threading.current_thread().ident}) Spotify track {comparison_helper.track["name"]} - {comparison_helper.artist_spotify["name"]} was excluded from search')
        return comparison_helper

    if matched_track["id"] in old_song_ids:
        logging.info(
            '(%s) Track with id "%s" already in playlist "%s"',
            str(threading.current_thread().ident),
            matched_track["id"],
            playlist_info["name"])
        comparison_helper.song_ids.append(matched_track["id"])
        comparison_helper.found = True
        insert_result = database.insert_song(
            playlist_info,
            matched_track,
            comparison_helper.artist_spotify,
            comparison_helper.track)
    elif (matched_track["id"] not in comparison_helper.song_ids
          and matched_track["artist"] != ''
          and comparison_helper.track['name'] != ''
          and matched_track["album"] != ''
          and matched_track["title"] != ''):

        placeholder = matched_track["artist"] + " " + \
            matched_track["title"] + " " + matched_track["album"]

        comparison_helper.track_helper.append(placeholder)
        comparison_helper.found = True
        insert_result = database.insert_song(
            playlist_info, matched_track, comparison_helper.artist_spotify, comparison_helper.track)
        is_ignored = check_ignored(
            insert_result, matched_track, playlist_info)
        if is_ignored is False:
            comparison_helper.song_ids.append(matched_track["id"])
            logging.info(
                '(%s) Adding song "%s - %s - %s" to playlist "%s"',
                str(threading.current_thread().ident),
                matched_track["artist"],
                matched_track["title"],
                matched_track["album"],
                playlist_info["name"])
            check_pysonic_connection().createPlaylist(
                playlistId=playlist_info["subsonic_playlist_id"],
                songIds=comparison_helper.song_ids)

    return comparison_helper


def check_ignored(insert_result, song, playlist_info):
    if insert_result is not None:
        if insert_result["song_ignored"] is True:
            logging.info(
                '(%s) Skipping song "%s - %s - %s" because the matching song is marked as ignored "%s"',
                str(threading.current_thread().ident),
                song["artist"],
                song["title"],
                song["album"],
                playlist_info["name"])
            return True
        elif insert_result["album_ignored"] is True:
            logging.info(
                '(%s) Skipping song "%s - %s - %s" because the matching album is marked as ignored "%s"',
                str(threading.current_thread().ident),
                song["artist"],
                song["title"],
                song["album"],
                playlist_info["name"])
            return True
        elif insert_result["artist_ignored"] is True:
            logging.info(
                '(%s) Skipping song "%s - %s - %s" because the matching artist is marked as ignored "%s"',
                str(threading.current_thread().ident),
                song["artist"],
                song["title"],
                song["album"],
                playlist_info["name"])
            return True
        elif insert_result["ignored_pl"] is True:
            logging.info(
                '(%s) Skipping song "%s - %s - %s" because it is marked as ignored for playlist "%s"',
                str(threading.current_thread().ident),
                song["artist"],
                song["title"],
                song["album"],
                playlist_info["name"])
            return True
        elif insert_result["ignored_whole_pl"] is True:
            logging.info(
                '(%s) Skipping song "%s - %s - %s" because this playlist is marked as ignored"%s"',
                str(threading.current_thread().ident),
                song["artist"],
                song["title"],
                song["album"],
                playlist_info["name"])
            return True
    return False


def select_all_songs(
        missing_only=False,
        page=None,
        limit=None,
        order=None,
        asc=None,
        search=None,
        playlist_uuid=None):
    """get list of playlists and songs"""
    try:
        playlist_songs, count = database.select_all_songs(
            missing_only=missing_only,
            page=page,
            limit=limit,
            order=order,
            asc=asc,
            search=search,
            playlist_uuid=playlist_uuid)

        has_been_deleted = False

        ids = []
        for playlist in playlist_songs:
            if playlist.subsonic_playlist_id is not None and playlist.subsonic_playlist_id not in ids:
                ids.append(playlist.subsonic_playlist_id)

        for plid in ids:
            playlist_search, has_been_deleted = get_playlist_from_cache(plid)

        if has_been_deleted:
            return select_all_songs(
                missing_only=missing_only,
                page=page,
                limit=limit,
                order=order,
                asc=asc,
                search=search)
        return playlist_songs, count
    except SubsonicOfflineException as ex:
        raise ex


def select_all_playlists(spotipy_helper, page=None,
                         limit=None, order=None, asc=None):
    """get list of playlists"""
    try:
        all_playlists, count = database.select_all_playlists(
            page=page,
            limit=limit,
            order=order,
            asc=asc)

        has_been_deleted = False

        songs = []

        ids = []

        for playlist in all_playlists:
            playlist["image"] = ""
            if "subsonic_playlist_id" in playlist and playlist[
                    "subsonic_playlist_id"] is not None and playlist["subsonic_playlist_id"] not in ids:
                ids.append(playlist["subsonic_playlist_id"])
            if playlist["type"] == constants.JOB_ATT_ID or playlist["type"] == constants.JOB_AR_ID:
                spotify_artist = get_spotify_object_from_cache(
                    spotipy_helper.get_spotipy_client(), playlist["spotify_playlist_uri"])
                if spotify_artist is not None and "images" in spotify_artist and spotify_artist["images"] is not None and len(
                        spotify_artist["images"]) > 0:
                    playlist["image"] = spotify_artist["images"][0]["url"]
            elif playlist["type"] == constants.JOB_UP_ID:
                spotify_playlist = get_spotify_object_from_cache(
                    spotipy_helper.get_spotipy_client(), playlist["spotify_playlist_uri"])
                if spotify_playlist is not None and "images" in spotify_playlist and spotify_playlist["images"] is not None and len(
                        spotify_playlist["images"]) > 0:
                    playlist["image"] = spotify_playlist["images"][0]["url"]

        for plid in ids:
            playlist_search, has_been_deleted = get_playlist_from_cache(
                plid)

        if has_been_deleted:
            return select_all_playlists(spotipy_helper, page=None,
                                        limit=None, order=None, asc=None)
        return all_playlists, count
    except SubsonicOfflineException as ex:
        raise ex


def get_playlist_from_cache(key):
    has_been_deleted = False
    if key not in playlist_cache:
        try:
            playlist_search = check_pysonic_connection().getPlaylist(key)
            playlist_cache[key] = playlist_search["playlist"]["name"]
        except DataNotFoundError:
            pass

    if key not in playlist_cache:
        logging.warning(
            '(%s) Playlist id "%s" not found, may be you deleted this playlist from Subsonic?',
            str(threading.current_thread().ident), key)
        logging.warning(
            '(%s) Deleting Playlist with id "%s" from spotisub database.',
            str(threading.current_thread().ident), key)
        database.delete_playlist_relation_by_id(key)
        has_been_deleted = True
        return None, has_been_deleted
    return playlist_cache[key], has_been_deleted


def get_playlist_songs_ids_by_id(key):
    """get playlist songs ids by id"""
    songs = []
    playlist_search = None
    try:
        playlist_search = check_pysonic_connection().getPlaylist(key)
    except SubsonicOfflineException as ex:
        raise ex
    except DataNotFoundError:
        pass
    if playlist_search is None:
        logging.warning(
            '(%s) Playlist id "%s" not found, may be you ' +
            'deleted this playlist from Subsonic?',
            str(threading.current_thread().ident), key)
        logging.warning(
            '(%s) Deleting Playlist with id "%s" from spotisub database.',
            str(threading.current_thread().ident), key)
        database.delete_playlist_relation_by_id(key)
    elif (playlist_search is not None
            and "playlist" in playlist_search
            and "entry" in playlist_search["playlist"]
            and len(playlist_search["playlist"]["entry"]) > 0):
        songs = playlist_search["playlist"]["entry"]
        for entry in playlist_search["playlist"]["entry"]:
            if "id" in entry and entry["id"] is not None and entry["id"].strip(
            ) != "":
                if not is_ignored(
                        entry["id"],
                        playlist_search["playlist"]["name"]):
                    songs.append(entry["id"])

    return songs


def is_ignored(subsonic_song_id, playlist_name):
    songs, count = database.select_all_songs(subsonic_song_id=subsonic_song_id)
    for song in songs:
        if song.ignored:
            return True
        elif song.spotify_album_ignored:
            return True
        elif song.ignored_pl and song.subsonic_playlist_name.strip().lower() == playlist_name.strip().lower():
            return True
        else:
            for artist_ignored in song.spotify_artist_ignored.split(","):
                if artist_ignored.strip().lower() == '1':
                    return True
    return False


def remove_subsonic_deleted_playlist():
    """fix user manually deleted playlists"""

    spotisub_playlists, count = database.select_all_playlists()
    spotisub_songs, count = database.select_all_songs()

    ids = []

    for row1 in spotisub_playlists:
        if row1["subsonic_playlist_id"] is not None and row1["subsonic_playlist_id"] not in ids:
            ids.append(row1["subsonic_playlist_id"])

    for row2 in spotisub_songs:
        if row2.subsonic_playlist_id is not None and row2.subsonic_playlist_id not in ids:
            ids.append(row2.subsonic_playlist_id)

    for key in ids:
        playlist_search = None
        try:
            playlist_search = check_pysonic_connection().getPlaylist(key)
        except SubsonicOfflineException as ex:
            raise ex
        except DataNotFoundError:
            pass
        if playlist_search is None:
            logging.warning(
                '(%s) Playlist id "%s" not found, may be you ' +
                'deleted this playlist from Subsonic?',
                str(threading.current_thread().ident), key)
            logging.warning(
                '(%s) Deleting Playlist with id "%s" from spotisub database.',
                str(threading.current_thread().ident), key)
            database.delete_playlist_relation_by_id(key)

    # DO we really need to remove spotify songs even if they are not related to any playlist?
    # This can cause errors when an import process is running
    # I will just leave spotify songs saved in Spotisub database for now


def load_artist(uuid, spotipy_helper, page=None,
                limit=None, order=None, asc=None):
    artist_db, songs, count = database.get_artist_and_songs(
        uuid, page=page, limit=limit, order=order, asc=asc)
    sp = None

    spotify_artist = get_spotify_object_from_cache(
        spotipy_helper.get_spotipy_client(), artist_db.spotify_uri)

    artist = {}
    artist["uuid"] = artist_db.uuid
    artist["name"] = artist_db.name
    artist["ignored"] = artist_db.ignored
    artist["genres"] = ""
    artist["url"] = ""
    artist["image"] = ""
    artist["popularity"] = ""
    if spotify_artist is not None:
        if "genres" in spotify_artist:
            artist["genres"] = ", ".join(spotify_artist["genres"])
        if "popularity" in spotify_artist:
            artist["popularity"] = str(spotify_artist["popularity"]) + "%"
        if "external_urls" in spotify_artist and "spotify" in spotify_artist["external_urls"]:
            artist["url"] = spotify_artist["external_urls"]["spotify"]
        if "images" in spotify_artist and len(spotify_artist["images"]) > 0:
            artist["image"] = spotify_artist["images"][0]["url"]
    return artist, songs, count


def load_album(uuid, spotipy_helper, page=None,
               limit=None, order=None, asc=None):
    album_db, songs, count = database.get_album_and_songs(
        uuid, page=page, limit=limit, order=order, asc=asc)
    sp = None

    spotify_album = get_spotify_object_from_cache(
        spotipy_helper.get_spotipy_client(), album_db.spotify_uri)

    album = {}
    album["uuid"] = album_db.uuid
    album["name"] = album_db.name
    album["ignored"] = album_db.ignored
    album["url"] = ""
    album["image"] = ""
    album["release_date"] = ""
    if spotify_album is not None:
        if "release_date" in spotify_album:
            album["release_date"] = spotify_album["release_date"]
        if "external_urls" in spotify_album and "spotify" in spotify_album["external_urls"]:
            album["url"] = spotify_album["external_urls"]["spotify"]
        if "images" in spotify_album and len(spotify_album["images"]) > 0:
            album["image"] = spotify_album["images"][0]["url"]

    return album, songs, count


def load_song(uuid, spotipy_helper, page=None,
              limit=None, order=None, asc=None):
    song_db, songs, count = database.get_song_and_playlists(
        uuid, page=page, limit=limit, order=order, asc=asc)
    sp = None

    spotify_song = get_spotify_object_from_cache(
        spotipy_helper.get_spotipy_client(), song_db.spotify_uri)

    song = {}
    song["uuid"] = song_db.uuid
    song["name"] = song_db.title
    song["ignored"] = song_db.ignored
    song["url"] = ""
    song["image"] = ""
    song["popularity"] = ""
    song["preview"] = ""

    if spotify_song is not None:
        if "preview_url" in spotify_song:
            song["preview_url"] = spotify_song["preview_url"]
        if "popularity" in spotify_song:
            song["popularity"] = str(spotify_song["popularity"]) + "%"
        if "external_urls" in spotify_song and "spotify" in spotify_song["external_urls"]:
            song["url"] = spotify_song["external_urls"]["spotify"]

    if len(songs) > 0:
        spotify_album = get_spotify_object_from_cache(
            spotipy_helper.get_spotipy_client(), songs[0].spotify_album_uri)

        if spotify_album is not None:
            if "images" in spotify_album and len(spotify_album["images"]) > 0:
                song["image"] = spotify_album["images"][0]["url"]

    return song, songs, count


def select_playlist_info_by_uuid(spotipy_helper, uuid):
    playlist_info_db = database.select_playlist_info_by_uuid(uuid)
    playlist_info = {}
    playlist_info["uuid"] = playlist_info_db.uuid
    playlist_info["subsonic_playlist_id"] = playlist_info_db.subsonic_playlist_id
    playlist_info["subsonic_playlist_name"] = playlist_info_db.subsonic_playlist_name
    playlist_info["spotify_playlist_uri"] = playlist_info_db.spotify_playlist_uri
    playlist_info["ignored"] = playlist_info_db.ignored
    playlist_info["type"] = playlist_info_db.type
    playlist_info["type_desc"] = string.capwords(
        playlist_info_db.type.replace("_", " "))
    playlist_info["image"] = ""
    if playlist_info["type"] == constants.JOB_ATT_ID or playlist_info["type"] == constants.JOB_AR_ID:
        spotify_artist = get_spotify_object_from_cache(
            spotipy_helper.get_spotipy_client(),
            playlist_info["spotify_playlist_uri"])
        if spotify_artist is not None and "images" in spotify_artist and len(
                spotify_artist["images"]) > 0:
            playlist_info["image"] = spotify_artist["images"][0]["url"]
    elif playlist_info["type"] == constants.JOB_UP_ID:
        spotify_playlist = get_spotify_object_from_cache(
            spotipy_helper.get_spotipy_client(),
            playlist_info["spotify_playlist_uri"])
        if spotify_playlist is not None and "images" in spotify_playlist and len(
                spotify_playlist["images"]) > 0:
            playlist_info["image"] = spotify_playlist["images"][0]["url"]
    return playlist_info


def set_ignore(type, uuid, value):
    if type == 'song':
        database.update_ignored_song(uuid, value)
    elif type == 'artist':
        database.update_ignored_artist(uuid, value)
    elif type == 'album':
        database.update_ignored_album(uuid, value)
    elif type == 'song_pl':
        database.update_ignored_song_pl(uuid, value)
    elif type == 'playlist':
        database.update_ignored_playlist(uuid, value)


def download_song(spotipy_helper, uri):
    sp = spotipy_helper.get_spotipy_client()
    track = get_spotify_object_from_cache(sp, uri, force=True)
    if "external_urls" in track and track["external_urls"] is not None and "spotify" in track[
            "external_urls"] and track["external_urls"]["spotify"] is not None:
        spotdl_executor.submit(
            spotdl_helper.download_track,
            track["external_urls"]["spotify"])
        return True
    else:
        return False


spotify_cache = load_spotify_cache_from_file()
