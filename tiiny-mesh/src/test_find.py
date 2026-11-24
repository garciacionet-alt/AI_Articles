#!/usr/bin/env python3
"""Tests for the find module — "which model can do this, and what would it take?"

The two questions are kept apart on purpose, and the tests keep them apart:

  * the SCORE says how well a model fits the words of a request;
  * the PLACEMENT says what it would cost to run it — the NPU headroom
    beside what is already resident, and the disk left for the weights.

A model that fits the words perfectly and cannot be placed is a real
answer, not a failure, so it has to be reported rather than hidden.

The device payload, measured on 2026-11-23:

    {
      "data": {
        "total_bytes": 921123848192,
        "used_bytes": 462442033152,
        "remaining_bytes": 411857166336,
        "details": [
          {"name": "LLM", "size_bytes": 405205846306},
          {"name": "Agent", "size_bytes": 18941299712,
           "apps": [{"name": "wa-tiinyvisuals", "size_bytes": 120394219}]},
          {"name": "Other Dockers", "size_bytes": 5926843550}
        ],
        "status": "ok"
      }
    }
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import find


def row(model_id="m", status="downloaded", npu=20, type_="Text Generation",
        caps=None, desc="", name="", supported=None, tags=None, rank=None):
    """A catalogue row shaped like the device's."""
    return {
        "model_id": model_id,
        "status": status,
        "npu_usage": npu,
        "type": type_,
        "capabilities": caps if caps is not None else ["chat"],
        "desc": desc,
        "name": name,
        "supported": supported or [],
        "tags": tags or [],
        "recommend_rank": rank,
        "load_time": 7,
    }


class Target:
    """A target, shaped like the mesh's."""

    def __init__(self, tid="tiiny-ant", kind="tiiny"):
        self.id = tid
        self.kind = kind
        self.admin_url = "http://x"
        self.key_env = ""

    def admin(self, path):
        return "http://x" + path

    def key(self):
        return "k"


class TestTerms(unittest.TestCase):
    def test_stopwords_dropped(self):
        self.assertEqual(find.terms("create a drawing of a child"), ["drawing", "child"])

    def test_short_words_kept_when_they_mean_something(self):
        # "3d" is two characters and a real capability on these boxes
        self.assertIn("3d", find.terms("a 3d model of a fox"))
        self.assertIn("fox", find.terms("a 3d model of a fox"))

    def test_single_characters_dropped(self):
        self.assertEqual(find.terms("a b c"), [])

    def test_repeats_kept_once(self):
        self.assertEqual(find.terms("drawing drawing picture"), ["drawing", "picture"])

    def test_empty_query(self):
        self.assertEqual(find.terms(""), [])
        self.assertEqual(find.terms(""), [])


class TestHints(unittest.TestCase):
    def test_drawing_is_an_image_job(self):
        self.assertEqual(find.hints_for("a drawing of a child"), {"drawing": ["image_gen"]})

    def test_phrase_beats_word(self):
        # "speech" alone means ASR; "text to speech" means TTS
        self.assertEqual(find.hints_for("text to speech")["text to speech"], ["tts"])
        self.assertEqual(find.hints_for("speech")["speech"], ["asr"])

    def test_unknown_word_has_no_hint(self):
        self.assertNotIn("gizmo", find.hints_for("a gizmo"))


