import re

import pytest
import requests

import sdcm.utils.alternator as alternator
from sdcm.utils.decorators import timeout
from sdcm.utils.docker_utils import running_in_docker
from sdcm.ycsb_thread import YcsbStressThread
from unit_tests.dummy_remote import LocalLoaderSetDummy

pytestmark = [pytest.mark.usefixtures('events', 'create_table', 'create_cql_ks_and_table'),
              pytest.mark.skip(reason="those are integration tests only")]

ALTERNATOR_PORT = 8000
TEST_PARAMS = dict(dynamodb_primarykey_type='HASH_AND_RANGE',
                   alternator_use_dns_routing=True, alternator_port=ALTERNATOR_PORT)
ALTERNATOR = alternator.api.Alternator()


@pytest.fixture(scope='session')
def create_table(docker_scylla):
    if running_in_docker():
        ALTERNATOR.endpoint_url = f'http://{docker_scylla.internal_ip_address}:{ALTERNATOR_PORT}'
    else:
        address = docker_scylla.get_port(f'{ALTERNATOR_PORT}')
        ALTERNATOR.endpoint_url = f'http://{address}'
    ALTERNATOR.create_table(table_name=alternator.consts.TABLE_NAME)


@pytest.fixture(scope='session')
def create_cql_ks_and_table(docker_scylla):
    if running_in_docker():
        address = f'{docker_scylla.internal_ip_address}:9042'
    else:
        address = docker_scylla.get_port('9042')
    node_ip, port = address.split(':')
    port = int(port)

    from cassandra.cluster import Cluster  # pylint: disable=no-name-in-module
    cluster_driver = Cluster([node_ip], port=port)
    session = cluster_driver.connect()
    session.execute(
        """create keyspace ycsb WITH REPLICATION = {'class' : 'SimpleStrategy', 'replication_factor': 1 };""")
    session.execute("""CREATE TABLE ycsb.usertable (
                        y_id varchar primary key,
                        field0 varchar,
                        field1 varchar,
                        field2 varchar,
                        field3 varchar,
                        field4 varchar,
                        field5 varchar,
                        field6 varchar,
                        field7 varchar,
                        field8 varchar,
                        field9 varchar);""")


def test_01_dynamodb_api(request, docker_scylla, prom_address):
    loader_set = LocalLoaderSetDummy()

    cmd = 'bin/ycsb run dynamodb -P workloads/workloada -threads 5 -p recordcount=1000000 -p fieldcount=10 -p fieldlength=1024 -p operationcount=200200300 -s'
    ycsb_thread = YcsbStressThread(loader_set, cmd, node_list=[docker_scylla], timeout=5, params=TEST_PARAMS)

    def cleanup_thread():
        ycsb_thread.kill()

    request.addfinalizer(cleanup_thread)

    ycsb_thread.run()

    @timeout(timeout=60)
    def check_metrics():
        output = requests.get("http://{}/metrics".format(prom_address)).text
        regex = re.compile(r'^collectd_ycsb_read_gauge.*?([0-9\.]*?)$', re.MULTILINE)
        assert 'collectd_ycsb_read_gauge' in output
        assert 'collectd_ycsb_update_gauge' in output

        matches = regex.findall(output)
        assert all(float(i) > 0 for i in matches), output

    check_metrics()

    output = ycsb_thread.get_results()
    assert 'latency mean' in output[0]
    assert float(output[0]['latency mean']) > 0

    assert 'latency 99th percentile' in output[0]
    assert float(output[0]['latency 99th percentile']) > 0


def test_02_dynamodb_api_dataintegrity(request, docker_scylla, prom_address, events):
    loader_set = LocalLoaderSetDummy()

    error_log_content_before = events.get_event_log_file('error.log')

    # 2. do write without dataintegrity=true
    cmd = 'bin/ycsb load dynamodb -P workloads/workloada -threads 5 -p recordcount=10000 -p fieldcount=10 -p fieldlength=512'
    ycsb_thread1 = YcsbStressThread(loader_set, cmd, node_list=[docker_scylla], timeout=5, params=TEST_PARAMS)

    def cleanup_thread1():
        ycsb_thread1.kill()

    request.addfinalizer(cleanup_thread1)

    ycsb_thread1.run()
    ycsb_thread1.get_results()
    ycsb_thread1.kill()

    # 3. do read with dataintegrity=true
    cmd = 'bin/ycsb run dynamodb -P workloads/workloada -threads 5 -p recordcount=10000 -p fieldcount=10 -p fieldlength=512 -p dataintegrity=true -p operationcount=100000000'
    ycsb_thread2 = YcsbStressThread(loader_set, cmd, node_list=[docker_scylla], timeout=20, params=TEST_PARAMS)

    def cleanup_thread2():
        ycsb_thread2.kill()

    request.addfinalizer(cleanup_thread2)

    ycsb_thread2.run()

    # 4. wait for expected metrics to be available
    @timeout(timeout=60)
    def check_metrics():
        output = requests.get("http://{}/metrics".format(prom_address)).text
        regex = re.compile(r'^collectd_ycsb_verify_gauge.*?([0-9\.]*?)$', re.MULTILINE)

        assert 'collectd_ycsb_verify_gauge' in output
        assert 'UNEXPECTED_STATE' in output
        matches = regex.findall(output)
        assert all(float(i) >= 0 for i in matches), output

    check_metrics()
    ycsb_thread2.get_results()

    # 5. check that events with the expected error were raised
    error_log_content_after = events.wait_for_event_log_change('error.log', error_log_content_before)
    assert 'UNEXPECTED_STATE' in error_log_content_after


def test_03_cql(request, docker_scylla, prom_address):
    loader_set = LocalLoaderSetDummy()

    cmd = 'bin/ycsb load cassandra-cql -P workloads/workloada -threads 5 -p recordcount=1000000 -p fieldcount=10 -p fieldlength=1024 -p operationcount=200200300 -s'
    ycsb_thread = YcsbStressThread(loader_set, cmd, node_list=[docker_scylla], timeout=5, params=TEST_PARAMS)

    def cleanup_thread():
        ycsb_thread.kill()

    request.addfinalizer(cleanup_thread)

    ycsb_thread.run()

    @timeout(timeout=60)
    def check_metrics():
        output = requests.get("http://{}/metrics".format(prom_address)).text
        regex = re.compile(r'^collectd_ycsb_read_gauge.*?([0-9\.]*?)$', re.MULTILINE)
        assert 'collectd_ycsb_read_gauge' in output
        assert 'collectd_ycsb_update_gauge' in output

        matches = regex.findall(output)
        assert all(float(i) > 0 for i in matches), output

    check_metrics()
    ycsb_thread.get_results()


def test_04_insert_new_data():
    schema = alternator.schemas.HASH_AND_STR_RANGE_SCHEMA
    schema_keys = [key_details["AttributeName"] for key_details in schema["KeySchema"]]
    new_items = [{schema_keys[0]: 'test_0', schema_keys[1]: 'NFinQpNuCnaNOxsAkyrZ'},
                 {schema_keys[0]: 'test_1', schema_keys[1]: 'hScfTVnCctqqTQcLrIQd'},
                 {schema_keys[0]: 'test_2', schema_keys[1]: 'OpvrbHJNNMHptWYQSWvm'},
                 {schema_keys[0]: 'test_3', schema_keys[1]: 'nzxHPebRwNaxLlXUbbCW'},
                 {schema_keys[0]: 'test_4', schema_keys[1]: 'WfHQIwRNHflFHYWwOcFA'},
                 {schema_keys[0]: 'test_5', schema_keys[1]: 'ipcTlIvLbcbrOFDynEBU'},
                 {schema_keys[0]: 'test_6', schema_keys[1]: 'judYKbqgDAejlpPdqLdx'},
                 {schema_keys[0]: 'test_7', schema_keys[1]: 'mMYdekljccLeOMWLBTLL'},
                 {schema_keys[0]: 'test_8', schema_keys[1]: 'NqsNVTtJeWRzrjHmOwop'},
                 {schema_keys[0]: 'test_9', schema_keys[1]: 'YrRvsqXAtppgCLiHhiQn'}]

    ALTERNATOR.batch_write_actions(new_items=new_items, schema=alternator.schemas.HASH_AND_STR_RANGE_SCHEMA)
    diff = ALTERNATOR.compare_table_data(table_data=new_items)
    assert diff
