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

# This is stress longevity test that runs light weight transactions in parallel with different node operations:
# disruptive and not disruptive
#
# After the test is finished will be performed the data validation.

import time

from longevity_test import LongevityTest
from sdcm.sct_events.base import Severity
from sdcm.sct_events.filters import EventsSeverityChangerFilter
from sdcm.sct_events.database import DatabaseLogEvent
from sdcm.utils.data_validator import LongevityDataValidator


class LWTLongevityTest(LongevityTest):
    BASE_TABLE_PARTITION_KEYS = ['domain', 'published_date']

    def __init__(self, *args):
        super(LWTLongevityTest, self).__init__(*args)
        self.data_validator = None

    def run_prepare_write_cmd(self):
        # mutation_write_ warning is thrown when system is overloaded and got timeout on operations on system.paxos
        # table. Decrease severity of this event during prepare. Shouldn't impact on test result
        with EventsSeverityChangerFilter(event_class=DatabaseLogEvent, regex=r".*mutation_write_*",
                                         severity=Severity.WARNING, extra_time_to_expiration=30), \
            EventsSeverityChangerFilter(event_class=DatabaseLogEvent, regex=r'.*Operation failed for system.paxos.*',
                                        severity=Severity.WARNING, extra_time_to_expiration=30), \
            EventsSeverityChangerFilter(event_class=DatabaseLogEvent, regex=r'.*Operation timed out for system.paxos.*',
                                        severity=Severity.WARNING, extra_time_to_expiration=30):
            super(LWTLongevityTest, self).run_prepare_write_cmd()

        # Stop nemesis. Prefer all nodes will be run before collect data for validation
        # Increase timeout to wait for nemesis finish
        if self.db_cluster.nemesis_threads:
            self.db_cluster.stop_nemesis(timeout=300)

        # Wait for MVs data will be fully inserted (running on background)
        time.sleep(300)

        self.data_validator = LongevityDataValidator(longevity_self_object=self,
                                                     user_profile_name='c-s_lwt',
                                                     base_table_partition_keys=self.BASE_TABLE_PARTITION_KEYS)

        self.data_validator.copy_immutable_expected_data()
        self.data_validator.copy_updated_expected_data()
        self.data_validator.save_count_rows_for_deletion()

        # Run nemesis during stress as it was stopped before copy expected data
        if self.params.get('nemesis_during_prepare'):
            self.start_nemesis()

    def start_nemesis(self):
        self.db_cluster.start_nemesis()

    def test_lwt_longevity(self):
        self.test_custom_time()

        # Stop nemesis. Prefer all nodes will be run before collect data for validation
        # Increase timeout to wait for nemesis finish
        if self.db_cluster.nemesis_threads:
            self.db_cluster.stop_nemesis(timeout=300)
        self.validate_data()

    def validate_data(self):
        node = self.db_cluster.nodes[0]
        with self.db_cluster.cql_connection_patient(node, keyspace=self.data_validator.keyspace_name) as session:
            self.data_validator.validate_range_not_expected_to_change(session=session)
            self.data_validator.validate_range_expected_to_change(session=session)
            self.data_validator.validate_deleted_rows(session=session)
