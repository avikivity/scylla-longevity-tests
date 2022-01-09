#!/usr/bin/env python

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
# Copyright (c) 2021 ScyllaDB
import logging
import re
from functools import partial

from sdcm.cluster import BaseNode
from sdcm.nemesis import StartStopMajorCompaction, StartStopScrubCompaction, StartStopCleanupCompaction, \
    StartStopValidationCompaction
from sdcm.rest.storage_service_client import StorageServiceClient
from sdcm.tester import ClusterTester
from sdcm.utils.common import ParallelObject
from sdcm.utils.compaction_ops import CompactionOps


LOGGER = logging.getLogger(__name__)


class StopCompactionTest(ClusterTester):
    GREP_PATTERN = r"Compaction for ([\w/\d]+) was stopped"

    def setUp(self):
        super().setUp()
        self.node = self.db_cluster.nodes[0]
        self.storage_service_client = StorageServiceClient(self.node)
        self.populate_data_parallel(size_in_gb=10, blocking=True)
        self.disable_autocompaction_on_all_nodes()

    def disable_autocompaction_on_all_nodes(self):
        compaction_ops = CompactionOps(cluster=self.db_cluster)
        compaction_ops.disable_autocompaction_on_ks_cf(node=self.node)

    def test_stop_compaction(self):
        with self.subTest("Stop upgrade compaction test"):
            self.stop_upgrade_compaction()

        with self.subTest("Stop major compaction test"):
            self.stop_major_compaction()

        with self.subTest("Stop scrub compaction test"):
            self.stop_scrub_compaction()

        with self.subTest("Stop cleanup compaction test"):
            self.stop_cleanup_compaction()

        with self.subTest("Stop validation compaction test"):
            self.stop_validation_compaction()

        with self.subTest("Stop reshape compaction test"):
            self.stop_reshape_compaction()

    def stop_major_compaction(self):
        """
        Test that we can stop a major compaction with <nodetool stop COMPACTION>.
        1. Use the StopStartMajorCompaction nemesis to trigger the
        major compaction and stop it mid-flight with <nodetool stop
        COMPACTION>.
        2. Grep the logs for a line informing of the major compaction being
        stopped due to a user request.
        3. Assert that we found the line we were grepping for.
        """
        self._stop_compaction_base_test_scenario(
            compaction_nemesis=StartStopMajorCompaction(
                tester_obj=self,
                termination_event=self.db_cluster.nemesis_termination_event))

    def stop_scrub_compaction(self):
        """
        Test that we can stop a scrub compaction with <nodetool stop SCRUB>.
        1. Use the StopStartScrubCompaction nemesis to trigger the
        major compaction and stop it mid-flight with <nodetool stop
        SCRUB>.
        2. Grep the logs for a line informing of the scrub compaction being
        stopped due to a user request.
        3. Assert that we found the line we were grepping for.
        """
        self._stop_compaction_base_test_scenario(
            compaction_nemesis=StartStopScrubCompaction(
                tester_obj=self,
                termination_event=self.db_cluster.nemesis_termination_event))

    def stop_cleanup_compaction(self):
        """
        Test that we can stop a cleanup compaction with <nodetool stop CLEANUP>.
        1. Use the StopStartCleanupCompaction nemesis to trigger the
        major compaction and stop it mid-flight with <nodetool stop
        CLEANUP>.
        2. Grep the logs for a line informing of the cleanup compaction being
        stopped due to a user request.
        3. Assert that we found the line we were grepping for.
        """
        self._stop_compaction_base_test_scenario(
            compaction_nemesis=StartStopCleanupCompaction(
                tester_obj=self,
                termination_event=self.db_cluster.nemesis_termination_event))

    def stop_validation_compaction(self):
        """
        Test that we can stop a validation compaction with
        <nodetool stop VALIDATION>.
        1. Use the StopStartValidationCompaction nemesis to trigger the
        major compaction and stop it mid-flight with <nodetool stop
        CLEANUP>.
        2. Grep the logs for a line informing of the validation
        compaction being stopped due to a user request.
        3. Assert that we found the line we were grepping for.
        """
        self._stop_compaction_base_test_scenario(
            compaction_nemesis=StartStopValidationCompaction(
                tester_obj=self,
                termination_event=self.db_cluster.nemesis_termination_event))

    def stop_upgrade_compaction(self):
        """
        Test that we can stop an upgrade compaction with <nodetool stop UPGRADE>.

        Prerequisite:
        The initial setup in scylla.yaml must include 2 settings:
            enable_sstables_mc_format: true
            enable_sstables_md_format: false
        This is necessary for the test to be able to go from the legacy
        "mc" sstable format to the newer "md" format.

        1. Flush the data from memtables to sstables.
        2. Stop scylla on a given node.
        3. Update the scylla.yaml configuration to enable the mc
        sstable format.
        4. Restart scylla.
        5. Trigger the upgrade compaction using the API request.
        6. Stop the compaction mid-flight with <nodetool stop UPGRADE>.
        7. Grep the logs for a line informing of the upgrade compaction being
        stopped due to a user request.
        8. Assert that we found the line we were grepping for.
        """
        compaction_ops = CompactionOps(cluster=self.db_cluster, node=self.node)
        timeout = 300
        upgraded_configuration_options = {"enable_sstables_mc_format": False,
                                          "enable_sstables_md_format": True}
        trigger_func = partial(compaction_ops.trigger_upgrade_compaction)
        watch_func = partial(compaction_ops.stop_on_user_compaction_logged,
                             node=self.node,
                             mark=self.node.mark_log(),
                             watch_for="Upgrade keyspace1.standard1",
                             timeout=timeout,
                             stop_func=compaction_ops.stop_upgrade_compaction)

        def _upgrade_sstables_format(node: BaseNode):
            LOGGER.info("Upgrading sstables format...")
            with node.remote_scylla_yaml() as scylla_yaml:
                scylla_yaml.update(upgraded_configuration_options)

        try:
            compaction_ops.trigger_flush()
            self.node.stop_scylla()
            _upgrade_sstables_format(self.node)
            self.node.start_scylla()
            self.wait_no_compactions_running()
            ParallelObject(objects=[trigger_func, watch_func], timeout=timeout).call_objects()
            self._grep_log_and_assert(self.node)
        finally:
            self.node.running_nemesis = False

    def stop_reshape_compaction(self):
        """
        Test that we can stop a reshape compaction with <nodetool stop RESHAPE>.
        To trigger a reshape compaction, the current CompactionStrategy
        must not be aligned with the shape of the stored sstables. In
        this case we're setting the new strategy to
        TimeWindowCompactionStrategy with a very small time window.

        1. Flush the memtable data to sstables.
        2. Copy sstable files to the upload and staging dirs.
        3. Change the compaction strategy to TimeWindowCompactionStrategy.
        4. Run <nodetool refresh> command to trigger the compaction.
        5. Stop the compaction mid-flight with <nodetool stop RESHAPE>.
        6. Grep the logs for a line informing of the reshape compaction
        being stopped due to a user request.
        7. Assert that we found the line we were grepping for.
        """
        node = self.node
        compaction_ops = CompactionOps(cluster=self.db_cluster, node=node)
        timeout = 600

        def _trigger_reshape(node: BaseNode, tester, keyspace: str = "keyspace1"):
            twcs = {'class': 'TimeWindowCompactionStrategy', 'compaction_window_size': 1,
                    'compaction_window_unit': 'MINUTES', 'max_threshold': 1, 'min_threshold': 1}
            compaction_ops.trigger_flush()
            tester.wait_no_compactions_running()
            LOGGER.info("Copying data files to ./staging and ./upload directories...")
            keyspace_dir = f'/var/lib/scylla/data/{keyspace}'
            cf_data_dir = node.remoter.run(f"ls {keyspace_dir}").stdout.splitlines()[0]
            full_dir_path = f"{keyspace_dir}/{cf_data_dir}"
            upload_dir = f"{full_dir_path}/upload"
            staging_dir = f"{full_dir_path}/staging"
            cp_cmd_upload = f"cp -p {full_dir_path}/m* {upload_dir}"
            cp_cmd_staging = f"cp -p {full_dir_path}/m* {staging_dir}"
            node.remoter.sudo(cp_cmd_staging)
            node.remoter.sudo(cp_cmd_upload)
            LOGGER.info("Finished copying data files to ./staging and ./upload directories.")
            cmd = f"ALTER TABLE standard1 WITH compaction={twcs}"
            node.run_cqlsh(cmd=cmd, keyspace="keyspace1")
            node.run_nodetool("refresh -- keyspace1 standard1")

        trigger_func = partial(_trigger_reshape,
                               node=node,
                               tester=self)
        watch_func = partial(compaction_ops.stop_on_user_compaction_logged,
                             node=node,
                             mark=node.mark_log(),
                             watch_for="Reshape keyspace1.standard1",
                             timeout=timeout,
                             stop_func=compaction_ops.stop_reshape_compaction)
        try:
            ParallelObject(objects=[trigger_func, watch_func], timeout=timeout).call_objects()
        finally:
            self._grep_log_and_assert(node)

    def _stop_compaction_base_test_scenario(self,
                                            compaction_nemesis):
        try:
            compaction_nemesis.disrupt()
            node = compaction_nemesis.target_node
            self._grep_log_and_assert(node)
        finally:
            node.running_nemesis = False

    def _grep_log_and_assert(self, node: BaseNode):
        found_grepped_expression = False
        with open(node.system_log, encoding="utf-8") as logfile:
            pattern = re.compile(self.GREP_PATTERN)
            for line in logfile.readlines():
                if pattern.search(line):
                    found_grepped_expression = True

        self.assertTrue(found_grepped_expression, msg=f'Did not find the expected "{self.GREP_PATTERN}" '
                                                      f'expression in the logs.')
