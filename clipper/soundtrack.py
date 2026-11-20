"""Background music and transition sounds for Top 10s, made here with ffmpeg (nothing copyrighted).

  music: a soft lo-fi loop: warm chord pads, a quiet bass, a gentle kick and snare. Each Top 10 gets a
         random chord progression and key, so they don't all sound the same.
  whoosh: a rising noise swell that peaks on the cut, with a soft low thump.

Songs you put in the "music" folder (next to config.toml) are used instead of the made-up loop, one
picked at random each time. Only use music you're allowed to post.
"""
from __future__ import annotations

import random
import subprocess
from pathlib import Path

from .proc import NO_WINDOW

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
LOOP = 16.0           # seconds: 4 chords of 4 s; the loop repeats under the whole video
WHOOSH_PEAK = 0.5     # seconds into the sound effect where it peaks (put that on the cut)

# Chord progressions as MIDI notes (triads), in A minor / C major; transposed at random.
PROGRESSIONS = [
    [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)],   # Am F C G
    [(53, 57, 60), (55, 59, 62), (52, 55, 59), (57, 60, 64)],   # F G Em Am
    [(48, 52, 55), (55, 59, 62), (57, 60, 64), (53, 57, 60)],   # C G Am F
    [(57, 60, 64), (55, 59, 62), (53, 57, 60), (52, 55, 59)],   # Am G F Em
    [(50, 53, 57), (55, 59, 62), (48, 52, 55), (57, 60, 64)],   # Dm G C Am
]


def _hz(note: float) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def music_expr(rng: random.Random) -> tuple[str, str]:
    """The aevalsrc expressions (left, right) for one loop."""
    prog = rng.choice(PROGRESSIONS)
    shift = rng.randint(-3, 2)
    span = LOOP / len(prog)
    m = f"mod(t,{LOOP})"
    chans = []
    for detune in (0.0, 0.7):                     # a slightly detuned right channel makes it wide and soft
        parts = []
        for i, chord in enumerate(prog):
            a, b = i * span, (i + 1) * span + 0.6       # each chord rings a little into the next
            # the last chord rings on over the start of the next loop, so the loop has no gap
            mm = f"({m}+{LOOP}*lt({m},0.6))" if i == len(prog) - 1 else m
            x = f"({mm}-{a})"
            env = f"min(1,{x}/0.7)*max(0,min(1,({b}-{mm})/0.9))"
            tones = "+".join(f"sin(2*PI*{_hz(n + shift) + detune:.3f}*t)+0.3*sin(4*PI*{_hz(n + shift) + detune:.3f}*t)"
                             for n in chord)
            bass = f"0.9*sin(2*PI*{_hz(chord[0] + shift - 24):.3f}*t)"
            parts.append(f"between({mm},{a},{b})*{env}*(0.16*({tones})+{bass}*0.5)")
        k = "mod(t,2)"                             # a kick every 2 s and a soft snare in between (lo-fi, slow)
        kick = f"0.55*exp(-14*{k})*sin(2*PI*(48+70*exp(-28*{k}))*{k})"
        s = "mod(t+1,2)"
        snare = f"0.07*exp(-22*{s})*(2*random(0)-1)"
        chans.append("+".join(parts) + f"+{kick}+{snare}")
    return chans[0], chans[1]


def make_music(out: Path, seed: int | None = None) -> Path:
    """Write a LOOP-second music loop (wav) to `out`."""
    left, right = music_expr(random.Random(seed))
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc=exprs='{left}|{right}':s=44100:d={LOOP}",
                    "-af", "lowpass=f=2200,highpass=f=35,volume=0.5", "-c:a", "pcm_s16le", str(out)],
                   check=True, capture_output=True, timeout=120, **NO_WINDOW)
    return out


def make_whoosh(out: Path) -> Path:
    """Write the transition sound (wav): a noise swell peaking at WHOOSH_PEAK s, plus a low thump there."""
    p = WHOOSH_PEAK
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "anoisesrc=d=0.9:c=pink:a=0.9:s=44100",
                    "-f", "lavfi", "-i", "aevalsrc='0.8*exp(-10*t)*sin(2*PI*(50+70*exp(-30*t))*t)':s=44100:d=0.5",
                    "-filter_complex",
                    f"[0]highpass=f=500,lowpass=f=7000,volume=4,"
                    f"volume='if(lt(t,{p}),pow(t/{p},3),exp(-(t-{p})*13))':eval=frame[w];"
                    f"[1]adelay={int(p * 1000)}[k];[w][k]amix=inputs=2:normalize=0,"
                    "aformat=channel_layouts=stereo,volume=0.7",
                    "-c:a", "pcm_s16le", str(out)],
                   check=True, capture_output=True, timeout=60, **NO_WINDOW)
    return out


def pick_song(folder: Path) -> Path | None:
    """A random song from your music folder, if there are any."""
    if not folder.is_dir():
        return None
    songs = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXT]
    return random.choice(songs) if songs else None
