#!/usr/bin/env python3
"""
Podcast Generator v5 - Core Async Engine with Audio
------------------------------------------------------------
This library contains the core classes and logic for generating podcasts,
including live, asynchronous audio generation.
"""
from __future__ import annotations

import json
import os
import random
import re
import asyncio
import aiohttp
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any

# --- Default Logger ---
def print_logger(message: str): print(message)

# --- Configuration ---
INTERRUPTION_THRESHOLD = 6
TRANSCRIPT_LOG_FILE = "podcast_transcript.log"
PERSONAS_FILE = "personas.json"
OLLAMA_API_URL = "http://localhost:11434/api/generate"
TEMP_AUDIO_DIR = "/tmp/podcast_audio"

# --- Utility Functions ---
def clean_text_for_tts(text: str) -> str:
    """Applies a series of cleaning steps to prepare text for TTS."""
    text = re.sub(r'\(.*\)', '', text) # Remove parenthetical remarks
    text = re.sub(r'\[.*?\]', '', text) # Remove bracketed remarks
    text = text.replace('...', '.') # Replace ellipses
    text = ' '.join(text.split()) # Normalize whitespace
    text = re.sub(r'[^a-zA-Z0-9\s.,!?-]', '', text) # Remove non-standard chars
    return text.strip()

# --- Data Classes ---
@dataclass
class Persona:
    name: str
    personality: str
    stance: str
    age: int
    gender: str
    model: str = "llama3:8b"
    background: str = ""
    speaker_wav_path: str = ""
    relationships: Dict[str, str] = field(default_factory=dict)

@dataclass
class InterruptionBid:
    importance: int; interrupt_after_word: str; interruption_text: str; interrupter_name: str

# --- Core Podcast Logic (Async with Audio) ---