class TestScoring(unittest.TestCase):
    def test_image_model_beats_chat_model_for_a_drawing(self):
        q = find.terms("create a drawing of a child")
        hints = find.hints_for("create a drawing of a child")
        image = find.score_model(
            row(model_id="img", caps=["image_gen"], type_="Text-to-Image"), q, hints)[0]
        chat = find.score_model(
            row(model_id="chat", caps=["chat"], type_="Image-Text-to-Text"), q, hints)[0]
        self.assertGreater(image, chat)

    def test_vision_chat_model_is_not_an_image_generator(self):
        # the trap: "Image-Text-to-Text" contains "image", but a vision
        # chat model cannot draw
        q = find.terms("draw a picture")
        hints = find.hints_for("draw a picture")
        score, _ = find.score_model(
            row(model_id="chat", caps=["chat", "vision"], type_="Image-Text-to-Text"), q, hints)
        self.assertEqual(score, 0.0)

    def test_chat_model_wins_for_a_chat_request(self):
        q = find.terms("explain this code")
        hints = find.hints_for("explain this code")
        chat = find.score_model(row(model_id="chat", caps=["chat"]), q, hints)[0]
        image = find.score_model(
            row(model_id="img", caps=["image_gen"], type_="Text-to-Image"), q, hints)[0]
        self.assertGreater(chat, image)

    def test_description_match_scores(self):
        q = find.terms("photo of a cat")
        hints = find.hints_for("photo of a cat")
        with_desc = find.score_model(
            row(model_id="a", caps=["image_gen"], type_="Text-to-Image",
                desc="generates a photo of a cat or a dog"), q, hints)[0]
        without = find.score_model(
            row(model_id="b", caps=["image_gen"], type_="Text-to-Image",
                desc="an image model"), q, hints)[0]
        self.assertGreater(with_desc, without)

    def test_name_match_scores(self):
        q = find.terms("children")
        hints = find.hints_for("children")
        named = find.score_model(
            row(model_id="x", caps=["image_gen"], type_="Text-to-Image",
                name="Children Drawing"), q, hints)[0]
        other = find.score_model(
            row(model_id="y", caps=["image_gen"], type_="Text-to-Image"), q, hints)[0]
        self.assertGreater(named, other)


class TestBudget(unittest.TestCase):
    def test_only_running_models_count(self):
        rows = [row(status="running", npu=47), row(status="downloaded", npu=30),
                row(status="not_downloaded", npu=90)]
        self.assertEqual(find.incumbent_npu(rows), 47)

    def test_budget_is_ninety_five_not_a_hundred(self):
        self.assertEqual(find.NPU_BUDGET, 95)

    def test_estimate_from_npu_share(self):
        self.assertAlmostEqual(find.estimate_gb(23), 11.0, places=1)
        self.assertAlmostEqual(find.estimate_gb(47), 22.6, places=1)

    def test_estimate_of_nothing(self):
        self.assertIsNone(find.estimate_gb(0))
        self.assertIsNone(find.estimate_gb(None))


