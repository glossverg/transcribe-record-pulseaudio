"""Unit tests using a FakeShell against ShellProtocol; live tests gated by RUN_LIVE_TESTS=1."""
import json
import os
import sys
import shutil
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from TranscribeRecordApplicationAudio import (
    NullLogger, ScriptLogShell, PulseAudioMixer, ShellExecutionError,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakeShell:
  """FakeShell implements ShellProtocol with canned stdout per command prefix."""
  def __init__(self, responses=None):
    self.responses = list((responses or {}).items())
    self.ran = []

  def run(self, command, check=True, ignore_errors=False):
    self.ran.append(command)
    cmd = command if isinstance(command, str) else " ".join(map(str, command))
    for prefix, (stdout, code) in self.responses:
      if cmd.startswith(prefix):
        if code != 0 and check and not ignore_errors:
          raise ShellExecutionError(cmd, code, stdout, "")
        return stdout, "", code
    return "", "", 0

  def spawn(self, command, **kwargs):
    self.ran.append(command)
    return None


def make_mixer(fake_shell=None, sink_name="call_mix"):
  log_shell = ScriptLogShell(loggerType=NullLogger)
  if fake_shell is not None:
    log_shell.shell = fake_shell
  return PulseAudioMixer(sinkName=sink_name, logShell=log_shell)


SOURCES_JSON = json.dumps([
  {"name": "alsa_input.usb-Mic", "description": "USB Microphone", "index": 1},
  {"name": "call_mix.monitor", "description": "Monitor of call_mix", "index": 2},
])

SINKS_JSON = json.dumps([
  {"name": "alsa_output.pci", "description": "Built-in Audio", "index": 0},
  {"name": "call_mix", "description": "call_mix", "index": 2},
])

SINK_INPUTS_JSON = json.dumps([
  {"index": 57, "sink": 0,
   "properties": {"application.process.binary": "/usr/bin/chrome", "application.name": "Chrome"}},
  {"index": 58, "sink": 0,
   "properties": {"application.process.binary": "/usr/bin/firefox", "application.name": "Firefox"}},
])


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestPureHelpers:
  def test_parse_pactl_id_strips_whitespace(self):
    assert make_mixer().parsePactlId("  23\n") == 23

  def test_keyword_match_case_insensitive_substring(self):
    m = make_mixer()
    assert m.isAnyKeywordMatch(["chrome"], ["/usr/bin/chrome", "chrome"])
    assert not m.isAnyKeywordMatch(["chrome"], ["firefox", "spotify"])

  def test_plural_str_normalizes_str_and_list(self):
    m = make_mixer()
    assert m.pluralStr("chrome") == ["chrome"]
    assert m.pluralStr(["a", "b"]) == ["a", "b"]

  def test_extract_metadata_lowercases(self):
    m = make_mixer()
    stream = {"properties": {"application.process.binary": "/usr/bin/Chrome", "application.name": "ChRoMe"}}
    assert m.extractPulseAudioAppMetadata(stream) == ("/usr/bin/chrome", "chrome")


# ---------------------------------------------------------------------------
# PulseAudio query logic against FakeShell
# ---------------------------------------------------------------------------

class TestMixerQueries:
  def test_keyword_search_finds_real_source_skips_monitor(self):
    fake = FakeShell({"pactl -f json list sources": (SOURCES_JSON, 0)})
    m = make_mixer(fake)
    assert m.pulseaudioFullSourceNameByKeyword("source", "usb") == "alsa_input.usb-Mic"
    # monitor sources must never be returned for a mic match
    assert m.pulseaudioFullSourceNameByKeyword("source", "monitor") is None

  def test_sink_index_lookup(self):
    fake = FakeShell({"pactl -f json list sinks": (SINKS_JSON, 0)})
    m = make_mixer(fake)
    assert m.sinkIndexOfName() == 2
    assert m.sinkIndexOfName("does_not_exist") is None

  def test_route_playback_moves_only_matching_streams(self):
    fake = FakeShell({
      "pactl -f json list sinks": (SINKS_JSON, 0),
      "pactl -f json list sink-inputs": (SINK_INPUTS_JSON, 0),
    })
    m = make_mixer(fake)
    matched = m.routeAppPlaybackToCallMix(["chrome"])
    assert matched == ["chrome"]
    assert "pactl move-sink-input 57 call_mix" in fake.ran
    assert not any("58" in cmd for cmd in fake.ran if "move-sink-input" in cmd)


# ---------------------------------------------------------------------------
# Module lifecycle
# ---------------------------------------------------------------------------

class TestModuleLifecycle:
  def test_unload_reverses_load_order(self):
    fake = FakeShell()
    m = make_mixer(fake)
    m.loadedModules = [11, 22, 33]
    m.unloadPulseaudioModulesCreatedBySession()
    unloads = [c for c in fake.ran if "unload-module" in c]
    assert unloads == ["pactl unload-module 33", "pactl unload-module 22", "pactl unload-module 11"]
    assert m.loadedModules == []

  def test_failed_unload_keeps_module_tracked(self):
    fake = FakeShell({"pactl unload-module 22": ("", 1)})
    m = make_mixer(fake)
    m.loadedModules = [22]
    m.unloadPulseaudioModulesCreatedBySession()
    assert m.loadedModules == [22]  # still tracked so a later pass can retry


# ---------------------------------------------------------------------------
# Output file naming
# ---------------------------------------------------------------------------

class TestFileNaming:
  def test_file_from_stem_formats_timestamped_name(self):
    ls = ScriptLogShell(loggerType=NullLogger)
    assert ls.fileFromStem("app", "wav", "20260101_120000") == "app_20260101_120000.wav"

  def test_refresh_generates_wav_and_txt_paths(self):
    ls = ScriptLogShell(loggerType=NullLogger)
    ls.refresh()
    assert ls.outputAudioFile.endswith(".wav")
    assert ls.transcribeFile.endswith(".txt")
    assert ls.logFile.endswith(".txt")


# ---------------------------------------------------------------------------
# Live integration (gated)
# ---------------------------------------------------------------------------

live = pytest.mark.skipif(
  os.environ.get("RUN_LIVE_TESTS") != "1" or shutil.which("pactl") is None,
  reason="set RUN_LIVE_TESTS=1 with a running PulseAudio server")

@live
class TestLivePulseAudio:
  def test_create_sink_and_unload(self):
    m = make_mixer()  # real SystemShell, NullLogger
    try:
      m.createNullSink()
      assert m.sinkExists()
    finally:
      m.unloadPulseaudioModulesCreatedBySession()
    assert not m.sinkExists()
