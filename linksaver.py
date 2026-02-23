# YouTube Link Saver
# Press Command+B (Cmd+B) to save YouTube links from clipboard
# Press ESC to exit

from pynput import keyboard
import pyperclip
import json
import os

JSON_FILE = "yt_links.json"

def load_links():
    """Load existing links from JSON file"""
    if not os.path.exists(JSON_FILE):
        return []
    with open(JSON_FILE, "r") as f:
        return json.load(f)

def save_links(links):
    """Save links to JSON file"""
    with open(JSON_FILE, "w") as f:
        json.dump(links, f, indent=4)

def save_youtube_link():
    """Save YouTube link from clipboard"""
    clipboard = pyperclip.paste().strip()
    
    # Check if it's a valid YouTube link
    if ("youtube.com/watch" in clipboard or "youtu.be/" in clipboard):
        links = load_links()
        if clipboard not in links:
            links.append(clipboard)
            save_links(links)
            print(f"✓ Saved: {clipboard}")
            print(f"📊 Total links: {len(links)}")
        else:
            print("⚠ Link already exists")
    else:
        print("❌ Not a YouTube link - ignored")
        print(f"   Clipboard: {clipboard[:60]}..." if len(clipboard) > 60 else f"   Clipboard: {clipboard}")

current_keys = set()

def on_press(key):
    """Handle key press"""
    current_keys.add(key)
    
    # Check for Command+B (Cmd+B)
    if keyboard.Key.cmd in current_keys or keyboard.Key.cmd_l in current_keys or keyboard.Key.cmd_r in current_keys:
        try:
            if hasattr(key, 'char') and key.char == 'b':
                print("\n🔥 Command+B detected!")
                save_youtube_link()
        except AttributeError:
            pass

def on_release(key):
    """Handle key release"""
    current_keys.discard(key)
    
    # Exit on ESC
    if key == keyboard.Key.esc:
        print("\n⏹ Stopping listener... Goodbye!")
        return False

def main():
    """Start the keyboard listener"""
    print("="*60)
    print("🎧 YouTube Link Saver - ACTIVE")
    print("="*60)
    
    # Show existing links count
    existing = load_links()
    print(f"📋 Currently saved: {len(existing)} link(s)")
    
    print("\n📝 Instructions:")
    print("  1. Copy a YouTube link")
    print("  2. Press Command+B (Cmd+B) to save it")
    print("  3. Press ESC to exit")
    print("\n" + "="*60 + "\n")
    
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹ Stopped by user")
