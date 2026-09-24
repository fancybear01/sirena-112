#!/usr/bin/env python3
"""Run the actual AI app with deterministic speech engines (test transport only)."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ai"))

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8090)
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--real", action="store_true", help="Use AI_STT/AI_TTS model environment instead")
args = parser.parse_args()

from app.voice.speech import SpeechPipeline, ScriptedRecognizer, SilenceSynthesizer, use_pipeline
from app.main import create_app
import uvicorn

if not args.real:
    use_pipeline(SpeechPipeline(ScriptedRecognizer((
        "Служба сто двенадцать, назовите адрес происшествия",
        "Пострадавшие есть, помощь нужна?",
    )), SilenceSynthesizer()))
uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