class TestPlacement(unittest.TestCase):
    def test_running_model_is_ready(self):
        p = find.placement(Target(), row(status="running", npu=47), 47, None)
        self.assertEqual(p["action"], "ready")
        self.assertEqual(p["npu_free"], 48)

    def test_downloaded_model_that_fits_is_a_load(self):
        p = find.placement(Target(), row(status="downloaded", npu=23), 47, None)
        self.assertEqual(p["action"], "load")
        self.assertTrue(p["fits"])

    def test_downloaded_model_that_does_not_fit_needs_an_eviction(self):
        p = find.placement(Target(), row(status="downloaded", npu=60), 47, None)
        self.assertEqual(p["action"], "un-reside")
        self.assertFalse(p["fits"])
        self.assertIn("evict_candidates", p)

    def test_not_downloaded_model_needs_a_download(self):
        p = find.placement(Target(), row(status="not_downloaded", npu=23), 47, None)
        self.assertEqual(p["action"], "download")

    def test_eviction_prefers_the_smallest_non_generalist(self):
        running = [
            row(model_id="Qwen/Qwen3.6-35B-A3B", status="running", npu=47),
            row(model_id="openai/gpt-oss-20b", status="running", npu=27),
        ]
        # the generalist is 47 and would free enough on its own, but the
        # smaller model is tried first
        p = find.placement(Target(), row(status="downloaded", npu=60), 74,
                            None, running)
        self.assertEqual(p["action"], "un-reside")
        self.assertEqual(p["evict_candidates"][0], "openai/gpt-oss-20b")

    def test_eviction_stops_once_enough_is_freed(self):
        running = [
            row(model_id="Qwen/Qwen3.6-35B-A3B", status="running", npu=47),
            row(model_id="openai/gpt-oss-20b", status="running", npu=27),
        ]
        # incumbent 74, so headroom is 21; needing 30 leaves a shortfall
        # of 9, which the 27% model covers on its own. The generalist -
        # the model every other tier falls back to - is left alone.
        p = find.placement(Target(), row(status="downloaded", npu=30), 74,
                            None, running)
        self.assertEqual(p["evict_candidates"], ["openai/gpt-oss-20b"])

    def test_eviction_takes_the_generalist_only_as_a_last_resort(self):
        running = [
            row(model_id="Qwen/Qwen3.6-35B-A3B", status="running", npu=47),
            row(model_id="openai/gpt-oss-20b", status="running", npu=27),
        ]
        # needing 60 frees a shortfall of 39, which one model cannot cover
        p = find.placement(Target(), row(status="downloaded", npu=60), 74,
                            None, running)
        self.assertEqual(p["evict_candidates"],
                         ["openai/gpt-oss-20b", "Qwen/Qwen3.6-35B-A3B"])

    def test_only_resident_models_can_be_evicted(self):
        # a downloaded model holds no NPU share, so stopping it would
        # not make room for anything
        rows = [
            row(model_id="Qwen/Qwen3.6-35B-A3B", status="running", npu=47),
            row(model_id="openai/gpt-oss-20b", status="downloaded", npu=27),
        ]
        p = find.placement(Target(), row(status="downloaded", npu=60), 47,
                            None, rows)
        self.assertEqual(p["evict_candidates"], ["Qwen/Qwen3.6-35B-A3B"])

    def test_disk_figures_are_carried(self):
        storage = {"ok": True, "free_gb": 411.9}
        p = find.placement(Target(), row(status="not_downloaded", npu=23), 47, storage)
        self.assertEqual(p["disk_free_gb"], 411.9)
        self.assertAlmostEqual(p["est_size_gb"], 11.0, places=1)
        self.assertTrue(p["disk_fits"])

    def test_disk_too_small_is_reported(self):
        storage = {"ok": True, "free_gb": 4.0}
        p = find.placement(Target(), row(status="not_downloaded", npu=23), 47, storage)
        self.assertFalse(p["disk_fits"])

    def test_non_tiiny_target_has_no_budget(self):
        p = find.placement(Target("ollama", "openai"), row(status="available"), 0, None)
        self.assertEqual(p["action"], "use")
        self.assertIsNone(p["npu_free"])


class TestStorage(unittest.TestCase):
    PAYLOAD = {
        "data": {
            "total_bytes": 921123848192,
            "used_bytes": 723697500160,
            "remaining_bytes": 150601699328,
            "details": [
                {"name": "LLM", "size_bytes": 658058246674},
                {"name": "Agent", "size_bytes": 18941299712,
                 "apps": [{"name": "wa-tiinyvisuals", "size_bytes": 120394219}]},
                {"name": "Other Dockers", "size_bytes": 6394593988},
            ],
            "status": "ok",
        }
    }

    def test_totals(self):
        s = find.norm_storage(self.PAYLOAD)
        self.assertTrue(s["ok"])
        self.assertEqual(s["total_bytes"], 921123848192)
        self.assertEqual(s["remaining_bytes"], 150601699328)
        self.assertAlmostEqual(s["free_gb"], 150.6, places=1)

    def test_categories_are_broken_out(self):
        s = find.norm_storage(self.PAYLOAD)
        names = [c["name"] for c in s["categories"]]
        self.assertIn("LLM", names)
        self.assertIn("Agent", names)

    def test_apps_are_listed(self):
        s = find.norm_storage(self.PAYLOAD)
        agent = [c for c in s["categories"] if c["name"] == "Agent"][0]
        self.assertEqual(agent["apps"][0]["name"], "wa-tiinyvisuals")

    def test_unreadable_payload(self):
        s = find.norm_storage({"data": "nope"})
        self.assertFalse(s["ok"])

    def test_storage_of_a_non_tiiny_target(self):
        s = find.storage_for(Target("ollama", "openai"), lambda *a, **k: (200, {}, {}))
        self.assertFalse(s["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
