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
import logging
import unittest
import traceback
import multiprocessing
from pathlib import Path
from datetime import datetime

from sdcm.prometheus import start_metrics_server
from sdcm.utils.decorators import timeout
from sdcm.sct_events import Severity
from sdcm.sct_events.system import CoreDumpEvent, TestFrameworkEvent
from sdcm.sct_events.filters import DbEventsFilter, EventsFilter, EventsSeverityChangerFilter
from sdcm.sct_events.loaders import YcsbStressEvent
from sdcm.sct_events.nemesis import DisruptionEvent
from sdcm.sct_events.database import DatabaseLogEvent
from sdcm.sct_events.file_logger import get_logger_event_summary

from unit_tests.lib.events_utils import EventsUtilsMixin

LOGGER = logging.getLogger(__name__)


class BaseEventsTest(unittest.TestCase, EventsUtilsMixin):
    killed = multiprocessing.Event()

    @classmethod
    def setUpClass(cls) -> None:
        start_metrics_server()
        cls.setup_events_processes(events_device=True, events_main_device=False, registry_patcher=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.teardown_events_processes()

    @classmethod
    def get_event_log_file(cls, name: str) -> str:
        if (log_file := Path(cls.temp_dir, "events_log", name)).exists():
            return log_file.read_text()
        return ""

    @timeout(timeout=10, sleep_time=0.05)
    def wait_for_event_summary(self):
        return get_logger_event_summary(_registry=self.events_processes_registry)


class SctEventsTests(BaseEventsTest):  # pylint: disable=too-many-public-methods
    @staticmethod
    def test_disruption_event():
        try:
            1 / 0
        except ZeroDivisionError:
            _full_traceback = traceback.format_exc()

        str(DisruptionEvent(type="ChaosMonkeyLimited",
                            subtype='end',
                            status=False,
                            error=str(Exception("long one")),
                            full_traceback=_full_traceback,
                            duration=20,
                            start=1,
                            end=2,
                            node='test'))

        str(DisruptionEvent(type="ChaosMonkeyLimited",
                            subtype='end',
                            status=True,
                            duration=20,
                            start=1,
                            end=2,
                            node='test'))

        print(str(DisruptionEvent(type="ChaosMonkeyLimited",
                                  subtype='start',
                                  status=True,
                                  node='test')))

    def test_filter(self):
        enospc_line_1 = \
            "[99.80.124.204] [stdout] Mar 31 09:08:10 warning|  [shard 8] commitlog - Exception in segment " \
            "reservation: storage_io_error (Storage I/O error: 28: No space left on device)"
        enospc_line_2 = \
            "2019-10-29T12:19:49+00:00  ip-172-30-0-184 !WARNING | scylla: [shard 2] storage_service - Commitlog " \
            "error: std::filesystem::__cxx11::filesystem_error (error system:28, filesystem error: open failed: No " \
            "space left on device [/var/lib/scylla/hints/2/172.30.0.116/HintsLog-1-36028797019122576.log])"

        log_content_before = self.get_event_log_file("events.log")

        # 13 events in total: 2 events per filter x 4 filters + 5 events.
        with self.wait_for_n_events(self.get_events_logger(), count=13, timeout=3):
            with DbEventsFilter(db_event=DatabaseLogEvent.NO_SPACE_ERROR), \
                    DbEventsFilter(db_event=DatabaseLogEvent.BACKTRACE, line="No space left on device"), \
                    DbEventsFilter(db_event=DatabaseLogEvent.DATABASE_ERROR, line="No space left on device"), \
                    DbEventsFilter(db_event=DatabaseLogEvent.FILESYSTEM_ERROR, line="No space left on device"):
                DatabaseLogEvent.NO_SPACE_ERROR().add_info(node="A", line_number=22, line=enospc_line_1).publish()
                DatabaseLogEvent.BACKTRACE().add_info(node="A", line_number=22, line=enospc_line_1).publish()
                DatabaseLogEvent.FILESYSTEM_ERROR().add_info(node="A", line_number=22, line=enospc_line_2).publish()
                DatabaseLogEvent.DATABASE_ERROR().add_info(node="A", line_number=22, line=enospc_line_1).publish()
                DatabaseLogEvent.NO_SPACE_ERROR().add_info(node="A", line_number=22, line=enospc_line_1).publish()

        self.assertEqual(log_content_before, self.get_event_log_file("events.log"))

    def test_general_filter(self):
        with self.wait_for_n_events(self.get_events_logger(), count=4, timeout=3):
            with EventsFilter(event_class=CoreDumpEvent):
                CoreDumpEvent(corefile_url="http://",
                              backtrace="asfasdfsdf",
                              node="node xy",
                              download_instructions="test_general_filter",
                              timestamp=1578998425.0).publish()  # Tue 2020-01-14 10:40:25 UTC
                TestFrameworkEvent(source="", source_method="").publish()

        log_content = self.get_event_log_file("events.log")

        self.assertIn("TestFrameworkEvent", log_content)
        self.assertNotIn("test_general_filter", log_content)

    def test_general_filter_regex(self):
        with self.wait_for_n_events(self.get_events_logger(), count=4, timeout=3):
            with EventsFilter(regex=".*1234567890.*") as filter:
                CoreDumpEvent(corefile_url="http://",
                              backtrace="asfasdfsdf",
                              node="node xy",
                              download_instructions="gsutil cp gs://upload.scylladb.com/core.scylla-jmx.996.1234567890"
                                                    ".3968.1566979933000/core.scylla-jmx.996.d173729352e34c76aaf8db334"
                                                    "2153c3e.3968.1566979933000000 .",
                              timestamp=1578998425.0).publish()  # Tue 2020-01-14 10:40:25 UTC
                TestFrameworkEvent(source="", source_method="").publish()

        log_content = self.get_event_log_file("events.log")

        self.assertIn("TestFrameworkEvent", log_content)
        self.assertNotIn("1234567890", log_content)

    def test_severity_changer(self):
        with self.wait_for_n_events(self.get_events_logger(), count=4, timeout=3):
            with EventsSeverityChangerFilter(new_severity=Severity.WARNING,
                                             event_class=TestFrameworkEvent,
                                             extra_time_to_expiration=10):
                TestFrameworkEvent(source="critical that should be lowered #1",
                                   source_method="",
                                   severity=Severity.CRITICAL).publish()
            TestFrameworkEvent(source="critical that should be lowered #2",
                               source_method="",
                               severity=Severity.CRITICAL).publish()

        log_content = self.get_event_log_file("warning.log")

        self.assertIn("TestFrameworkEvent", log_content)
        self.assertIn("critical that should be lowered #1", log_content)
        self.assertIn("critical that should be lowered #2", log_content)

    def test_severity_changer_db_log(self):
        """
            See https://github.com/scylladb/scylla-cluster-tests/issues/2115
        """
        # 1) Lower DatabaseLogEvent to WARNING for 1 sec.
        with self.wait_for_n_events(self.get_events_logger(), count=4, timeout=3):
            with EventsSeverityChangerFilter(new_severity=Severity.WARNING,
                                             event_class=DatabaseLogEvent,
                                             extra_time_to_expiration=1):
                DatabaseLogEvent.NO_SPACE_ERROR() \
                    .add_info(node="A", line_number=22, line="critical that should be lowered #1") \
                    .publish()
            DatabaseLogEvent.NO_SPACE_ERROR() \
                .add_info(node="A", line_number=22, line="critical that should be lowered #2") \
                .publish()

        log_content = self.get_event_log_file("warning.log")

        self.assertIn("DatabaseLogEvent", log_content)
        self.assertIn("critical that should be lowered #1", log_content)
        self.assertIn("critical that should be lowered #2", log_content)

        # 2) One of the next DatabaseLogEvent event should expire the EventsSeverityChangerFilter
        #    (and not crash all subscribers)
        with self.wait_for_n_events(self.get_events_logger(), count=2, timeout=3):
            for _ in range(2):
                time.sleep(1)
                DatabaseLogEvent.NO_SPACE_ERROR() \
                    .add_info(node="A", line_number=22, line="critical that shouldn't be lowered") \
                    .publish()

        log_content = self.get_event_log_file("error.log")

        self.assertIn("critical that shouldn't be lowered", log_content)

    def test_ycsb_filter(self):
        with self.wait_for_n_events(self.get_events_logger(), count=4, timeout=3):
            with EventsFilter(event_class=YcsbStressEvent,
                              regex=".*Internal server error: exceptions::unavailable_exception.*"):
                YcsbStressEvent.error(
                    node="Node alternator-3h-silence--loader-node-bb90aa05-2"
                         " [34.251.153.122 | 10.0.220.55] (seed: False)",
                    stress_cmd="ycsb",
                    errors=["237951 [Thread-47] ERROR site.ycsb.db.DynamoDBClient"
                            " -com.amazonaws.AmazonServiceException: Internal server error:"
                            " exceptions::unavailable_exception (Cannot achieve consistency"
                            " level for cl LOCAL_ONE. Requires 1, alive 0) (Service: AmazonDynamoDBv2;"
                            " Status Code: 500; Error Code: Internal Server Error; Request ID: null)"]).publish()
                TestFrameworkEvent(source="", source_method="").publish()

        log_content = self.get_event_log_file("events.log")

        self.assertIn("TestFrameworkEvent", log_content)
        self.assertNotIn("YcsbStressEvent", log_content)

        with self.wait_for_n_events(self.get_events_logger(), count=1):
            YcsbStressEvent.error(
                node="Node alternator-3h-silence--loader-node-bb90aa05-2"
                     " [34.251.153.122 | 10.0.220.55] (seed: False)",
                stress_cmd="ycsb",
                errors=["237951 [Thread-47] ERROR site.ycsb.db.DynamoDBClient"
                        " -com.amazonaws.AmazonServiceException: Internal server error:"
                        " exceptions::unavailable_exception (Cannot achieve consistency"
                        " level for cl LOCAL_ONE. Requires 1, alive 0) (Service: AmazonDynamoDBv2;"
                        " Status Code: 500; Error Code: Internal Server Error; Request ID: null)"]).publish()

        log_content = self.get_event_log_file("events.log")

        self.assertIn("TestFrameworkEvent", log_content)
        self.assertIn("YcsbStressEvent", log_content)

    def test_filter_repair(self):
        failed_repaired_line = "2019-07-28T10:53:29+00:00  ip-10-0-167-91 !INFO    | scylla.bin: [shard 0] repair - " \
                               "Got error in row level repair: std::runtime_error (repair id 1 is aborted on shard 0)"

        # 9 events in total: 2 events per filter x 3 filters + 3 events.
        with self.wait_for_n_events(self.get_events_logger(), count=9, timeout=3):
            with DbEventsFilter(db_event=DatabaseLogEvent.DATABASE_ERROR,
                                line="repair's stream failed: streaming::stream_exception"), \
                    DbEventsFilter(db_event=DatabaseLogEvent.RUNTIME_ERROR,
                                   line="Can not find stream_manager"), \
                    DbEventsFilter(db_event=DatabaseLogEvent.RUNTIME_ERROR, line="is aborted"):

                DatabaseLogEvent.RUNTIME_ERROR().add_info(node="A", line_number=22, line=failed_repaired_line).publish()
                DatabaseLogEvent.RUNTIME_ERROR().add_info(node="A", line_number=22, line=failed_repaired_line).publish()
                DatabaseLogEvent.NO_SPACE_ERROR().add_info(node="B", line_number=22, line="not filtered").publish()

        log_content = self.get_event_log_file("events.log")

        self.assertIn("not filtered", log_content)
        self.assertNotIn("repair id 1", log_content)

    def test_filter_upgrade(self):
        known_failure_line = "!ERR     | scylla:  [shard 3] storage_proxy - Exception when communicating with " \
                             "10.142.0.56: std::runtime_error (Failed to load schema version " \
                             "b40e405f-462c-38f2-a90c-6f130ddbf6f3) "

        with self.wait_for_n_events(self.get_events_logger(), count=5, timeout=3):
            with DbEventsFilter(db_event=DatabaseLogEvent.RUNTIME_ERROR, line="Failed to load schema"):
                DatabaseLogEvent.RUNTIME_ERROR().add_info(node="A", line_number=22, line=known_failure_line).publish()
                DatabaseLogEvent.RUNTIME_ERROR().add_info(node="A", line_number=22, line=known_failure_line).publish()
                DatabaseLogEvent.NO_SPACE_ERROR().add_info(node="B", line_number=22, line="not filtered").publish()

        log_content = self.get_event_log_file("events.log")

        self.assertIn("not filtered", log_content)
        self.assertNotIn("Exception when communicating", log_content)

    def test_filter_by_node(self):
        with self.wait_for_n_events(self.get_events_logger(), count=4, timeout=3):
            with DbEventsFilter(db_event=DatabaseLogEvent.NO_SPACE_ERROR, node="A"):
                DatabaseLogEvent.NO_SPACE_ERROR().add_info(node="A", line_number=22, line="this is filtered").publish()
                DatabaseLogEvent.NO_SPACE_ERROR().add_info(node="B", line_number=22, line="not filtered").publish()

        log_content = self.get_event_log_file("events.log")

        self.assertIn("not filtered", log_content)
        self.assertNotIn("this is filtered", log_content)

    def test_filter_expiration(self):
        with self.wait_for_n_events(self.get_events_logger(), count=5, timeout=10):
            line_prefix = f"{datetime.utcnow():%Y-%m-%dT%H:%M:%S+00:00}"

            with DbEventsFilter(db_event=DatabaseLogEvent.NO_SPACE_ERROR, node="A"):
                DatabaseLogEvent.NO_SPACE_ERROR() \
                    .add_info(node="A", line_number=22, line=line_prefix + " this is filtered") \
                    .publish()

            time.sleep(2)

            DatabaseLogEvent.NO_SPACE_ERROR() \
                .add_info(node="A", line_number=22, line=line_prefix + " this is filtered") \
                .publish()

            time.sleep(2)

            line_prefix = f"{datetime.utcnow():%Y-%m-%dT%H:%M:%S+00:00}"

            DatabaseLogEvent.NO_SPACE_ERROR() \
                .add_info(node="A", line_number=22, line=line_prefix + " this is not filtered") \
                .publish()

        log_content = self.get_event_log_file("events.log")

        self.assertIn("this is not filtered", log_content)
        self.assertNotIn("this is filtered", log_content)

    def test_default_filters(self):
        with self.wait_for_n_events(self.get_events_logger(), count=2):
            DatabaseLogEvent.BACKTRACE() \
                .add_info(node="A",
                          line_number=22,
                          line="Jul 01 03:37:31 ip-10-0-127-151.eu-west-1.compute.internal"
                               " scylla[6026]:Rate-limit: supressed 4294967292 backtraces on shard 5") \
                .publish()
            DatabaseLogEvent.BACKTRACE() \
                .add_info(node="A", line_number=22, line="other back trace that shouldn't be filtered") \
                .publish()

        log_content = self.get_event_log_file("events.log")

        self.assertIn("other back trace", log_content)
        self.assertNotIn("supressed", log_content)

    def test_failed_stall_during_filter(self):
        with self.wait_for_n_events(self.get_events_logger(), count=5, timeout=3):
            with DbEventsFilter(db_event=DatabaseLogEvent.NO_SPACE_ERROR), \
                    DbEventsFilter(db_event=DatabaseLogEvent.BACKTRACE, line="No space left on device"):

                event = DatabaseLogEvent.REACTOR_STALLED()
                event.add_info(node="A",
                               line_number=22,
                               line="[99.80.124.204] [stdout] Mar 31 09:08:10 warning|  reactor stall 20").publish()

        self.assertEqual(event.severity, Severity.WARNING)
