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

import logging

from avocado import main

from sdcm.tester import ClusterTester
from sdcm.tester import clean_aws_resources
from sdcm.nemesis import Nemesis
from sdcm.nemesis import log_time_elapsed
import time


class DecommissionNoAddMonkey(Nemesis):

    @log_time_elapsed
    def disrupt(self):
        self.disrupt_nodetool_decommission(add_node=False)


class ReduceClusterTest(ClusterTester):
    """
    Test scylla cluster reduction (removing nodes to shrink cluster from initial cluster size to target cluster size).

    :avocado: enable
    """

    @clean_aws_resources
    def setUp(self):
        self.credentials = None
        self.db_cluster = None
        self.loaders = None
        logging.getLogger('botocore').setLevel(logging.CRITICAL)
        logging.getLogger('boto3').setLevel(logging.CRITICAL)
        self.stress_thread = None

    def wait_for_init(self, cluster_starting_size, cluster_target_size):
        # We're starting the cluster with more than 3 nodes due to
        # replication factor settings we're using with cassandra-stress
        self._cluster_starting_size = cluster_starting_size
        self._cluster_target_size = cluster_target_size
        loader_info = {'n_nodes': 1, 'device_mappings': None,
                       'type': None}
        db_info = {'n_nodes': self._cluster_starting_size,
                   'device_mappings': None, 'type': None}
        self.init_resources(loader_info=loader_info, db_info=db_info)
        self.loaders.wait_for_init()
        self.db_cluster.wait_for_init()

    def get_stress_cmd(self, duration=None, threads=None, population_size=None):
        """
        Get a cassandra stress cmd string suitable for reduce cluster purposes.

        :param duration: Duration of stress (minutes).
        :param threads: Number of threads used by cassandra stress.
        :param population_size: Size of the -pop seq1..%s argument.
        :return: Cassandra stress string
        :rtype: basestring
        """
        ip = self.db_cluster.get_node_private_ips()[0]
        if population_size is None:
            population_size = 1000000
        if duration is None:
            duration = self.params.get('cassandra_stress_duration')
        if threads is None:
            threads = self.params.get('cassandra_stress_threads')
        return ("cassandra-stress write cl=QUORUM duration=%sm "
                "-schema 'replication(factor=3)' -port jmx=6868 "
                "-mode cql3 native -rate threads=%s "
                "-pop seq=1..%s -node %s" %
                (duration, threads, population_size, ip))

    def reduce_cluster(self, cluster_starting_size, cluster_target_size=3):
        self.wait_for_init(cluster_starting_size, cluster_target_size)

        nodes_to_remove = self._cluster_starting_size - self._cluster_target_size
        # 60 minutes should be long enough for each node to do decommission
        duration = 60 * nodes_to_remove
        stress_queue = self.run_stress_thread(duration=duration)

        # Wait for cluster is filled with data
        # Set space_node_threshold in config file for the size
        self.db_cluster.wait_total_space_used_per_node()

        self.db_cluster.add_nemesis(DecommissionNoAddMonkey)
        # Have c-s run for 2 + 3 minutes before we start to do decommission
        time.sleep(2 * 60)
        while len(self.db_cluster.nodes) > cluster_target_size:
            # Sleep 3 minutes before decommission
            time.sleep(3 * 60)
            # Run DecommissionNoAddMonkey once to decommission one node a time
            self.db_cluster.start_nemesis(interval=10)
            self.db_cluster.stop_nemesis(timeout=None)

        # Run 2 more minutes before stop c-s
        time.sleep(2 * 60)

        # Kill c-s when decommission is done
        self.kill_stress_thread()

        self.verify_stress_thread(queue=stress_queue)

    def test_reduce_4_to_3(self):
        """
        Reduce cluster from 4 to 3

        1) Start a 4 node cluster
        2) Start cassandra-stress on the loader node
        3) Decommission a node
        4) Keep repeating 3) until we get to the target number of 3 nodes
        """
        self.reduce_cluster(cluster_starting_size=4, cluster_target_size=3)

    def test_reduce_5_to_3(self):
        """
        Reduce cluster from 5 to 3

        1) Start a 5 node cluster
        2) Start cassandra-stress on the loader node
        3) Decommission a node
        4) Keep repeating 3) until we get to the target number of 3 nodes
        """
        self.reduce_cluster(cluster_starting_size=5, cluster_target_size=3)

    def test_reduce_10_to_3(self):
        """
        Reduce cluster from 10 to 3

        1) Start a 10 node cluster
        2) Start cassandra-stress on the loader node
        3) Decommission a node
        4) Keep repeating 3) until we get to the target number of 3 nodes
        """
        self.reduce_cluster(cluster_starting_size=10, cluster_target_size=3)

    def test_reduce_30_to_3(self):
        """
        Reduce cluster from 10 to 3

        1) Start a 10 node cluster
        2) Start cassandra-stress on the loader node
        3) Decommission a  node
        4) Keep repeating 3) until we get to the target number of 3 nodes
        """
        self.reduce_cluster(cluster_starting_size=30, cluster_target_size=3)


if __name__ == '__main__':
    main()
