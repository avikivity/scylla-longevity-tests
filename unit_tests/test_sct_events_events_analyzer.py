# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
#
# Copyright (c) 2020 ScyllaDB

import time
import unittest
import unittest.mock

from sdcm.sct_events.base import Severity, SctEvent
from sdcm.sct_events.system import TestResultEvent
from sdcm.sct_events.setup import EVENTS_SUBSCRIBERS_START_DELAY
from sdcm.sct_events.events_analyzer import EventsAnalyzer, start_events_analyzer
from sdcm.sct_events.events_processes import EVENTS_ANALYZER_ID, get_events_process

from unit_tests.lib.events_utils import EventsUtilsMixin


class TestEventsAnalyzer(unittest.TestCase, EventsUtilsMixin):
    @classmethod
    def setUpClass(cls) -> None:
        cls.setup_events_processes(events_device=False, events_main_device=True, registry_patcher=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.teardown_events_processes()

    def test_events_analyzer(self):
        start_events_analyzer(_registry=self.events_processes_registry)
        events_analyzer = get_events_process(name=EVENTS_ANALYZER_ID, _registry=self.events_processes_registry)

        time.sleep(EVENTS_SUBSCRIBERS_START_DELAY)

        try:
            self.assertIsInstance(events_analyzer, EventsAnalyzer)
            self.assertTrue(events_analyzer.is_alive())
            self.assertEqual(events_analyzer._registry, self.events_main_device._registry)
            self.assertEqual(events_analyzer._registry, self.events_processes_registry)

            event1 = TestResultEvent("CRITICAL", {})
            event1.severity = Severity.CRITICAL

            event2 = SctEvent()
            event2.severity = Severity.CRITICAL

            with unittest.mock.patch("sdcm.sct_events.events_analyzer.EventsAnalyzer.kill_test") as mock:
                with self.wait_for_n_events(events_analyzer, count=2, timeout=1):
                    self.events_main_device.publish_event(event1)
                    self.events_main_device.publish_event(event2)

            self.assertEqual(self.events_main_device.events_counter, events_analyzer.events_counter)

            mock.assert_called_once()
        finally:
            events_analyzer.stop(timeout=1)