class Character:
    # ... (Character class is unchanged from the async refactor)
    def __init__(self, persona: Persona, topic: str, all_personas: List[Persona], session: aiohttp.ClientSession, log_callback, debug_bids: bool = False):
        self.persona, self.topic, self.all_personas, self.session, self.log, self.debug_bids = persona, topic, all_personas, session, log_callback, debug_bids
    async def _call_ollama(self, prompt: str) -> str:
        self.log(f"    -> Calling model {self.persona.model} for {self.persona.name}...")
        payload = {"model": self.persona.model, "prompt": prompt, "stream": False}
        try:
            async with self.session.post(OLLAMA_API_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    self.log(f"    <- Model call for {self.persona.name} successful.")
                    full_response = data.get("response", "").strip()
                    return re.sub(rf"^\s*{re.escape(self.persona.name)}[:,]?\s*", "", full_response, flags=re.IGNORECASE).strip()
                else:
                    self.log(f"[!] Error: Ollama API returned status {response.status}: {await response.text()}")
                    return f"[Error: API Error {response.status}]"
        except Exception as e: self.log(f"[!] Error during model call: {e}"); return "[Error: Connection Failed]"
    async def generate_full_response(self, ch: List[str], ct: int, tt: int) -> str:
        op = [p.name for p in self.all_personas if p.name != self.persona.name]
        hs = "\n".join(ch[-15:])
        ls = ch[-1].split(":")[0] if ch else "the moderator"
        
        relationship_str = ""
        if ls in self.persona.relationships:
            relationship_str = f"Your defined relationship with {ls} is: '{self.persona.relationships[ls]}'. Let this influence your tone."

        p = (f"You are {self.persona.name}. You are on a casual podcast with your friends: {op}. "
             f"This is turn {ct} of {tt}. Your personality is: {self.persona.personality}. "
             f"Your stance on '{self.topic}': {self.persona.stance}.\n\n"
             f"The tone is friendly and informal. Avoid formal pleasantries. Just make your point directly.\n"
             f"{relationship_str}\n\n"
             f"Review the conversation so far and introduce a NEW argument. Don't repeat old points.\n"
             f"Conversation so far:\n{hs}\n\n"
             f"It's your turn. Address {ls} and keep your response to 1-3 sentences. "
             f"IMPORTANT: You MUST end your entire response with the line 'NEXT_SPEAKER: [name]', choosing a name from {op}. "
             f"Do not add any other text after this line.")
        return await self._call_ollama(p)
    def _robust_json_parse(self, r: str) -> Optional[Dict[str, Any]]:
        # ... (logic is unchanged)
        m = re.search(r"\{{.*?\}}", r, re.DOTALL); 
        if not m: return None
        js = m.group(0).replace("'", '"'); js = re.sub(r",(\s*[\}\]])", r"\1", js); js = re.sub(r'\|(?!["\\/bfnrtu])', r'\\\\', js)
        try: return json.loads(js)
        except json.JSONDecodeError: return None
    async def bid_for_interruption(self, si: str, tr: str, ch: List[str], ct: int, tt: int) -> Optional[InterruptionBid]:
        # ... (prompt logic is unchanged)
        hs = "\n".join(ch[-15:]); p = (f"You are {self.persona.name}. This is turn {ct} of {tt}. Decide if you should interrupt.\n"
                                     f"Conversation so far:\n{hs}\n\n{si} is about to say:\n\"{tr}\"\n\n"
                                     f"Respond with ONLY JSON. Example: {{'importance': 8, 'interrupt_after_word': 'tech', 'interruption_text': 'Wait!'}}\n"
                                     f"If not interrupting: {{'importance': 1, 'interrupt_after_word': '', 'interruption_text': ''}}")
        r = await self._call_ollama(p); bd = self._robust_json_parse(r)
        if not bd: return None
        try: return InterruptionBid(importance=int(bd.get("importance",0)),interrupt_after_word=(bd.get("interrupt_after_word")or"").strip(),interrupt_text=(bd.get("interruption_text")or"").strip(),interrupter_name=self.persona.name)
        except (ValueError, KeyError): return None

class Podcast:
    def __init__(self, topic: str, personas: List[Persona], num_turns: int, timeout: int, log_callback, transcript_callback, injection_queue: asyncio.Queue, generate_audio: bool = False, debug_bids: bool = False):
        self.topic, self.personas, self.num_turns, self.timeout, self.log, self.transcript_callback, self.injection_queue, self.generate_audio, self.debug_bids = topic, personas, num_turns, timeout, log_callback, transcript_callback, injection_queue, generate_audio, debug_bids
        self.transcript: List[Dict[str, str]] = []
        self.conversation_history: List[str] = []
        self.speaker_wavs: Dict[str, str] = {}
        self.generated_audio_files: List[str] = []
        self.silence_clip_path: Optional[str] = None
        self.analytics = {"word_counts": {p.name: 0 for p in self.personas}, "turn_counts": {p.name: 0 for p in self.personas}, "interruption_counts": {p.name: 0 for p in self.personas}}

    def _update_analytics(self, speaker: str, line: str):
        self.analytics["word_counts"][speaker] = self.analytics["word_counts"].get(speaker, 0) + len(line.split())
        if speaker != "Moderator" and speaker != "Director":
            self.analytics["turn_counts"][speaker] = self.analytics["turn_counts"].get(speaker, 0) + 1

    def _load_speaker_wavs(self):
        self.log("--- Loading speaker WAV paths ---")
        for p in self.personas:
            if p.speaker_wav_path and os.path.exists(p.speaker_wav_path):
                self.speaker_wavs[p.name] = p.speaker_wav_path
            else: self.log(f"[!] Warning: WAV path for {p.name} not found or not specified. They will be silent.")

    async def _generate_silence_clip(self):
        self.log("--- Generating silence clip for pacing ---")
        os.makedirs(TEMP_AUDIO_DIR, exist_ok=True)
        path = os.path.join(TEMP_AUDIO_DIR, "silence.wav")
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.5", "-q:a", "2", path]
        process = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, stderr = await process.communicate()
        if process.returncode == 0: self.silence_clip_path = path; self.log("    -> Silence clip generated.")
        else: self.log(f"[!] Error generating silence clip: {stderr.decode()}")

    async def _generate_audio_for_line(self, line_text: str, speaker: str, output_filename: str):
        self.log(f"    -> Generating audio for {speaker}... ")
        wav_path = self.speaker_wavs.get(speaker)
        if not wav_path: self.log(f"    [!] Skipped: No WAV path for {speaker}."); return

        cleaned_text = clean_text_for_tts(line_text)
        if not cleaned_text: self.log(f"    [!] Skipped: Line for {speaker} was empty after cleaning."); return

        tts_executable = os.path.join(os.path.expanduser("~"), "podcast_env/bin/tts")
        output_path = os.path.join(TEMP_AUDIO_DIR, output_filename)
        cmd = [tts_executable, "--text", cleaned_text, "--model_name", "tts_models/multilingual/multi-dataset/xtts_v2", "--speaker_wav", wav_path, "--language_idx", "en", "--out_path", output_path]
        
        process = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, stderr = await process.communicate()
        if process.returncode == 0: self.generated_audio_files.append(output_path); self.log(f"    <- Audio for {speaker} generated.")
        else: self.log(f"[!] TTS generation failed for {speaker}: {stderr.decode()}")

    def _add_to_transcript(self, speaker: str, line: str, line_index: int):
        timestamp = datetime.now().strftime("%H:%M:%S"); entry = {"timestamp": timestamp, "speaker": speaker, "line": line}
        self.transcript.append(entry); self.conversation_history.append(f"{speaker}: {line}")
        self.transcript_callback(speaker, line, timestamp)
        with open(TRANSCRIPT_LOG_FILE, "a", encoding="utf-8") as f: f.write(f"[{timestamp}] {speaker}: {line}\n"
)
        if self.generate_audio: asyncio.create_task(self._generate_audio_for_line(line, speaker, f"line_{line_index}.wav"))

    async def _finalize_audio(self):
        self.log(f"--- Finalizing Audio: Combining {len(self.generated_audio_files)} clips ---")
        if not self.generated_audio_files: self.log("[!] No audio clips were generated."); return

        # Wait for any lingering TTS tasks to finish
        await asyncio.sleep(2)
        self.generated_audio_files.sort()

        file_list_path = os.path.join(TEMP_AUDIO_DIR, "file_list.txt")
        with open(file_list_path, "w") as f:
            for i, audio_file in enumerate(self.generated_audio_files):
                f.write(f"file '{os.path.abspath(audio_file)}'\n")
                if self.silence_clip_path and i < len(self.generated_audio_files) - 1:
                    f.write(f"file '{os.path.abspath(self.silence_clip_path)}'\n")
        
        date = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_mp3_file = f"podcast_{self.topic.replace(' ', '_')}_{date}.mp3"
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", file_list_path, "-acodec", "libmp3lame", "-q:a", "2", output_mp3_file]
        process = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, stderr = await process.communicate()
        if process.returncode == 0: self.log(f"\n--- Podcast Audio Generation Finished: {output_mp3_file} ---")
        else: self.log(f"[!] Error combining audio files: {stderr.decode()}")

    async def run(self, session: aiohttp.ClientSession):
        self.characters = {p.name: Character(p, self.topic, self.personas, session, self.log, self.debug_bids) for p in self.personas}
        if self.generate_audio: self._load_speaker_wavs(); await self._generate_silence_clip()

        self.log(f"--- Podcast starting ---"); line_idx = 0
        self._add_to_transcript("Moderator", f"Welcome! Today's topic is: {self.topic}.", line_idx); line_idx+=1
        current_speaker_name = self.personas[0].name

        for i in range(self.num_turns):
            # --- Director Injection Check ---
            while not self.injection_queue.empty():
                try:
                    injection_text = self.injection_queue.get_nowait()
                    self.log(f"--- Director Injection: '{injection_text}' ---")
                    self._add_to_transcript("Director", injection_text, line_idx)
                    line_idx += 1
                except asyncio.QueueEmpty:
                    break # Should not happen with this loop structure, but safe to have

            for i in range(self.num_turns):
            # --- Director Injection Check ---
            if not self.injection_queue.empty():
                try:
                    injection_text = self.injection_queue.get_nowait()
                    self.log(f"\n--- Turn {i+1}/{self.num_turns} (Director's Intervention as Moderator) ---")
                    self._add_to_transcript("Moderator", injection_text, line_idx)
                    line_idx += 1
                except asyncio.QueueEmpty:
                    pass # Should not happen with this loop structure
            else:
                self.log(f"\n--- Turn {i+1}/{self.num_turns} (Floor: {current_speaker_name}) ---")
            
            potential_response = await self.characters[current_speaker_name].generate_full_response(self.conversation_history, i + 1, self.num_turns)

            self.log("    Gathering interruption bids concurrently"); bid_tasks = []
            for p in [p for p in self.personas if p.name != current_speaker_name]:
                bid_tasks.append(self.characters[p.name].bid_for_interruption(current_speaker_name, potential_response, self.conversation_history, i + 1, self.num_turns))
            all_bids = await asyncio.gather(*bid_tasks); interrupt_bids = [b for b in all_bids if b and b.importance >= INTERRUPTION_THRESHOLD]
            self.log(f"    ... all {len(bid_tasks)} bids received.")

            if interrupt_bids:
                winning_bid = max(interrupt_bids, key=lambda x: x.importance)
                self.log(f"--- Interruption by {winning_bid.interrupter_name}! ---")
                self._add_to_transcript(current_speaker_name, potential_response.split("NEXT_SPEAKER:")[0].strip(), line_idx); line_idx+=1
                self._add_to_transcript(winning_bid.interrupter_name, winning_bid.interruption_text, line_idx); line_idx+=1
                current_speaker_name = winning_bid.interrupter_name
            else:
                cleaned_response = re.sub(r"NEXT_SPEAKER:.*", "", potential_response, flags=re.IGNORECASE | re.DOTALL).strip()
                self._add_to_transcript(current_speaker_name, cleaned_response, line_idx); line_idx+=1
                # ... (NEXT_SPEAKER parsing logic is unchanged)
                next_speaker_match = re.search(r"NEXT_SPEAKER:\s*\[?(.*?)\]?$", potential_response, re.IGNORECASE)
                if next_speaker_match:
                    candidate = next_speaker_match.group(1).strip(); normalized_candidate = re.sub(r'[^a-zA-Z0-9]', '', candidate).lower()
                    persona_map = {re.sub(r'[^a-zA-Z0-9]', '', p.name).lower(): p.name for p in self.personas}
                    if normalized_candidate in persona_map and persona_map[normalized_candidate] != current_speaker_name:
                        current_speaker_name = persona_map[normalized_candidate]
                    else:
                        self.log(f"  [!] Nominated speaker '{candidate}' invalid. Choosing randomly."); current_speaker_name = random.choice([p.name for p in self.personas if p.name != current_speaker_name])
                else:
                    self.log("  [!] No next speaker nominated. Choosing randomly."); current_speaker_name = random.choice([p.name for p in self.personas if p.name != current_speaker_name])

        if self.generate_audio: await self._finalize_audio()
        date = datetime.now().strftime("%Y%m%d_%H%M%S"); output_file = f"podcast_{self.topic.replace(' ', '_')}_{date}.json"
        try:
            with open(output_file, "w") as f: json.dump(self.transcript, f, indent=4, ensure_ascii=False)
            self.log(f"\nTranscript saved to {output_file}")
        except Exception as e: self.log(f"Error saving transcript: {e}")
