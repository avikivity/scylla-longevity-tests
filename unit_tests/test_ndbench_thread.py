import time

import pytest

from sdcm.ndbench_thread import NdBenchStressThread
from unit_tests.dummy_remote import LocalLoaderSetDummy

pytestmark = [pytest.mark.usefixtures('events'), pytest.mark.skip(reason="those are integration tests only")]


def test_01_cql_api(request, docker_scylla):
    loader_set = LocalLoaderSetDummy()
    cmd = 'ndbench cli.clientName=CassJavaDriverGeneric ; numKeys=20000000 ; numReaders=8; numWriters=8 ; cass.writeConsistencyLevel=QUORUM ; cass.readConsistencyLevel=QUORUM ; readRateLimit=7200 ; writeRateLimit=1800'
    ndbench_thread = NdBenchStressThread(loader_set, cmd, node_list=[docker_scylla], timeout=5)

    def cleanup_thread():
        ndbench_thread.kill()
    request.addfinalizer(cleanup_thread)
    ndbench_thread.run()
    ndbench_thread.get_results()


def test_02_cql_kill(request, docker_scylla):
    """
    verifies that kill command on the NdBenchStressThread is working
    """
    loader_set = LocalLoaderSetDummy()
    cmd = 'ndbench cli.clientName=CassJavaDriverGeneric ; numKeys=20000000 ; numReaders=8; numWriters=8 ; cass.writeConsistencyLevel=QUORUM ; cass.readConsistencyLevel=QUORUM ; readRateLimit=7200 ; writeRateLimit=1800'
    ndbench_thread = NdBenchStressThread(loader_set, cmd, node_list=[docker_scylla], timeout=500)

    def cleanup_thread():
        ndbench_thread.kill()
    request.addfinalizer(cleanup_thread)
    ndbench_thread.run()
    time.sleep(3)
    ndbench_thread.kill()
    ndbench_thread.get_results()


def test_03_dynamodb_api(request, docker_scylla, events):
    """
    this test isn't working yet, since we didn't figured out a way to use ndbench with dynamodb
    """
    critical_log_content_before = events.get_event_log_file('critical.log')

    # start a command that would yield errors
    loader_set = LocalLoaderSetDummy()
    cmd = f'ndbench cli.clientName=DynamoDBKeyValue ; numKeys=20000000 ; numReaders=8; numWriters=8 ; readRateLimit=7200 ; writeRateLimit=1800; dynamodb.autoscaling=false; dynamodb.endpoint=http://{docker_scylla.internal_ip_address}:8000'
    ndbench_thread = NdBenchStressThread(loader_set, cmd, node_list=[docker_scylla], timeout=20)

    def cleanup_thread():
        ndbench_thread.kill()
    request.addfinalizer(cleanup_thread)

    ndbench_thread.run()
    ndbench_thread.get_results()

    # check that events with the errors were sent out
    critical_log_content_after = events.wait_for_event_log_change('critical.log', critical_log_content_before)

    assert 'Encountered an exception when driving load' in critical_log_content_after
    assert 'BUILD FAILED' in critical_log_content_after


def test_04_verify_data(request, docker_scylla, events):
    loader_set = LocalLoaderSetDummy()
    cmd = 'ndbench cli.clientName=CassJavaDriverGeneric ; numKeys=30 ; readEnabled=false; numReaders=0; numWriters=1 ; cass.writeConsistencyLevel=QUORUM ; cass.readConsistencyLevel=QUORUM ; generateChecksum=false'
    ndbench_thread = NdBenchStressThread(loader_set, cmd, node_list=[docker_scylla], timeout=30)

    def cleanup_thread():
        ndbench_thread.kill()
    request.addfinalizer(cleanup_thread)

    ndbench_thread.run()
    ndbench_thread.get_results()

    cmd = 'ndbench cli.clientName=CassJavaDriverGeneric ; numKeys=30 ; writeEnabled=false; numReaders=1; numWriters=0 ; cass.writeConsistencyLevel=QUORUM ; cass.readConsistencyLevel=QUORUM ; validateChecksum=true ;'
    ndbench_thread2 = NdBenchStressThread(loader_set, cmd, node_list=[docker_scylla], timeout=30)

    def cleanup_thread2():
        ndbench_thread2.kill()

    request.addfinalizer(cleanup_thread2)

    critical_log_content_before = events.get_event_log_file('critical.log')
    ndbench_thread2.run()

    time.sleep(15)
    critical_log_content_after = events.wait_for_event_log_change('critical.log', critical_log_content_before)
    assert 'Failed to process NdBench read operation' in critical_log_content_after
