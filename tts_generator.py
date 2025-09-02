import argparse
import json
import os
import subprocess
import re

def clean_text(text):
    """Applies a series of cleaning steps to the input text."""
    # 1. Remove parenthetical remarks (e.g., (laughs))
    text = re.sub(r'\(.*?\)', '', text)
    # 2. Remove bracketed remarks (e.g., [sighs])
    text = re.sub(r'\[.*?\]', '', text)
    # 3. Replace ellipses with a period for a more natural pause
    text = text.replace('...', '.')
    # 4. Normalize whitespace
    text = ' '.join(text.split())
    # 5. Remove any characters that aren't standard for speech
    text = re.sub(r'[^a-zA-Z0-9\s.,!?-]', '', text)
    # 6. A final trim
    return text.strip()

def get_speaker_wav_paths(personas_file):
    """Loads speaker wav paths from the personas JSON file."""
    with open(personas_file, "r", encoding="utf-8") as f:
        personas = json.load(f)
    
    speaker_wavs = {}
    for person in personas:
        speaker_name = person.get("name")
        wav_path = person.get("speaker_wav_path")
        if speaker_name and wav_path:
            # Adjust path from /data to the user's home directory
            adjusted_path = wav_path.replace("/data", os.path.expanduser("~"))
            if not os.path.exists(adjusted_path):
                print(f"Warning: Speaker wav file not found at {adjusted_path}")
                continue
            speaker_wavs[speaker_name] = adjusted_path
    return speaker_wavs

def generate_speech_xtts(text, output_file, speaker_wav_path):
    """Generates speech using Coqui-XTTS voice cloning."""
    model_name = "tts_models/multilingual/multi-dataset/xtts_v2"
    tts_executable = os.path.join(os.path.expanduser("~"), "podcast_env/bin/tts")

    print(f"--- Generating speech for: '{text[:45]}...'")
    try:
        command = [
            tts_executable,
            "--text", text,
            "--model_name", model_name,
            "--speaker_wav", speaker_wav_path,
            "--language_idx", "en",
            "--out_path", output_file
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error generating speech: {e}\nStderr: {e.stderr}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred in generate_speech_xtts: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Generate TTS audio from a podcast transcript using Coqui-XTTS.")
    parser.add_argument("transcript_file", type=str, help="The JSON transcript file to process.")
    args = parser.parse_args()

    transcript_file = args.transcript_file
    output_mp3_file = os.path.splitext(transcript_file)[0] + ".mp3"
    personas_file = os.path.join(os.path.expanduser("~"), "personas.json")

    print("--- Starting TTS generation with XTTS ---")
    if os.path.exists(output_mp3_file):
        os.remove(output_mp3_file)

    try:
        speaker_wavs = get_speaker_wav_paths(personas_file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading personas file: {e}")
        return

    try:
        with open(transcript_file, "r", encoding="utf-8") as f:
            transcript = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading transcript file: {e}")
        return

    audio_files = []
    temp_dir = "/tmp/tts_audio"
    os.makedirs(temp_dir, exist_ok=True)

    # Generate a silence file for pauses
    silence_duration = 0.5  # seconds
    silence_file = os.path.join(temp_dir, "silence.wav")
    print(f"--- Generating {silence_duration}s silence file ---")
    try:
        silence_command = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
            "-t", str(silence_duration), "-q:a", "2", silence_file
        ]
        subprocess.run(silence_command, check=True, capture_output=True, text=True)
    except Exception as e:
        print(f"Error generating silence file: {e}. Pauses will not be added.")
        silence_file = None

    for i, entry in enumerate(transcript):
        speaker = entry.get("speaker")
        line = entry.get("line")

        if not speaker or not line or speaker == "Moderator":
            continue

        speaker_wav_path = speaker_wavs.get(speaker)
        if not speaker_wav_path:
            print(f"Warning: No speaker wav path found for {speaker}. Skipping line.")
            continue

        output_wav_file = os.path.join(temp_dir, f'line_{i}.wav')
        print(f"--- Processing line {i+1}/{len(transcript)} (Speaker: {speaker}) ---")
        cleaned_line = clean_text(line)
        if cleaned_line and generate_speech_xtts(cleaned_line, output_wav_file, speaker_wav_path):
            audio_files.append(output_wav_file)

    if not audio_files:
        print("No audio files were generated. Aborting combination.")
        return

    print(f"--- Combining {len(audio_files)} audio files into MP3 ---")
    file_list_path = os.path.join(temp_dir, "file_list.txt")
    with open(file_list_path, "w") as f:
        for i, file in enumerate(audio_files):
            f.write(f"file '{file}'\n")
            # Add silence between clips, but not after the last one
            if silence_file and i < len(audio_files) - 1:
                f.write(f"file '{silence_file}'\n")

    try:
        command = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", file_list_path, "-acodec", "libmp3lame", "-q:a", "2", output_mp3_file]
        subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"--- Podcast Audio Generation Finished ---")
        print(f"Podcast saved to {output_mp3_file}")
    except Exception as e:
        print(f"Error combining audio files: {e}")
    finally:
        print("--- Cleaning up temporary files ---")
        # Clean up temp files
        # for file in audio_files:
        #     os.remove(file)
        # os.remove(file_list_path)


if __name__ == "__main__":
    main()