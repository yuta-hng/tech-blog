#!/usr/bin/env python3
"""Create the fixed evaluation audio from the downloaded PyCon JP recording."""

from __future__ import annotations

import av
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source" / "5EEH8MHfAyA.m4a"
OUTPUT = ROOT / "source" / "pyconjp-search-talk.flac"
START_SECONDS = 471.08
END_SECONDS = 2182.00
SAMPLE_RATE = 16_000


def main() -> None:
    source = av.open(str(SOURCE))
    source_stream = source.streams.audio[0]
    source.seek(int(START_SECONDS * av.time_base), backward=True, any_frame=False)

    output = av.open(str(OUTPUT), mode="w")
    output_stream = output.add_stream("flac", rate=SAMPLE_RATE)
    output_stream.layout = "mono"
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)

    for frame in source.decode(source_stream):
        frame_start = float(frame.time or 0)
        frame_duration = frame.samples / frame.sample_rate
        if frame_start + frame_duration <= START_SECONDS:
            continue
        if frame_start >= END_SECONDS:
            break
        for converted in resampler.resample(frame):
            converted.pts = None
            for packet in output_stream.encode(converted):
                output.mux(packet)

    for converted in resampler.resample(None):
        converted.pts = None
        for packet in output_stream.encode(converted):
            output.mux(packet)
    for packet in output_stream.encode(None):
        output.mux(packet)

    output.close()
    source.close()
    print(OUTPUT)


if __name__ == "__main__":
    main()
