import json
import tempfile
import unittest
from pathlib import Path

from servio import subcast
from servio import create_app

SRT = """1
00:00:00,000 --> 00:00:06,740
When your holiday starts

2
00:00:06,740 --> 00:00:11,540
with Irish ferries, life's a beach
"""


def parse_vtt(text: str) -> list[tuple[str, str, str]]:
    """Return ``(start, end, text)`` for every cue of a WebVTT document."""
    cues = []
    for block in text.split("\n\n"):
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines or "-->" not in lines[0]:
            continue
        start, _, end = lines[0].partition(" --> ")
        cues.append((start.strip(), end.split(" ")[0], "\n".join(lines[1:])))
    return cues


class SrtToVttTest(unittest.TestCase):
    """Conversion must not move a single cue: the browser drives captions from
    the media clock, so a shifted timestamp is a visibly out-of-sync subtitle."""

    def test_cue_timeline_survives_the_conversion(self):
        vtt = subcast.srt_to_vtt(SRT)

        self.assertTrue(vtt.startswith("WEBVTT\n\n"))
        self.assertEqual(
            parse_vtt(vtt),
            [
                ("00:00:00.000", "00:00:06.740", "When your holiday starts"),
                ("00:00:06.740", "00:00:11.540", "with Irish ferries, life's a beach"),
            ],
        )

    def test_cue_numbers_are_dropped_but_numeric_dialogue_is_kept(self):
        vtt = subcast.srt_to_vtt(
            "1\n00:00:01,000 --> 00:00:02,000 align:start position:0%\nfirst\n\n"
            "2\n00:00:02,000 --> 00:00:03,000\n42\n"
        )

        self.assertEqual(
            parse_vtt(vtt),
            [
                ("00:00:01.000", "00:00:02.000", "first"),
                ("00:00:02.000", "00:00:03.000", "42"),
            ],
        )
        # SubRip cue settings are legal WebVTT settings and must not be lost.
        self.assertIn("00:00:01.000 --> 00:00:02.000 align:start position:0%", vtt)

    def test_markup_survives_but_bare_ampersands_and_angle_brackets_are_escaped(self):
        vtt = subcast.srt_to_vtt(
            "1\n00:00:00,500 --> 00:00:01,500\n"
            "Tom & Jerry <i>live</i> 2 < 3 &amp; <v Bob>hello</v>\n"
        )

        self.assertIn(
            "Tom &amp; Jerry <i>live</i> 2 &lt; 3 &amp; <v Bob>hello</v>", vtt
        )

    def test_windows_line_endings_and_byte_order_mark_are_normalised(self):
        vtt = subcast.srt_to_vtt("\ufeff1\r\n00:00:00,000 --> 00:00:01,000\r\nhi\r\n")

        self.assertNotIn("\r", vtt)
        self.assertNotIn("\ufeff", vtt)
        self.assertEqual(parse_vtt(vtt), [("00:00:00.000", "00:00:01.000", "hi")])

    def test_missing_cue_text_line_is_tolerated(self):
        vtt = subcast.srt_to_vtt("1\n00:00:00,000 --> 00:00:01,000\n")

        self.assertEqual(parse_vtt(vtt), [])


class CuesJsonToVttTest(unittest.TestCase):
    """``cues.json`` is the fallback when no SRT sidecar was kept; its float
    seconds carry the same timeline and must land on the same milliseconds."""

    def test_float_seconds_become_millisecond_timestamps(self):
        vtt = subcast.cues_to_vtt(
            [
                {"start": 0.0, "end": 6.74, "text": "first"},
                {"start": 6.74, "end": 3661.5, "text": "second"},
            ]
        )

        self.assertEqual(
            parse_vtt(vtt),
            [
                ("00:00:00.000", "00:00:06.740", "first"),
                ("00:00:06.740", "01:01:01.500", "second"),
            ],
        )

    def test_malformed_cues_are_skipped_instead_of_breaking_the_file(self):
        vtt = subcast.cues_to_vtt(
            [
                {"start": 0, "end": 1, "text": "good"},
                {"start": "nope", "end": 2, "text": "bad"},
                {"start": 3, "end": 4, "text": ""},
            ]
        )

        self.assertEqual(parse_vtt(vtt), [("00:00:00.000", "00:00:01.000", "good")])


class CacheListingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)

        self.app = create_app()
        self.app.config["SUBSCAST_FOLDER"] = str(self.folder)
        self.context = self.app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)

        self.write("rte/aaaa.mp3", b"audio")
        self.write("rte/aaaa.srt", SRT.encode())
        self.write("rte/aaaa.position", b"12.5")
        self.write("youtube/bbbb.mp4", b"video")
        self.write("bbc/cccc.mp3.part", b"partial")
        self.write(
            "rte/listings/deadbeef.json",
            json.dumps(
                {
                    "items": [
                        {"key": "aaaa", "title": "Morning Ireland", "duration": 3300.0},
                    ]
                }
            ).encode(),
        )
        self.write(
            "youtube/bbbb.meta.json",
            json.dumps({"title": "Bluey live", "duration": None}).encode(),
        )
        self.write(
            "youtube/bbbb.cues.json",
            json.dumps([{"start": 1.0, "end": 2.0, "text": "hi"}]).encode(),
        )

    def write(self, relative: str, payload: bytes) -> Path:
        path = self.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def test_only_playable_media_is_listed(self):
        entries = {entry.filename for entry in subcast.list_media(self.folder)}

        self.assertEqual(entries, {"rte/aaaa.mp3", "youtube/bbbb.mp4"})

    def test_entry_metadata_comes_from_titles_and_sidecars(self):
        entries = {entry.key: entry for entry in subcast.list_media(self.folder)}

        audio = entries["aaaa"]
        self.assertEqual(audio.title, "Morning Ireland")
        self.assertEqual(audio.kind, "audio")
        self.assertEqual(audio.duration, 3300.0)
        self.assertEqual(audio.duration_text, "55:00")
        self.assertEqual(audio.name, "aaaa.mp3")
        self.assertTrue(audio.has_subtitles)
        self.assertFalse(audio.is_video)

        video = entries["bbbb"]
        self.assertEqual(video.title, "Bluey live")
        self.assertEqual(video.kind, "video")
        self.assertIsNone(video.duration)
        self.assertTrue(video.has_subtitles)

    def test_title_falls_back_to_the_media_key(self):
        self.write("acast/dddd.mp3", b"audio")

        entries = {entry.key: entry for entry in subcast.list_media(self.folder)}

        self.assertEqual(entries["dddd"].title, "dddd")

    def test_listing_is_newest_first(self):
        newest = self.write("acast/eeee.mp3", b"audio")

        entries = subcast.list_media(self.folder)

        self.assertEqual(entries[0].filename, "acast/eeee.mp3")
        self.assertEqual(entries[0].modified, newest.stat().st_mtime)

    def test_missing_cache_folder_lists_nothing(self):
        self.assertEqual(subcast.list_media(self.folder / "absent"), [])

    def test_metadata_edits_are_picked_up(self):
        self.assertEqual(
            subcast.entry_for(self.folder, "rte", "aaaa").title, "Morning Ireland"
        )

        self.write(
            "rte/listings/deadbeef.json",
            json.dumps(
                {"items": [{"key": "aaaa", "title": "Later title", "duration": 10}]}
            ).encode(),
        )

        self.assertEqual(
            subcast.entry_for(self.folder, "rte", "aaaa").title, "Later title"
        )

    def test_entry_for_rejects_unknown_keys_and_traversal(self):
        self.assertIsNone(subcast.entry_for(self.folder, "rte", "nope"))
        self.assertIsNone(subcast.entry_for(self.folder, "rte", "../../etc/passwd"))
        self.assertIsNone(subcast.entry_for(self.folder, "..", "aaaa"))

    def test_vtt_is_built_from_srt_then_from_cues_json(self):
        srt_vtt = subcast.vtt_for(self.folder / "rte", "aaaa")
        self.assertTrue(srt_vtt.startswith("WEBVTT\n\n"))
        self.assertIn("00:00:06.740 --> 00:00:11.540", srt_vtt)

        cues_vtt = subcast.vtt_for(self.folder / "youtube", "bbbb")
        self.assertIn("00:00:01.000 --> 00:00:02.000", cues_vtt)

        self.assertIsNone(subcast.vtt_for(self.folder / "rte", "cccc"))


class SubcastRouteTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)

        self.app = create_app()
        self.app.config["SUBSCAST_FOLDER"] = str(self.folder)
        self.client = self.app.test_client()

        media = self.write("rte/aaaa.mp3", b"0123456789")
        self.write("rte/aaaa.srt", SRT.encode())
        self.write("rte/bbbb.mp3", b"no transcript here")
        self.write(
            "rte/listings/deadbeef.json",
            json.dumps(
                {"items": [{"key": "aaaa", "title": "Morning Ireland"}]}
            ).encode(),
        )
        self.media_size = media.stat().st_size

    def write(self, relative: str, payload: bytes) -> Path:
        path = self.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def test_index_lists_cached_media(self):
        response = self.client.get("/subcast")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Morning Ireland", body)
        self.assertIn("/subcast/player/rte/aaaa", body)
        self.assertIn("No subtitles", body)

    def test_media_is_streamable_with_byte_ranges(self):
        with self.client.get("/subcast/media/rte/aaaa.mp3") as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Content-Type"], "audio/mpeg")
            self.assertEqual(response.headers["Accept-Ranges"], "bytes")
            self.assertEqual(response.headers["Content-Length"], str(self.media_size))

        with self.client.get(
            "/subcast/media/rte/aaaa.mp3", headers={"Range": "bytes=2-5"}
        ) as partial:
            self.assertEqual(partial.status_code, 206)
            self.assertEqual(
                partial.headers["Content-Range"], f"bytes 2-5/{self.media_size}"
            )
            self.assertEqual(partial.get_data(), b"2345")

    def test_media_route_refuses_sidecars_and_traversal(self):
        self.assertEqual(
            self.client.get("/subcast/media/rte/aaaa.srt").status_code, 404
        )
        self.assertEqual(
            self.client.get("/subcast/media/rte/..%2F..%2Fetc%2Fpasswd").status_code,
            404,
        )
        self.assertEqual(
            self.client.get("/subcast/media/rte/missing.mp3").status_code, 404
        )

    def test_subtitles_are_served_as_webvtt(self):
        response = self.client.get("/subcast/subtitles/rte/aaaa.vtt")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["Content-Type"].startswith("text/vtt"))
        body = response.get_data(as_text=True)
        self.assertTrue(body.startswith("WEBVTT\n\n"))
        self.assertIn("00:00:00.000 --> 00:00:06.740", body)

    def test_subtitles_404_without_a_transcript_or_media(self):
        self.assertEqual(
            self.client.get("/subcast/subtitles/rte/bbbb.vtt").status_code, 404
        )
        self.assertEqual(
            self.client.get("/subcast/subtitles/rte/cccc.vtt").status_code, 404
        )

    def test_player_wires_media_and_track_together(self):
        response = self.client.get("/subcast/player/rte/aaaa")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('type="audio/mpeg"', body)
        self.assertIn('src="/subcast/media/rte/aaaa.mp3"', body)
        self.assertIn('kind="subtitles"', body)
        self.assertIn('src="/subcast/subtitles/rte/aaaa.vtt"', body)
        self.assertIn("Morning Ireland", body)

    def test_player_without_transcript_omits_the_track(self):
        response = self.client.get("/subcast/player/rte/bbbb")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertNotIn('kind="subtitles"', body)
        self.assertIn("disabled", body)

        self.assertEqual(
            self.client.get("/subcast/player/rte/missing").status_code, 404
        )
