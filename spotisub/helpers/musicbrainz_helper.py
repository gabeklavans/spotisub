"""Musicbrainz helper"""
import time
import logging


import musicbrainzngs
from musicbrainzngs.musicbrainz import ResponseError
from spotisub import spotisub
from spotisub import utils


# Disabling musicbrainz INFO log as we don't want to see ugly infos in the
# console
log = logging.getLogger("musicbrainzngs")
log.setLevel(40)

musicbrainzngs.set_useragent(
    "navidrome music",
    "0.1",
    "http://example.com/music")

def get_mbids_from_isrc(isrc: str) -> list:
    try:
        res = musicbrainzngs.get_recordings_by_isrc(isrc)
        time.sleep(0.25)
    except ResponseError as e:
        if "404" in str(e):
            logging.error(f'Spotify track with ISRC: {isrc} was not found in the MusicBrainz database. Consider manually submitting it.')
        elif "400" in str(e):
            logging.error(f'HTTP Error 400 from MusicBrainz API for ISRC: {isrc}.')
        else:
            utils.write_exception()
        return []
    except Exception:
        utils.write_exception()
        return []

    if "isrc" not in res:
        return []
    if "recording-list" not in res["isrc"]:
        return []

    return list(map(lambda rec: rec["id"], res["isrc"]["recording-list"]))

def get_isrc_by_id(song):
    """get isrc by id"""
    try:
        if ("musicBrainzId" in song
            and song["musicBrainzId"] is not None
                and song["musicBrainzId"] != ""):
            song = musicbrainzngs.get_recording_by_id(
                song["musicBrainzId"], includes=["isrcs"])
            time.sleep(1)
            if (song is not None and "recording" in song
                and song["recording"] is not None
                and "isrc-list" in song["recording"]
                and song["recording"]["isrc-list"] is not None
                    and len(song["recording"]["isrc-list"])) > 0:
                return song["recording"]["isrc-list"]
        return []
    except BaseException:
        utils.write_exception()
        return []
