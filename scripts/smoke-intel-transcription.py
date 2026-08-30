"""Native Intel transcription smoke test for release CI."""

from __future__ import annotations

import platform
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise RuntimeError("Intel transcription smoke test requires native macOS x86_64")

    import ctranslate2
    import faster_whisper
    import onnxruntime
    import pyaudio
    from faster_whisper import WhisperModel

    audio = pyaudio.PyAudio()
    audio.terminate()

    with tempfile.TemporaryDirectory(prefix="xpdite-intel-smoke-") as temp_dir:
        temp_root = Path(temp_dir)
        source_audio = temp_root / "speech.aiff"
        wav_audio = temp_root / "speech.wav"
        subprocess.run(
            ["/usr/bin/say", "-o", str(source_audio), "Xpdite transcription is ready"],
            check=True,
        )
        subprocess.run(
            [
                "/usr/bin/afconvert",
                "-f",
                "WAVE",
                "-d",
                "LEI16@16000",
                "-c",
                "1",
                str(source_audio),
                str(wav_audio),
            ],
            check=True,
        )

        model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(str(wav_audio), beam_size=1)
        transcript = " ".join(segment.text.strip() for segment in segments).strip()
        if not transcript:
            raise RuntimeError("Intel faster-whisper smoke fixture produced no transcript")

    print(
        "INTEL_TRANSCRIPTION_SMOKE_OK",
        ctranslate2.__version__,
        onnxruntime.__version__,
        faster_whisper.__version__,
    )


if __name__ == "__main__":
    main()
