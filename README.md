# transcribe-record-pulseaudio

Record and transcribe application audio on Linux: capture a call or meeting
as dual-channel stereo (one channel per speaker), watch a live transcription
stream during the call, and produce a clean post-call transcript with the two
speakers separated.

Built with Python, PulseAudio, ffmpeg, and Whisper (whisper.cpp for live
streaming, OpenAI Whisper for post-processing).

## Why script exists

- **2001**: if you wanted to mix audio in software on Linux, you installed
  PulseAudio and wired virtual sinks by hand.
- **2020**: everyone needed calls and meetings recorded, but capture tools were
  either GUI-heavy or black boxes.
- **2026**: people want *transcription* of those calls — live, local, and
  private — without sending audio to a third-party service.

This script is that pipeline in one place: PulseAudio routing + ffmpeg
capture + local Whisper AI transcription, with no cloud dependency.

## How script works

applications (browser, meeting app)
│ playback
▼
call_mix (PulseAudio null sink)  ◄── loopback: your microphone
│ monitor source (call_mix.monitor)
├──► ffmpeg ──► stereo WAV (Left = host, Right = you)
└──► whisper-stream ──► live transcript file


- Creates a virtual sink (`call_mix`) and loopbacks to mix application audio
  and your microphone into one stereo stream.
- Records that stream with ffmpeg at 16 kHz stereo — one channel per speaker,
  so speakers can be separated after the call.
- Runs `whisper-stream` against the monitor source for a rolling live
  transcript.
- On stop: splits the WAV into L/R channels and transcribes each with Python
  Whisper, saving a combined transcript.

The script also self-heals: if the recording process dies or the virtual sink
vanishes mid-call, script re-creates automatically.

## Requirements

- Linux with **PulseAudio** (`pactl` on PATH). PipeWire's PulseAudio
  compatibility layer generally works; native PipeWire is untested.
- **ffmpeg**
- **Python 3.10+**
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp) built with
  `whisper-stream`, plus a model, e.g. `models/ggml-base.en.bin`
- Python packages: `pip install -r requirements.txt` (OpenAI Whisper, used
  for post-call channel separation)
- Optional: `pavucontrol` to inspect/verify the routing visually

## Quick start

1. Edit the config at the top of `TranscribeRecordApplicationAudio.py`
   (`AudioConfig`):
   - `whisperCppDir` — path to your whisper.cpp checkout
   - `microphoneDeviceNameKeyword` — a word from your mic's PulseAudio name
     (find with `pactl list sources short`)
   - `speakerDeviceNameKeyword` — a word from your output device name
     (`pactl list sinks short`)
   - `playbackCaptureApplicationNameKeywords` — default `("chrome",)`; the
     app whose audio you want captured
2. Start the app you want to capture (so app playback stream exists), then run: `python3 TranscribeRecordApplicationAudio.py`
3. Watch the live transcript file (named `transcribeAppByScript_<timestamp>.txt`)
   update during the call.
4. Press **Ctrl+C** to stop. Cleanup (PulseAudio modules, ffmpeg,
   whisper-stream) runs automatically, and the post-call transcript is written
   as `transcribeAppByScript_combine.txt` with HOST and USER sections.

Recorded WAVs and logs are timestamped in the working directory.

## Configuration

All defaults live in the frozen `AudioConfig` dataclass (`Conf`):

| Field | Default | Purpose |
|---|---|---|
| `sinkName` | `call_mix` | Name of the virtual sink |
| `microphoneDeviceNameKeyword` | `SomeDevice` | Keyword matched against source names |
| `speakerDeviceNameKeyword` | `SomeDevice` | Keyword matched against sink names |
| `playbackCaptureApplicationNameKeywords` | `("chrome",)` | Apps to route into the mix |
| `recorderApplicationNameKeywords` | `("ffmpeg", "lavf")` | Recorders to point at the monitor |
| `whisperCppDir` | `path/to/whisper.cpp` | Path to whisper.cpp |
| `whisperModelName` | `base.en` | Python Whisper model for post-processing |
| `outputAudioFileStem` / `outputTranscribeFileStem` | see file | Output file prefixes |

## Limitations

- Keyword-based device matching: if a keyword matches nothing, that loopback
  is created with PulseAudio defaults — verify with `pavucontrol`.
- Live transcription quality is CPU-bound; `whisper-stream` trades accuracy
  for latency by design.
- Not tested on Wayland-specific audio paths or native PipeWire.

## Architecture notes

The code is organized around small protocol interfaces (`LoggerProtocol`,
`ShellProtocol`) with dependency injection, which makes the PulseAudio and
ffmpeg interaction testable without a running audio server. A `NullLogger`
is provided for silent/test runs.

## A note on how script was built

The first draft of script was generated with AI assistance (Gemini Flash).
Code been reviewed line-by-line, tested on a live system,
restructured, and is maintained by a human. Bug reports and PRs welcome.

## License

MIT
