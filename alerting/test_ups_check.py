import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import ups_check  # noqa: E402

UPSC_OUTPUT = """\
battery.charge: 98
battery.runtime: 4452
battery.voltage: 27.4
device.serial: XX0000TEST00
ups.load: 8
ups.status: OL CHRG
"""


def data(status, **extra):
    d = {"ups.status": status, "battery.charge": "60", "battery.runtime": "1800", "ups.load": "9"}
    d.update(extra)
    return d


class ParseTests(unittest.TestCase):
    def test_parses_key_values(self):
        d = ups_check.parse_upsc(UPSC_OUTPUT)
        self.assertEqual(d["ups.status"], "OL CHRG")
        self.assertEqual(d["battery.runtime"], "4452")
        self.assertEqual(d["device.serial"], "XX0000TEST00")

    def test_ignores_noise_lines(self):
        d = ups_check.parse_upsc("Init SSL without certificate database\nups.status: OL\n")
        self.assertEqual(d, {"ups.status": "OL"})


class EvaluateTests(unittest.TestCase):
    def test_on_mains_is_ok(self):
        ok, reason = ups_check.evaluate(data("OL CHRG"))
        self.assertTrue(ok)
        self.assertEqual(reason, "on mains (battery 60%, ~30 min runtime, load 9%)")

    def test_on_battery_fails(self):
        ok, reason = ups_check.evaluate(data("OB DISCHRG"))
        self.assertFalse(ok)
        self.assertIn("on battery, mains power lost", reason)
        self.assertIn("~30 min runtime", reason)

    def test_low_battery_wins_over_on_battery(self):
        ok, reason = ups_check.evaluate(data("OB LB"))
        self.assertFalse(ok)
        self.assertIn("LOW", reason)

    def test_replace_battery_fails_even_on_mains(self):
        ok, reason = ups_check.evaluate(data("OL RB"))
        self.assertFalse(ok)
        self.assertIn("needs replacing", reason)

    def test_overload_fails(self):
        self.assertFalse(ups_check.evaluate(data("OL OVER"))[0])

    def test_no_data_fails(self):
        ok, reason = ups_check.evaluate({})
        self.assertFalse(ok)
        self.assertIn("unavailable", reason)

    def test_unknown_status_fails(self):
        ok, reason = ups_check.evaluate(data("BYPASS"))
        self.assertFalse(ok)
        self.assertIn("BYPASS", reason)


class ReadUpsTests(unittest.TestCase):
    def test_nonzero_exit_returns_empty(self):
        res = subprocess.CompletedProcess([], 1, stdout="", stderr="Error: Driver not connected")
        with mock.patch("subprocess.run", return_value=res):
            self.assertEqual(ups_check.read_ups("apc@localhost"), {})

    def test_missing_upsc_returns_empty(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(ups_check.read_ups("apc@localhost"), {})


class MainTests(unittest.TestCase):
    def run_main(self, upsc_data):
        pings = []
        env = {"UPS_HC_PING_URL": "https://hc.example/abc", "UPS_NAME": "apc@localhost"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(ups_check, "read_ups", return_value=upsc_data), \
                mock.patch.object(ups_check, "ping", side_effect=lambda *a: pings.append(a)):
            rc = ups_check.main()
        return rc, pings

    def test_success_ping_on_mains(self):
        rc, pings = self.run_main(data("OL"))
        self.assertEqual(rc, 0)
        self.assertEqual(pings[0][:2], ("https://hc.example/abc", True))

    def test_fail_ping_on_battery(self):
        rc, pings = self.run_main(data("OB"))
        self.assertEqual(rc, 0)
        self.assertFalse(pings[0][1])

    def test_missing_url_exits_2(self):
        with mock.patch.dict(os.environ, {"UPS_HC_PING_URL": ""}):
            self.assertEqual(ups_check.main(), 2)

    def test_unreachable_healthchecks_does_not_crash(self):
        env = {"UPS_HC_PING_URL": "https://hc.example/abc"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(ups_check, "read_ups", return_value=data("OB")), \
                mock.patch.object(ups_check, "ping", side_effect=OSError("down")):
            self.assertEqual(ups_check.main(), 0)


if __name__ == "__main__":
    unittest.main()
