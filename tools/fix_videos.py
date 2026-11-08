import os
import subprocess

SUBPROCESS_CREATION_FLAGS = (
    getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
)

def fix_videos(directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".mp4") and not file.startswith("fixed_"):
                input_path = os.path.join(root, file)
                output_path = os.path.join(root, f"fixed_{file}")
                
                print(f"Fixing {file}...")
                try:
                    # Try to remux the file cleanly.
                    cmd = [
                        'ffmpeg', '-y', '-i', input_path, 
                        '-c', 'copy', '-map', '0:v', '-map', '0:a?',
                        output_path
                    ]
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        creationflags=SUBPROCESS_CREATION_FLAGS,
                    )
                    
                    if result.returncode == 0:
                        os.replace(output_path, input_path)
                        print(f"✓ Repaired {file}.")
                    else:
                        if os.path.exists(output_path):
                            os.remove(output_path)
                        print(f"✗ Could not repair {file} (the file may be corrupted).")
                except Exception as e:
                    print(f"Error fixing {file}: {e}")

if __name__ == "__main__":
    target_dir = "downloads"
    if os.path.exists(target_dir):
        fix_videos(target_dir)
        print("\nRepair complete!")
    else:
        print("Downloads folder not found.")
