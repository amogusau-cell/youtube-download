**Description**
Easily download YouTube videos or playlists with ease.
Playlist downloader will download videos that can be added to jellyfin as a show.

Converting support in order to maximize support for playing videos without transcoding.

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

Saves the copied links when a key combination is pressed. (For Mac its command+B)


Prefix_adder.py:

Adds prefixes for every file in a folder.


Subtitle.py:

Separates the subtitles from the video file.

Use this command to get cookies from the browser:
yt-dlp --cookies-from-browser chrome --cookies cookies.txt

**Known Issues**
When pressing ctrl+c when yt-dlp is downloading a video the yt-dlp process stops but the script continues running.
So it is recommended to stop the script when the conversation is happening instead of when the video is being downloaded.

**Before Use**
Make sure there is no other video or unfinished download file inside download_temp file.
You can have the last unfinished download file but any other video file can break the script.
For example

yt-dlp downloads video A and there is video B inside download_temp the script will break.
If there is video A's .part file then yt-dlp will automatically continue the download so it is fine.