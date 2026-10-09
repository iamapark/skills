"""Behavior tests with synthetic data only; no real credentials or API calls."""
import contextlib
from concurrent.futures import ThreadPoolExecutor
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_srt
import review_subtitles as review
from subtitle_common import fmt, load_inputs


def response(choice="clear", confidence=0.95):
    return {"model": "jev-test", "answers": {
        dimension: {"type": "choice", "choice": choice, "confidence": confidence,
                    "probabilities": {option: 1.0 if option == choice else 0.0
                                      for option in review.CRITERIA}}
        for dimension in review.DIMENSIONS},
        "usage": {"input_tokens": 100, "output_tokens": 20}}


class SubtitleReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.out = Path(self.directory.name)
        self.sent, self.tr = self.out / "sample.sentences.json", self.out / "translations.json"
        self.units = [
            {"id": 1, "start": 0, "end": 3, "en": "If the request fails,"},
            {"id": 2, "start": 3, "end": 6, "en": "do not retry it"},
            {"id": 3, "start": 6, "end": 9, "en": "without checking the server."},
            {"id": 4, "start": 10, "end": 13, "en": "Keep the identifier unchanged."},
        ]
        self.translations = {"1": "요청이 실패하면", "2": "서버를 확인하지 않고", "3": "재시도하지 마세요.", "4": "식별자를 유지하세요."}
        self.save_inputs()
        self.argv = [str(self.sent), str(self.tr), str(self.out), "sample"]
        self.report = self.out / "sample.review.json"
        self.api_log = self.out / "sample.jev-api.jsonl"
        self.log_context = {"log_path": self.api_log, "run_id": "test-run", "window_index": 1}
        self.environment = patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-only-secret"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def save_inputs(self):
        self.sent.write_text(json.dumps(self.units), encoding="utf-8")
        self.tr.write_text(json.dumps(self.translations), encoding="utf-8")

    def run_review(self, *args, side_effect=None, value=None):
        with patch.object(review, "call_jev", side_effect=side_effect,
                          return_value=value or response()) as call, contextlib.redirect_stdout(io.StringIO()):
            code = review.main(self.argv + list(args))
        return code, call

    def test_windows_preserve_split_sentence_and_all_ids_with_context(self):
        windows = review.make_windows(self.units, self.translations)
        self.assertEqual([u["id"] for u in windows[0]["target"]], [1, 2, 3])
        self.assertEqual([u["id"] for w in windows for u in w["target"]], [1, 2, 3, 4])
        self.assertEqual(windows[0]["after"][0]["id"], 4)
        self.assertEqual([u["id"] for u in windows[1]["before"]], [2, 3])

    def test_unpunctuated_long_input_is_bounded_without_losing_cues(self):
        units = [{"id": i + 1, "start": i * 2, "end": i * 2 + 1, "en": "unfinished"} for i in range(29)]
        windows = review.make_windows(units, {str(u["id"]): "계속" for u in units})
        self.assertTrue(all(len(w["target"]) <= 12 for w in windows))
        self.assertEqual([u["id"] for w in windows for u in w["target"]], list(range(1, 30)))

    def test_dry_run_needs_no_key_and_does_not_replace_live_report(self):
        self.report.write_text("previous-report", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            code, call = self.run_review("--dry-run")
        self.assertEqual(code, 0)
        call.assert_not_called()
        self.assertEqual(self.report.read_text(), "previous-report")
        plan = json.loads((self.out / "sample.review-plan.json").read_text())
        self.assertEqual(plan["status"], "dry_run")
        self.assertEqual(len(plan["requests"]), 2)
        self.assertNotIn("test-only-secret", json.dumps(plan))
        self.assertFalse(self.api_log.exists())

    def test_completed_review_builds_subtitles_without_altering_sources(self):
        before = self.sent.read_bytes(), self.tr.read_bytes()
        code, call = self.run_review()
        self.assertEqual(code, 0)
        self.assertEqual(call.call_count, 2)
        payload = call.call_args.args[0]
        self.assertEqual(set(payload), {"model", "state", "questions"})
        self.assertEqual(set(payload["questions"]), set(review.DIMENSIONS))
        with contextlib.redirect_stdout(io.StringIO()):
            build_srt.main(self.argv)
        srt = (self.out / "sample.ko.srt").read_text()
        self.assertIn("00:00:03,000 --> 00:00:06,000\n서버를 확인하지 않고", srt)
        self.assertTrue((self.out / "sample.ko.vtt").read_text().startswith("WEBVTT"))
        self.assertEqual((self.sent.read_bytes(), self.tr.read_bytes()), before)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["usage"], {"input_tokens": 200, "output_tokens": 40})
        self.assertEqual(self.report.stat().st_mode & 0o777, 0o600)

    def test_flagged_review_requires_acknowledgement_but_can_be_retained(self):
        code, _ = self.run_review(value=response("issue"))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(self.report.read_text())["review_ids"], [1, 2, 3, 4])
        with self.assertRaisesRegex(ValueError, "re-check"):
            build_srt.main(self.argv)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_srt.main(self.argv + ["--accept-review-flags"]), 0)

    def test_low_confidence_clear_and_uncertain_are_flagged(self):
        for answer in (response("clear", 0.1), response("uncertain")):
            with self.subTest(answer=answer["answers"]["flow"]):
                code, _ = self.run_review(value=answer)
                self.assertEqual(code, 2)

    def test_local_readability_warning_does_not_modify_translation(self):
        self.translations["1"] = "가" * 60
        self.save_inputs()
        code, _ = self.run_review()
        self.assertEqual(code, 2)
        data = json.loads(self.report.read_text())
        self.assertEqual({f["kind"] for f in data["local_flags"]}, {"reading_speed", "line_length"})
        self.assertEqual(json.loads(self.tr.read_text())["1"], "가" * 60)

    def test_missing_key_invalidates_old_report_without_network(self):
        self.run_review()
        with patch.dict(os.environ, {}, clear=True):
            code, call = self.run_review()
        self.assertEqual(code, 1)
        call.assert_not_called()
        self.assertFalse(self.api_log.exists())
        self.assertEqual(json.loads(self.report.read_text())["status"], "failed")
        with self.assertRaisesRegex(ValueError, "completed Jev review"):
            build_srt.main(self.argv + ["--accept-review-flags"])

    def test_partial_failure_records_progress_and_never_builds(self):
        code, _ = self.run_review(side_effect=[response(), review.ReviewError("Jev HTTP 529")])
        self.assertEqual(code, 1)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(report["results"]), 1)
        with self.assertRaises(ValueError):
            build_srt.main(self.argv + ["--accept-review-flags"])

    def test_stale_report_cannot_be_acknowledged_away(self):
        self.run_review()
        self.translations["1"] = "요청이 실패할 경우"
        self.save_inputs()
        with self.assertRaisesRegex(ValueError, "stale"):
            build_srt.main(self.argv + ["--accept-review-flags"])

    def test_dry_report_and_missing_coverage_cannot_build(self):
        self.run_review("--dry-run")
        self.report.write_bytes((self.out / "sample.review-plan.json").read_bytes())
        with self.assertRaises(ValueError):
            build_srt.main(self.argv)
        self.run_review()
        data = json.loads(self.report.read_text())
        data["results"][-1]["ids"] = []
        self.report.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "cover every"):
            build_srt.main(self.argv)

    def test_invalid_inputs_stop_before_api(self):
        mutations = [
            lambda: self.translations.pop("2"),
            lambda: self.translations.update({"9": "extra"}),
            lambda: self.translations.update({"2": ""}),
            lambda: self.translations.update({"2": "a\n\nb"}),
            lambda: self.units[1].update({"id": 1}),
            lambda: self.units[1].update({"start": 2}),
            lambda: self.units[1].update({"end": float("nan")}),
        ]
        original_units, original_tr = copy.deepcopy(self.units), dict(self.translations)
        for mutation in mutations:
            self.units, self.translations = copy.deepcopy(original_units), dict(original_tr)
            mutation()
            self.save_inputs()
            with patch.object(review, "call_jev") as call, self.assertRaises(ValueError):
                review.main(self.argv)
            call.assert_not_called()

    def test_duplicate_json_translation_key_is_rejected(self):
        self.tr.write_text('{"1":"a","1":"b"}')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            load_inputs(self.sent, self.tr)

    def test_malformed_api_responses_are_failures_not_clear(self):
        mutations = [
            lambda r: r["answers"].pop("flow"),
            lambda r: r["answers"]["flow"].update({"confidence": float("nan")}),
            lambda r: r["answers"]["flow"].update({"choice": "invented"}),
            lambda r: r["answers"]["flow"]["probabilities"].update({"clear": 0.2}),
            lambda r: r.update({"usage": {"input_tokens": -1, "output_tokens": 1}}),
        ]
        for mutation in mutations:
            data = response()
            mutation(data)
            code, _ = self.run_review(value=data)
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(self.report.read_text())["status"], "failed")

    def test_choice_disagreeing_with_probabilities_is_flagged_uncertain(self):
        data = response()
        data["answers"]["flow"]["choice"] = "issue"
        code, _ = self.run_review(value=data)
        self.assertEqual(code, 2)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["status"], "completed")
        answer = report["results"][0]["answers"]["flow"]
        self.assertEqual((answer["choice"], answer["reported_choice"]), ("uncertain", "issue"))
        self.assertEqual(report["results"][0]["flagged_dimensions"], ["flow"])
        self.assertIn("inconsistent", self.report.with_suffix(".md").read_text())

    def test_http_401_does_not_retry_or_expose_response_body(self):
        error = urllib.error.HTTPError(review.ENDPOINT, 401, "Unauthorized", {},
                                       io.BytesIO(b"test-only-secret upstream echo"))
        with patch.object(review.urllib.request, "build_opener") as opener, patch.object(review.time, "sleep") as sleep:
            opener.return_value.open.side_effect = error
            with self.assertRaises(review.ReviewError) as caught:
                review.call_jev({}, "test-only-secret", 1, **self.log_context)
        self.assertNotIn("test-only-secret", str(caught.exception))
        self.assertEqual(opener.return_value.open.call_count, 1)
        sleep.assert_not_called()
        events = self.read_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1]["outcome"], "http_error")
        self.assertEqual(events[-1]["http_status"], 401)
        self.assertIsNone(events[-1]["usage"])
        self.assertNotIn("test-only-secret", self.api_log.read_text())

    def test_rate_limits_retry_bounded_and_authorization_is_header_only(self):
        errors = [urllib.error.HTTPError(review.ENDPOINT, 429, "Limit", {"Retry-After": "99"}, io.BytesIO()) for _ in range(3)]
        with patch.object(review.urllib.request, "build_opener") as opener, patch.object(review.time, "sleep") as sleep:
            opener.return_value.open.side_effect = errors
            with self.assertRaises(review.ReviewError):
                review.call_jev({"state": "test"}, "test-only-secret", 1, **self.log_context)
        self.assertEqual(opener.return_value.open.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [30, 30])
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-only-secret")
        self.assertNotIn(b"test-only-secret", request.data)
        self.assertEqual(request.full_url, review.ENDPOINT)
        finished = [e for e in self.read_events() if e["event"] == "attempt_finished"]
        self.assertEqual([e["attempt"] for e in finished], [1, 2, 3])
        self.assertEqual([e["retry_delay_seconds"] for e in finished], [30, 30, None])
        self.assertTrue(all(e["http_status"] == 429 for e in finished))
        self.assertEqual(len({e["request_id"] for e in finished}), 1)

    def test_http_success_parses_json(self):
        with patch.object(review.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value.__enter__.return_value.status = 200
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(response()).encode()
            self.assertEqual(review.call_jev({}, "test-only-secret", 1, **self.log_context), response())

    def test_timeout_never_retries_and_redirects_are_disabled(self):
        with patch.object(review.urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError()
            with self.assertRaisesRegex(review.ReviewError, "No automatic retry"):
                review.call_jev({}, "test-only-secret", 1, **self.log_context)
            self.assertEqual(opener.return_value.open.call_count, 1)
        self.assertIsNone(review.NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.invalid"))
        finished = self.read_events()[-1]
        self.assertEqual(finished["outcome"], "network_error")
        self.assertIsNone(finished["http_status"])
        self.assertIsNone(finished["usage"])

    def read_events(self):
        return [json.loads(line) for line in self.api_log.read_text().splitlines()]

    @staticmethod
    def http_response(data):
        stream = io.BytesIO(data if isinstance(data, bytes) else json.dumps(data).encode())
        stream.status = 200
        return stream

    def test_history_accumulates_across_real_client_runs_without_source_text(self):
        with patch.object(review.urllib.request, "build_opener") as opener, contextlib.redirect_stdout(io.StringIO()):
            opener.return_value.open.side_effect = lambda *a, **k: self.http_response(response())
            self.assertEqual(review.main(self.argv), 0)
            first_bytes = self.api_log.read_bytes()
            first_report = json.loads(self.report.read_text())
            self.assertEqual(review.main(self.argv), 0)
        self.assertTrue(self.api_log.read_bytes().startswith(first_bytes))
        events = self.read_events()
        self.assertEqual(len(events), 8)  # 2 runs x 2 windows x start/finish
        self.assertEqual(len({e["run_id"] for e in events}), 2)
        self.assertEqual(len({e["request_id"] for e in events}), 4)
        self.assertEqual(events[0]["run_id"], first_report["run_id"])
        self.assertEqual(first_report["api_log_path"], str(self.api_log.resolve()))
        finished = [e for e in events if e["event"] == "attempt_finished"]
        self.assertTrue(all(e["outcome"] == "success" and e["http_status"] == 200 for e in finished))
        self.assertEqual(sum(e["usage"]["input_tokens"] for e in finished), 400)
        self.assertEqual(finished[0]["answers"]["flow"]["choice"], "clear")
        self.assertEqual(finished[0]["resolved_model"], "jev-test")
        self.assertGreaterEqual(finished[0]["elapsed_seconds"], 0)
        for forbidden in ("test-only-secret", "If the request fails", "요청이 실패하면", "Authorization"):
            self.assertNotIn(forbidden, self.api_log.read_text())
        self.assertEqual(self.api_log.stat().st_mode & 0o777, 0o600)

    def test_retry_then_success_has_distinct_attempt_outcomes(self):
        limited = urllib.error.HTTPError(review.ENDPOINT, 529, "busy", {}, io.BytesIO())
        with patch.object(review.urllib.request, "build_opener") as opener, patch.object(review.time, "sleep"):
            opener.return_value.open.side_effect = [limited, self.http_response(response())]
            review.call_jev({}, "test-only-secret", 1, **self.log_context)
        finished = [e for e in self.read_events() if e["event"] == "attempt_finished"]
        self.assertEqual([e["outcome"] for e in finished], ["http_error", "success"])
        self.assertEqual([e["http_status"] for e in finished], [529, 200])

    def test_invalid_json_and_contract_have_separate_log_outcomes(self):
        invalid_contract = response()
        invalid_contract["answers"].pop("flow")
        for body in (b"not-json test-only-secret", invalid_contract):
            with patch.object(review.urllib.request, "build_opener") as opener:
                opener.return_value.open.return_value = self.http_response(body)
                with self.assertRaises(review.ReviewError):
                    review.call_jev({}, "test-only-secret", 1, **self.log_context)
        finished = [e for e in self.read_events() if e["event"] == "attempt_finished"]
        self.assertEqual([e["outcome"] for e in finished], ["invalid_json", "invalid_response"])
        self.assertIsNone(finished[0]["usage"])
        self.assertEqual(finished[1]["usage"]["input_tokens"], 100)
        self.assertNotIn("test-only-secret", self.api_log.read_text())

    def test_interruption_is_logged_without_claiming_success(self):
        with patch.object(review.urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                review.call_jev({}, "test-only-secret", 1, **self.log_context)
        self.assertEqual(self.read_events()[-1]["outcome"], "interrupted")

    def test_unwritable_log_stops_before_network(self):
        self.api_log.mkdir()
        with patch.object(review.urllib.request, "build_opener") as opener, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(review.main(self.argv), 1)
            opener.return_value.open.assert_not_called()
        self.assertEqual(json.loads(self.report.read_text())["status"], "failed")

    def test_finish_log_failure_stops_after_one_request(self):
        append = review.append_api_log
        writes = []

        def fail_on_finish(path, event):
            writes.append(event["event"])
            if event["event"] == "attempt_finished":
                raise review.ReviewError("Cannot append Jev API history")
            append(path, event)

        with patch.object(review.urllib.request, "build_opener") as opener, \
                patch.object(review, "append_api_log", side_effect=fail_on_finish), \
                contextlib.redirect_stdout(io.StringIO()):
            opener.return_value.open.return_value = self.http_response(response())
            self.assertEqual(review.main(self.argv), 1)
            self.assertEqual(opener.return_value.open.call_count, 1)
        self.assertEqual(writes, ["attempt_started", "attempt_finished"])
        self.assertEqual(len(self.read_events()), 1)
        self.assertEqual(json.loads(self.report.read_text())["status"], "failed")

    def test_concurrent_log_writers_keep_valid_json_lines(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: review.append_api_log(self.api_log, {"index": i}), range(40)))
        self.assertEqual(sorted(e["index"] for e in self.read_events()), list(range(40)))

    def test_timestamp_rounding_carries_into_minutes(self):
        self.assertEqual(fmt(59.9996, ","), "00:01:00,000")
        self.assertEqual(fmt(3599.9996, "."), "01:00:00.000")


if __name__ == "__main__":
    unittest.main()
