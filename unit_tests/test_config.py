from __future__ import absolute_import
import os
import logging
import itertools
import unittest

from sdcm.sct_config import SCTConfiguration

RPM_URL = 'https://s3.amazonaws.com/downloads.scylladb.com/enterprise/rpm/unstable/centos/' \
          '9f724fedb93b4734fcfaec1156806921ff46e956-2bdfa9f7ef592edaf15e028faf3b7f695f39ebc1' \
          '-525a0255f73d454f8f97f32b8bdd71c8dec35d3d-a6b2b2355c666b1893f702a587287da978aeec22/71/scylla.repo'


class ConfigurationTests(unittest.TestCase):  # pylint: disable=too-many-public-methods
    @classmethod
    def setUpClass(cls):
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger('botocore').setLevel(logging.CRITICAL)
        logging.getLogger('boto3').setLevel(logging.CRITICAL)
        logging.getLogger('anyconfig').setLevel(logging.ERROR)

        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/minimal_test_case.yaml'

        cls.conf = SCTConfiguration()

        for k, _ in os.environ.items():
            if k.startswith('SCT_'):
                del os.environ[k]

        # some of the tests assume this basic case is define, to avoid putting this again and again in each test
        # and so we can run those tests specificly
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/minimal_test_case.yaml'

    def tearDown(self):
        for k, _ in os.environ.items():
            if k.startswith('SCT_'):
                del os.environ[k]
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/minimal_test_case.yaml'

    def test_01_dump_config(self):
        logging.debug(self.conf.dump_config())

    def test_02_verify_config(self):
        self.conf.verify_configuration()
        self.conf.check_required_files()

    def test_03_dump_help_config_yaml(self):
        logging.debug(self.conf.dump_help_config_yaml())

    def test_03_dump_help_config_markdown(self):  # pylint: disable=invalid-name
        logging.debug(self.conf.dump_help_config_markdown())

    def test_04_check_env_parse(self):
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_REGION_NAME'] = '["eu-west-1", "us-east-1"]'
        os.environ['SCT_N_DB_NODES'] = '2 2'
        os.environ['SCT_INSTANCE_TYPE_DB'] = 'i3.large'
        os.environ['SCT_AMI_ID_DB_SCYLLA'] = 'ami-06f919eb ami-eae4f795'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/minimal_test_case.yaml'

        conf = SCTConfiguration()
        conf.verify_configuration()
        conf.dump_config()

        self.assertEqual(conf.get('ami_id_db_scylla'), 'ami-06f919eb ami-eae4f795')

    def test_05_docker(self):
        os.environ['SCT_CLUSTER_BACKEND'] = 'docker'
        os.environ['SCT_SCYLLA_VERSION'] = '3.0.3'

        conf = SCTConfiguration()
        conf.verify_configuration()
        self.assertIn('docker_image', conf.dump_config())
        self.assertEqual(conf.get('docker_image'), 'scylladb/scylla')

    @staticmethod
    def test_06a_docker_latest_no_loader():
        os.environ['SCT_CLUSTER_BACKEND'] = 'docker'
        os.environ['SCT_SCYLLA_VERSION'] = 'latest'
        os.environ['SCT_N_LOADERS'] = "0"

        conf = SCTConfiguration()
        conf.verify_configuration()

    @staticmethod
    def test_06b_docker_development():
        os.environ['SCT_CLUSTER_BACKEND'] = 'docker'
        os.environ['SCT_SCYLLA_VERSION'] = '666.development-blah'
        os.environ['SCT_SCYLLA_REPO_LOADER'] = RPM_URL

        conf = SCTConfiguration()
        conf.verify_configuration()

    def test_07_baremetal_exception(self):
        os.environ['SCT_CLUSTER_BACKEND'] = 'baremetal'
        conf = SCTConfiguration()
        self.assertRaises(AssertionError, conf.verify_configuration)

    def test_08_baremetal(self):
        os.environ['SCT_CLUSTER_BACKEND'] = 'baremetal'
        os.environ['SCT_DB_NODES_PRIVATE_IP'] = '["1.2.3.4", "1.2.3.5"]'
        os.environ['SCT_DB_NODES_PUBLIC_IP'] = '["1.2.3.4", "1.2.3.5"]'
        conf = SCTConfiguration()
        conf.verify_configuration()

        self.assertIn('db_nodes_private_ip', conf.dump_config())
        self.assertEqual(conf.get('db_nodes_private_ip'), ["1.2.3.4", "1.2.3.5"])

    def test_09_unknown_configure(self):
        os.environ['SCT_CLUSTER_BACKEND'] = 'docker'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/unknown_param_in_config.yaml'
        conf = SCTConfiguration()
        self.assertRaises(ValueError, conf.verify_configuration)

    def test_09_unknown_env(self):
        os.environ['SCT_CLUSTER_BACKEND'] = 'docker'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/unknown_param_in_config.yaml'
        os.environ['SCT_WHAT_IS_THAT'] = 'just_made_this_up'
        os.environ['SCT_WHAT_IS_THAT_2'] = 'what is this ?'
        conf = SCTConfiguration()
        with self.assertRaises(ValueError) as context:
            conf.verify_configuration()

        self.assertIn('SCT_WHAT_IS_THAT_2=what is this ?', str(context.exception))
        self.assertIn('SCT_WHAT_IS_THAT=just_made_this_up', str(context.exception))

    def test_10_longevity(self):
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/complex_test_case_with_version.yaml'
        os.environ['SCT_AMI_ID_DB_SCYLLA_DESC'] = 'master'
        conf = SCTConfiguration()
        conf.verify_configuration()
        self.assertEqual(conf.get('user_prefix'), 'longevity-50gb-4d-not-jenkins-maste')

    @staticmethod
    def test_10_mananger_regression():
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_AMI_ID_DB_SCYLLA'] = 'ami-06f919eb ami-eae4f795'

        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/multi_region_dc_test_case.yaml'
        conf = SCTConfiguration()
        conf.verify_configuration()

    def test_12_scylla_version_ami(self):
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_SCYLLA_VERSION'] = '3.0.3'

        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/multi_region_dc_test_case.yaml'
        conf = SCTConfiguration()
        conf.verify_configuration()

        self.assertEqual(conf.get('ami_id_db_scylla'), 'ami-0f1aa8afb878fed2b ami-027c1337dcb46da50')

    @staticmethod
    def test_12_scylla_version_ami_case1():  # pylint: disable=invalid-name
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_SCYLLA_VERSION'] = '3.0.3'
        os.environ['SCT_AMI_ID_DB_SCYLLA'] = 'ami-06f919eb ami-eae4f795'

        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/multi_region_dc_test_case.yaml'
        conf = SCTConfiguration()
        conf.verify_configuration()

    def test_12_scylla_version_ami_case2(self):  # pylint: disable=invalid-name
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_SCYLLA_VERSION'] = '99.0.3'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/multi_region_dc_test_case.yaml'
        self.assertRaisesRegex(ValueError, r"AMI for scylla version 99.0.3 wasn't found", SCTConfiguration)

    @staticmethod
    def test_12_scylla_version_repo():
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_SCYLLA_VERSION'] = '3.0.3'

        conf = SCTConfiguration()
        conf.verify_configuration()

    @staticmethod
    def test_12_scylla_version_repo_case1():  # pylint: disable=invalid-name
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_SCYLLA_VERSION'] = '3.0.3'
        os.environ['SCT_AMI_ID_DB_SCYLLA'] = 'ami-06f919eb'

        conf = SCTConfiguration()
        conf.verify_configuration()

    def test_12_scylla_version_repo_case2(self):  # pylint: disable=invalid-name
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_SCYLLA_VERSION'] = '99.0.3'

        self.assertRaisesRegex(ValueError, r"repo for scylla version 99.0.3 wasn't found", SCTConfiguration)

    def test_12_scylla_version_repo_ubuntu(self):  # pylint: disable=invalid-name
        os.environ['SCT_CLUSTER_BACKEND'] = 'gce'
        os.environ['SCT_SCYLLA_LINUX_DISTRO'] = 'ubuntu-xenial'
        os.environ['SCT_SCYLLA_LINUX_DISTRO_LOADER'] = 'ubuntu-xenial'
        os.environ['SCT_SCYLLA_VERSION'] = '3.0.3'
        conf = SCTConfiguration()
        conf.verify_configuration()

        self.assertIn('scylla_repo', conf.dump_config())
        self.assertEqual(conf.get('scylla_repo'),
                         "https://s3.amazonaws.com/downloads.scylladb.com/deb/ubuntu/scylla-3.0-xenial.list")
        self.assertEqual(conf.get('scylla_repo_loader'),
                         "https://s3.amazonaws.com/downloads.scylladb.com/deb/ubuntu/scylla-3.0-xenial.list")

    def test_12_scylla_version_repo_ubuntu_loader_centos(self):  # pylint: disable=invalid-name
        os.environ['SCT_CLUSTER_BACKEND'] = 'gce'
        os.environ['SCT_SCYLLA_LINUX_DISTRO'] = 'ubuntu-xenial'
        os.environ['SCT_SCYLLA_LINUX_DISTRO_LOADER'] = 'centos'
        os.environ['SCT_SCYLLA_VERSION'] = '3.0.3'
        conf = SCTConfiguration()
        conf.verify_configuration()

        self.assertIn('scylla_repo', conf.dump_config())
        self.assertEqual(conf.get('scylla_repo'),
                         "https://s3.amazonaws.com/downloads.scylladb.com/deb/ubuntu/scylla-3.0-xenial.list")
        self.assertEqual(conf.get('scylla_repo_loader'),
                         "https://s3.amazonaws.com/downloads.scylladb.com/rpm/centos/scylla-3.0.repo")

    def test_12_k8s_scylla_version_ubuntu_loader_centos(self):  # pylint: disable=invalid-name
        os.environ['SCT_CLUSTER_BACKEND'] = 'k8s-gce-minikube'
        os.environ['SCT_SCYLLA_LINUX_DISTRO'] = 'ubuntu-xenial'
        os.environ['SCT_SCYLLA_LINUX_DISTRO_LOADER'] = 'centos'
        os.environ['SCT_SCYLLA_VERSION'] = 'latest'
        conf = SCTConfiguration()
        conf.verify_configuration()

        self.assertIn('scylla_repo', conf.dump_config())
        self.assertEqual(conf.get('scylla_repo'),
                         None)
        self.assertEqual(conf.get('scylla_repo_loader'),
                         'https://s3.amazonaws.com/downloads.scylladb.com/rpm/centos/scylla-nightly.repo')

    def test_13_scylla_version_ami_branch(self):  # pylint: disable=invalid-name
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_SCYLLA_VERSION'] = 'branch-4.2:100'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/multi_region_dc_test_case.yaml'
        conf = SCTConfiguration()
        conf.verify_configuration()

        self.assertEqual(conf.get('ami_id_db_scylla'), 'ami-07d3138defbd9a2cf ami-0f703fdc8e06723f0')

    def test_13_scylla_version_ami_branch_latest(self):  # pylint: disable=invalid-name
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_SCYLLA_VERSION'] = 'branch-4.0:latest'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/multi_region_dc_test_case.yaml'
        conf = SCTConfiguration()
        conf.verify_configuration()

        self.assertIsNotNone(conf.get('ami_id_db_scylla'))
        self.assertEqual(len(conf.get('ami_id_db_scylla').split(' ')), 2)

    def test_conf_check_required_files(self):  # pylint: disable=no-self-use
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/minimal_test_case.yaml'
        os.environ['SCT_STRESS_CMD'] = """cassandra-stress user profile=/tmp/cs_profile_background_reads_overload.yaml \
            ops'(insert=100)' no-warmup cl=ONE duration=10m -port jmx=6868 \
            -mode cql3 native -rate threads=3000 -errors ignore"""
        conf = SCTConfiguration()
        conf.verify_configuration()
        conf.check_required_files()

    def test_conf_check_required_files_negative(self):  # pylint: disable=no-self-use
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/stress_cmd_with_bad_profile.yaml'
        os.environ['SCT_STRESS_CMD'] = """cassandra-stress user profile=/tmp/1232123123123123123.yaml ops'(insert=100)'\
            no-warmup cl=ONE duration=10m -port jmx=6868 -mode cql3 native -rate threads=3000 -errors ignore"""
        conf = SCTConfiguration()
        conf.verify_configuration()
        try:
            conf.check_required_files()
        except ValueError as exc:
            self.assertEqual(str(
                exc), "Stress command parameter \'stress_cmd\' contains profile \'/tmp/1232123123123123123.yaml\' that"
                      " does not exists under data_dir/")

    def test_config_dupes(self):
        def get_dupes(c):
            '''sort/tee/izip'''

            # pylint: disable=invalid-name
            a, b = itertools.tee(sorted(c))
            next(b, None)
            r = None
            for k, g in zip(a, b):
                if k != g:
                    continue
                if k != r:
                    yield k
                    r = k

        opts = [o['name'] for o in SCTConfiguration.config_options]

        self.assertListEqual(list(get_dupes(opts)), [])

    def test_13_bool(self):
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_STORE_RESULTS_IN_ELASTICSEARCH'] = 'False'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/multi_region_dc_test_case.yaml'
        conf = SCTConfiguration()

        self.assertEqual(conf['store_results_in_elasticsearch'], False)

    def test_14_aws_siren_from_env(self):
        os.environ['SCT_CLUSTER_BACKEND'] = 'aws-siren'
        os.environ['SCT_REGION_NAME'] = 'us-east-1'
        os.environ['SCT_N_DB_NODES'] = '2'
        os.environ['SCT_INSTANCE_TYPE_DB'] = 'i3.large'
        os.environ['SCT_AMI_ID_DB_SCYLLA'] = 'ami-eae4f795'
        os.environ['SCT_AUTHENTICATOR_USER'] = "user"
        os.environ['SCT_AUTHENTICATOR_PASSWORD'] = "pass"
        os.environ['SCT_CLOUD_CLUSTER_ID'] = "193712947904378"
        os.environ['SCT_SECURITY_GROUP_IDS'] = "sg-89fi3rkl"
        os.environ['SCT_SUBNET_ID'] = "sub-d32f09sdf"

        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/multi_region_dc_test_case.yaml'

        conf = SCTConfiguration()
        conf.verify_configuration()
        self.assertEqual(conf.get('cloud_cluster_id'), 193712947904378)
        assert conf["authenticator_user"] == "user"
        assert conf["authenticator_password"] == "pass"
        assert conf["security_group_ids"] == ["sg-89fi3rkl"]
        assert conf["subnet_id"] == ["sub-d32f09sdf"]

    def test_15_new_scylla_repo(self):
        centos_repo = 'https://s3.amazonaws.com/downloads.scylladb.com/enterprise/rpm/unstable/centos/' \
                      '9f724fedb93b4734fcfaec1156806921ff46e956-2bdfa9f7ef592edaf15e028faf3b7f695f39ebc1' \
                      '-525a0255f73d454f8f97f32b8bdd71c8dec35d3d-a6b2b2355c666b1893f702a587287da978aeec22/71/scylla' \
                      '.repo'

        os.environ['SCT_CLUSTER_BACKEND'] = 'gce'
        os.environ['SCT_SCYLLA_REPO'] = centos_repo
        os.environ['SCT_NEW_SCYLLA_REPO'] = centos_repo
        os.environ['SCT_USER_PREFIX'] = 'testing'

        conf = SCTConfiguration()
        conf.verify_configuration()
        self.assertEqual(conf.get('target_upgrade_version'), '2019.1.1')

    def test_15a_new_scylla_repo_by_scylla_version(self):
        os.environ['SCT_CLUSTER_BACKEND'] = 'gce'
        os.environ['SCT_SCYLLA_VERSION'] = 'branch-4.2:latest'
        os.environ['SCT_NEW_VERSION'] = 'master:latest'
        os.environ['SCT_USER_PREFIX'] = 'testing'

        conf = SCTConfiguration()
        conf.verify_configuration()
        self.assertEqual(conf.get('scylla_repo'),
                         "https://s3.amazonaws.com/downloads.scylladb.com/rpm/unstable/centos/branch-4.2/latest/scylla.repo")
        target_upgrade_version = conf.get('target_upgrade_version')
        self.assertTrue(target_upgrade_version == '666.development' or target_upgrade_version.endswith(".dev"))

    def test_15b_new_scylla_repo_by_scylla_version_ubuntu(self):
        os.environ['SCT_CLUSTER_BACKEND'] = 'gce'
        os.environ['SCT_SCYLLA_VERSION'] = 'master:latest'
        os.environ['SCT_NEW_VERSION'] = 'master:latest'
        os.environ['SCT_USER_PREFIX'] = 'testing'
        os.environ['SCT_SCYLLA_LINUX_DISTRO'] = 'ubuntu-xenial'
        os.environ['SCT_SCYLLA_LINUX_DISTRO_LOADER'] = 'ubuntu-xenial'

        conf = SCTConfiguration()
        conf.verify_configuration()
        self.assertEqual(conf.get('scylla_repo'),
                         "https://s3.amazonaws.com/downloads.scylladb.com/deb/unstable/unified/master/latest/scylladb-master/scylla.list")
        target_upgrade_version = conf.get('target_upgrade_version')
        self.assertTrue(target_upgrade_version == '666.development' or target_upgrade_version.endswith(".dev"))

    def test_16_oracle_scylla_version_us_east_1(self):
        ami_3_0_11 = "ami-0a49c99b529429c18"

        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_ORACLE_SCYLLA_VERSION'] = "3.0.11"
        os.environ['SCT_REGION_NAME'] = 'us-east-1'
        os.environ['SCT_AMI_ID_DB_SCYLLA'] = 'ami-eae4f795'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/minimal_test_case.yaml'

        conf = SCTConfiguration()
        conf.verify_configuration()

        self.assertEqual(conf.get('ami_id_db_oracle'), ami_3_0_11)

    def test_16_oracle_scylla_version_eu_west_1(self):
        ami_3_0_11 = "ami-0535c88b85b914499"

        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_ORACLE_SCYLLA_VERSION'] = "3.0.11"
        os.environ['SCT_REGION_NAME'] = 'eu-west-1'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/minimal_test_case.yaml'

        conf = SCTConfiguration()
        conf.verify_configuration()

        self.assertEqual(conf.get('ami_id_db_oracle'), ami_3_0_11)

    def test_16_oracle_scylla_version_wrong_region(self):
        ami_3_0_11_eu_west_1 = "ami-0535c88b85b914499"

        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_ORACLE_SCYLLA_VERSION'] = "3.0.11"
        os.environ['SCT_REGION_NAME'] = 'us-east-1'
        os.environ['SCT_AMI_ID_DB_SCYLLA'] = 'ami-eae4f795'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/minimal_test_case.yaml'

        conf = SCTConfiguration()
        conf.verify_configuration()

        self.assertNotEqual(conf.get('ami_id_db_oracle'), ami_3_0_11_eu_west_1)

    def test_16_oracle_scylla_version_and_oracle_ami_together(self):

        os.environ['SCT_CLUSTER_BACKEND'] = 'aws'
        os.environ['SCT_REGION_NAME'] = 'eu-west-1'
        os.environ['SCT_ORACLE_SCYLLA_VERSION'] = '3.0.11'
        os.environ['SCT_AMI_ID_DB_ORACLE'] = 'ami-0535c88b85b914499'
        os.environ['SCT_CONFIG_FILES'] = 'internal_test_data/minimal_test_case.yaml'

        with self.assertRaises(ValueError) as context:
            SCTConfiguration()

        self.assertIn("oracle_scylla_version and ami_id_db_oracle can't used together", str(context.exception))


if __name__ == "__main__":
    unittest.main()
