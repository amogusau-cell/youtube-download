**Description**
Easily download youtube videos or playlists with ease.
Playlist downloader will download videos that can be added to jellyfin as a show.

Converting support in order to maximaze support for playing videos without transcoding.

**How To Use**

Checker.py:

Checks all the videos for compatibility.
Change "CHECK_FOLDER" to check a different folder.


Converter.py:

Converts all the videos inside "INPUT_FOLDER", encodes them and puts them to "OUTPUT_FOLDER".


Download_playlist.py:

Downloads a playlist with jellyfin support. Change "PLAYLIST_URL" to use a different playlist.
Change paths or config at the top level for your liking.


Download_V2.py:

Downloads all the videos in "JSON_PATH". Use with linksaver.py is recommended.


Linksaver.py:

Saves the copied links when a key combination is pressed. (For mac its command+B)


Prefix_adder.py:

Adds prefixes for every file in a folder.


Subtitle.py:

Seperates the subtitles from the video file.
