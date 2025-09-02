#!/usr/bin/env python3
"""
Podcast Generator v5 - CLI Runner (Async)
------------------------------------------------------------
This script runs the podcast generation logic as a command-line tool.
It uses the async podcast_engine library for its core functionality.
"""
from __future__ import annotations

import argparse
import json
import asyncio
import aiohttp

# Import the core engine
from podcast_engine import (
    Persona,
    Podcast,
    print_logger, 
    PERSONAS_FILE
)

def cli_transcript_callback(speaker: str, line: str, timestamp: str):
    """Prints transcript lines to the console."""
    print(f"[{timestamp}] {speaker}: {line}")

async def main():
    parser = argparse.ArgumentParser(description="Generate a podcast from the command line.")
    parser.add_argument("--topic", type=str, required=True, help="Podcast topic.")
    parser.add_argument("--num_turns", type=int, default=10, help="Number of turns.")
    parser.add_argument("--timeout", type=int, default=180, help="Timeout for AI model calls in seconds.")
    parser.add_argument("--debug-bids", action="store_true", help="Print raw bid responses for debugging.")
    parser.add_argument("--generate-audio", action="store_true", help="Generate audio for the podcast.")
    args = parser.parse_args()

    try:
        with open(PERSONAS_FILE, "r", encoding="utf-8") as f:
            personas_data = json.load(f)
        personas = [Persona(**p) for p in personas_data]
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading personas from {PERSONAS_FILE}: {e}")
        return

    # Create the Podcast instance
    podcast = Podcast(
        topic=args.topic, 
        personas=personas, 
        num_turns=args.num_turns, 
        timeout=args.timeout, 
        log_callback=print_logger,
        transcript_callback=cli_transcript_callback,
        injection_queue=asyncio.Queue(), # Pass a dummy queue
        generate_audio=args.generate_audio,
        debug_bids=args.debug_bids
    )
    
    # Create an aiohttp session and run the podcast
    async with aiohttp.ClientSession() as session:
        await podcast.run(session)

if __name__ == "__main__":
    asyncio.run(main())