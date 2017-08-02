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
# Copyright (c) 2016 ScyllaDB


from avocado import main

from sdcm.tester import ClusterTester


class LongevityTest(ClusterTester):

    """
    Test a Scylla cluster stability over a time period.

    :avocado: enable
    """

    default_params = {'timeout': 650000}

    def test_custom_time(self):
        """
        Run cassandra-stress with params defined in data_dir/scylla.yaml
        """
        self.db_cluster.add_nemesis(nemesis=self.get_nemesis_class(),
                                    loaders=self.loaders,
                                    monitoring_set=self.monitors)
        compaction_strategy = ['SizeTieredCompactionStrategy',
                               'DateTieredCompactionStrategy',
                               'LeveledCompactionStrategy']
        stress_queue = list()
        for cmd in ('stress_cmd', 'stress_cmd_1'):
            stress_cmd = self.params.get(cmd)
            if stress_cmd:
                if 'counter_' in stress_cmd:
                    self._create_counter_table()
                self.log.debug('stress cmd: {}'.format(stress_cmd))
                stress_queue.append(self.run_stress_thread(stress_cmd=stress_cmd,
                                                           keyspace_num=3,
                                                           compaction_strategy=compaction_strategy))

        self.db_cluster.wait_total_space_used_per_node()
        self.db_cluster.start_nemesis(interval=self.params.get('nemesis_interval'))

        for stress in stress_queue:
            self.verify_stress_thread(queue=stress, keyspace_num=3)

    def _create_counter_table(self):
        """
        workaround for the issue https://github.com/scylladb/scylla-tools-java/issues/32
        remove when resolved
        """
        node = self.db_cluster.nodes[0]
        session = self.cql_connection_patient(node)
        session.execute("""
            CREATE KEYSPACE IF NOT EXISTS keyspace1
            WITH replication = {'class': 'SimpleStrategy', 'replication_factor': '2'} AND durable_writes = true;
        """)
        session.execute("""
            CREATE TABLE IF NOT EXISTS keyspace1.counter1 (
                key blob PRIMARY KEY,
                "C0" counter,
                "C1" counter,
                "C2" counter,
                "C3" counter,
                "C4" counter
            ) WITH COMPACT STORAGE
                AND bloom_filter_fp_chance = 0.01
                AND caching = '{"keys":"ALL","rows_per_partition":"ALL"}'
                AND comment = ''
                AND compaction = {'class': 'SizeTieredCompactionStrategy'}
                AND compression = {}
                AND dclocal_read_repair_chance = 0.1
                AND default_time_to_live = 0
                AND gc_grace_seconds = 864000
                AND max_index_interval = 2048
                AND memtable_flush_period_in_ms = 0
                AND min_index_interval = 128
                AND read_repair_chance = 0.0
                AND speculative_retry = '99.0PERCENTILE';
        """)


if __name__ == '__main__':
    main()
