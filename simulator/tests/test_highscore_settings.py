import pathlib
import sys
import unittest


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.highscore.settings import SearchSettings  # noqa: E402


class SearchSettingsDefaultTests(unittest.TestCase):
    def test_monotone_ingress_is_disabled_by_default(self):
        self.assertFalse(SearchSettings().use_monotone_ingress)

    def test_geometry_rescue_is_disabled_by_default_after_physical_gate_rejection(self):
        self.assertFalse(SearchSettings().use_geometry_rescue)
