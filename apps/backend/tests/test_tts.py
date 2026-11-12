"""TTS tests: the ElevenLabs client's fail-closed rules, streaming, and the
ffmpeg voice-note encode, all against a fake ElevenLabs.

Hermetic by design: no keys and no network. The only real dependency exercised
is `ffmpeg`, and only to encode audio this test builds itself.
"""

from __future__ import annotations

import io
import json
import os
import threading
import time
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.modules.voice import audio
from app.modules.voice import tts


def _tiny_wav(seconds: float = 0.05, rate: int = 16000) -> bytes:
    """A valid WAV built in memory — enough for ffmpeg to decode."""
    frames = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


class FakeEleven:
    """A local stand-in for api.elevenlabs.io returning raw PCM."""

    def __init__(self, payload: bytes = b"\x00\x01" * 240, status: int = 200,
                 dribble: bool = False):
        self.payload = payload
        self.status = status
        self.dribble = dribble
        self.requests: list[tuple[str, dict, str | None]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - required name
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else 0
                outer.requests.append((
                    self.path,
                    json.loads(raw or b"{}"),
                    self.headers.get("xi-api-key"),
                ))
                self.send_response(outer.status)
                self.send_header("Content-Type", "audio/mpeg")
                if not outer.dribble:
                    self.send_header("Content-Length", str(len(outer.payload)))
                self.end_headers()
                if outer.dribble:
                    # Three writes with gaps, the way a real stream arrives:
                    # a reader that only returns after EOF sees one chunk, a
                    # streaming reader sees three.
                    third = max(1, len(outer.payload) // 3)
                    for i in range(0, len(outer.payload), third):
                        self.wfile.write(outer.payload[i:i + third])
                        self.wfile.flush()
                        time.sleep(0.15)
                else:
                    self.wfile.write(outer.payload)

            def log_message(self, fmt, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class ElevenLabsCase(unittest.TestCase):
    """`tts` reads its ElevenLabs config at call time, so the tests own the env."""

    KEYS = ("ELEVENLABS_API_KEY", "ELEVENLABS_API_URL")

    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in self.KEYS}

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_keyed_elevenlabs_wins_and_answers_wav(self):
        eleven = FakeEleven(payload=b"\x01\x02" * 400)
        try:
            os.environ["ELEVENLABS_API_KEY"] = "test-key"
            os.environ["ELEVENLABS_API_URL"] = eleven.url
            wav, why = tts.synthesize("Your light bill is ₦5,000.")
        finally:
            eleven.close()
        self.assertEqual(why, tts.OK)
        self.assertTrue(wav.startswith(b"RIFF"), wav[:4])
        with wave.open(io.BytesIO(wav)) as w:
            self.assertEqual(w.getframerate(), tts.ELEVENLABS_PCM_RATE)
            self.assertEqual(w.getnchannels(), 1)

        path, sent, key = eleven.requests[0]
        self.assertIn("text-to-speech/", path)
        self.assertIn("output_format=pcm_24000", path)
        # Not "₦5,000": the voice says the letter N for the sign (measured
        # 2026-10-24), so the amount goes over as it is spoken.
        self.assertEqual(sent["text"], "Your light bill is 5,000 naira.")
        self.assertEqual(sent["model_id"], tts.ELEVENLABS_MODEL)
        self.assertEqual(key, "test-key")

    def test_no_key_is_a_refusal_not_a_guess(self):
        wav, why = tts.synthesize("hello stark")
        self.assertIsNone(wav)
        self.assertEqual(why, tts.NO_KEY)

    def test_no_key_means_no_voice_note(self):
        self.assertIsNone(tts.voice_note("hello stark"))

    def test_empty_text_is_failed_not_a_request(self):
        eleven = FakeEleven()
        try:
            os.environ["ELEVENLABS_API_KEY"] = "test-key"
            os.environ["ELEVENLABS_API_URL"] = eleven.url
            wav, why = tts.synthesize("   ")
        finally:
            eleven.close()
        self.assertIsNone(wav)
        self.assertEqual(why, tts.FAILED)
        self.assertEqual(eleven.requests, [])

    def test_elevenlabs_error_is_failed_not_empty_audio(self):
        eleven = FakeEleven(payload=b"boom", status=500)
        try:
            os.environ["ELEVENLABS_API_KEY"] = "test-key"
            os.environ["ELEVENLABS_API_URL"] = eleven.url
            wav, why = tts.synthesize("hello stark")
        finally:
            eleven.close()
        self.assertIsNone(wav)
        self.assertEqual(why, tts.ELEVENLABS_FAILED)

    @unittest.skipUnless(audio.ffmpeg_available(), "ffmpeg not installed")
    def test_voice_note_is_ogg_opus(self):
        eleven = FakeEleven(payload=b"\x00\x00" * 2400)
        try:
            os.environ["ELEVENLABS_API_KEY"] = "test-key"
            os.environ["ELEVENLABS_API_URL"] = eleven.url
            note = tts.voice_note("hello stark")
        finally:
            eleven.close()
        self.assertIsNotNone(note)
        self.assertTrue(note.startswith(b"OggS"), note[:8] if note else None)

    def test_elevenlabs_refused_is_failed_not_audio(self):
        os.environ["ELEVENLABS_API_KEY"] = "test-key"
        os.environ["ELEVENLABS_API_URL"] = "http://127.0.0.1:1"
        wav, why = tts.synthesize("hello stark")
        self.assertIsNone(wav)
        self.assertEqual(why, tts.ELEVENLABS_FAILED)

    def test_stream_naira_is_spelled_for_the_voice_too(self):
        # The dashboard plays this stream, not the buffered call — a fix that
        # only covered `synthesize` would leave the reported bug in place.
        eleven = FakeEleven(payload=b"ID3" + b"\xff" * 900)
        try:
            os.environ["ELEVENLABS_API_KEY"] = "test-key"
            os.environ["ELEVENLABS_API_URL"] = eleven.url
            list(tts.stream_elevenlabs("Your balance is ₦64,200."))
        finally:
            eleven.close()
        self.assertEqual(eleven.requests[0][1]["text"], "Your balance is 64,200 naira.")

    def test_stream_arrives_in_pieces_not_at_the_end(self):
        payload = b"ID3" + b"\xff" * 3000
        eleven = FakeEleven(payload=payload, dribble=True)
        try:
            os.environ["ELEVENLABS_API_KEY"] = "test-key"
            os.environ["ELEVENLABS_API_URL"] = eleven.url
            chunks = list(tts.stream_elevenlabs("hello stark"))
        finally:
            eleven.close()
        self.assertGreaterEqual(len(chunks), 2,
                                "the body arrived as one blob — that is buffering")
        self.assertEqual(b"".join(chunks), payload)
        self.assertIn("/stream", eleven.requests[0][0])

    def test_stream_without_a_key_yields_nothing(self):
        self.assertEqual(list(tts.stream_elevenlabs("hello stark")), [])

    def test_stream_refusal_is_empty_not_an_error(self):
        eleven = FakeEleven(payload=b"no", status=500)
        try:
            os.environ["ELEVENLABS_API_KEY"] = "test-key"
            os.environ["ELEVENLABS_API_URL"] = eleven.url
            self.assertEqual(list(tts.stream_elevenlabs("hello stark")), [])
        finally:
            eleven.close()


class SpeakableCase(unittest.TestCase):
    """What the voice is asked to say, pinned to a real mispronunciation.

    2026-10-24, reported from the Talk screen: "You have ₦64,200" was read as
    "N sixty-four thousand…". Synthesising the reply and transcribing it back
    showed the naira sign is simply not in the voice's dictionary, and no
    amount of voice settings changes that.
    """

    def test_an_amount_is_spoken_after_the_number(self):
        self.assertEqual(tts.speakable("Your current balance is ₦64,200."),
                         "Your current balance is 64,200 naira.")

    def test_every_amount_in_a_sentence_is_spelled(self):
        self.assertEqual(
            tts.speakable("You have ₦7,000 of your ₦30,000 spending cap remaining."),
            "You have 7,000 naira of your 30,000 naira spending cap remaining.",
        )

    def test_a_space_after_the_sign_is_fine(self):
        self.assertEqual(tts.speakable("That is ₦ 5,000."), "That is 5,000 naira.")

    def test_a_negative_amount_keeps_its_sign(self):
        self.assertEqual(tts.speakable("A refund of -₦2,500."),
                         "A refund of -2,500 naira.")

    def test_kobo_survive_as_decimals(self):
        self.assertEqual(tts.speakable("₦2,500.50"), "2,500.50 naira")

    def test_a_stray_sign_still_becomes_a_word(self):
        self.assertEqual(tts.speakable("The ₦ is the naira."), "The naira is the naira.")

    def test_text_without_money_is_untouched(self):
        # Commas, decimals and thousand-ish digits must not be rewritten: the
        # rule is about the sign, not about numbers in general.
        for text in ("About 11.4 units left — roughly 4 days.",
                     "Your token is 4821 0937 5512 8846 3019.",
                     "You've used 76% of your limit."):
            self.assertEqual(tts.speakable(text), text)

    def test_the_prompt_is_never_rewritten_for_display(self):
        # The reply the user reads keeps the sign; only `speakable` output is
        # sent to a voice, and the two must not be confused.
        reply = "Your current balance is ₦64,200."
        self.assertIn("₦", reply)
        self.assertNotIn("₦", tts.speakable(reply))


class TestOpusEncode(unittest.TestCase):
    @unittest.skipUnless(audio.ffmpeg_available(), "ffmpeg not installed")
    def test_wav_encodes_to_ogg(self):
        out = audio.encode_opus(_tiny_wav())
        self.assertIsNotNone(out)
        self.assertTrue(out.startswith(b"OggS"))

    @unittest.skipUnless(audio.ffmpeg_available(), "ffmpeg not installed")
    def test_garbage_is_refused_not_guessed(self):
        self.assertIsNone(audio.encode_opus(b"this is not audio at all" * 20))

    def test_tiny_and_oversized_inputs_are_refused(self):
        self.assertIsNone(audio.encode_opus(b""))
        self.assertIsNone(audio.encode_opus(_tiny_wav(), max_input_bytes=10))


if __name__ == "__main__":
    unittest.main()
