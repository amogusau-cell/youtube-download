import os

FOLDER = "path/to/your/folder"
PREFIX = "Breaking Bad "

for filename in os.listdir(FOLDER):
    old_path = os.path.join(FOLDER, filename)

    if os.path.isfile(old_path):
        new_name = PREFIX + filename
        new_path = os.path.join(FOLDER, new_name)
        os.rename(old_path, new_path)
