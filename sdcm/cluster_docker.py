import re
import json
import time
import logging
import os
import types

from sdcm import cluster
from sdcm.utils.common import retrying
from sdcm.remote import LocalCmdRunner
from sdcm.log import SDCMAdapter
from sdcm.utils.docker import get_docker_bridge_gateway

LOGGER = logging.getLogger(__name__)
LOCALRUNNER = LocalCmdRunner()
AIO_MAX_NR_RECOMMENDED_VALUE = 1048576


class DockerError(Exception):
    pass


class DockerCommandError(DockerError):
    pass


class DockerContainerNotExists(DockerError):
    pass


class DockerContainerNotRunning(DockerError):
    pass


class ScyllaDockerRequirementError(cluster.ScyllaRequirementError, DockerError):
    pass


class CannotFindContainers(DockerError):
    pass


def _docker(cmd, timeout=10):
    res = LOCALRUNNER.run('docker {}'.format(cmd), ignore_status=True, timeout=timeout)
    if res.exit_status:
        if 'No such container:' in res.stderr:
            raise DockerContainerNotExists(res.stderr)
        raise DockerCommandError('command: {}, error: {}, output: {}'.format(cmd, res.stderr, res.stdout))
    return res


class DockerNode(cluster.BaseNode):  # pylint: disable=abstract-method

    def __init__(self,  # pylint: disable=too-many-arguments
                 name,
                 parent_cluster,
                 base_logdir=None,
                 ssh_login_info=None,
                 node_prefix=None,
                 dc_idx=None):
        self._public_ip_address = None
        super(DockerNode, self).__init__(name=name,
                                         parent_cluster=parent_cluster,
                                         base_logdir=base_logdir,
                                         ssh_login_info=ssh_login_info,
                                         node_prefix=node_prefix,
                                         dc_idx=dc_idx)
        self.wait_for_status_running()
        self.wait_public_ip()

    def _get_public_ip_address(self):
        if not self._public_ip_address:
            out = _docker("inspect --format='{{{{ .NetworkSettings.IPAddress }}}}' {}".format(self.name)).stdout
            self._public_ip_address = out.strip()
        return self._public_ip_address

    def is_running(self):
        out = _docker("inspect --format='{{{{json .State.Running}}}}' {}".format(self.name)).stdout
        return json.loads(out)

    @retrying(n=20, sleep_time=2, allowed_exceptions=(DockerContainerNotRunning,))
    def wait_for_status_running(self):
        if not self.is_running():
            raise DockerContainerNotRunning(self.name)

    @property
    def public_ip_address(self):
        return self._get_public_ip_address()

    @property
    def private_ip_address(self):
        return self._get_public_ip_address()

    def wait_public_ip(self):
        while not self._public_ip_address:
            self._get_public_ip_address()
            time.sleep(1)

    def start(self, timeout=30):
        _docker('start {}'.format(self.name), timeout=timeout)

    def restart(self, timeout=30):  # pylint: disable=arguments-differ
        _docker('restart {}'.format(self.name), timeout=timeout)

    @retrying(n=5, sleep_time=1)
    def destroy(self, force=True):  # pylint: disable=arguments-differ
        force_param = '-f' if force else ''
        _docker('rm {} -v {}'.format(force_param, self.name))

    def start_scylla_server(self, verify_up=True, verify_down=False, timeout=300, verify_up_timeout=300):
        if verify_down:
            self.wait_db_down(timeout=timeout)
        self.remoter.run('supervisorctl start scylla', timeout=timeout)
        if verify_up:
            self.wait_db_up(timeout=verify_up_timeout)

    @cluster.log_run_info
    def start_scylla(self, verify_up=True, verify_down=False, timeout=300):
        self.start_scylla_server(verify_up=verify_up, verify_down=verify_down, timeout=timeout)

    def stop_scylla_server(self, verify_up=False, verify_down=True, timeout=300, ignore_status=False):
        if verify_up:
            self.wait_db_up(timeout=timeout)
        self.remoter.run('supervisorctl stop scylla', timeout=timeout)
        if verify_down:
            self.wait_db_down(timeout=timeout)

    @cluster.log_run_info
    def stop_scylla(self, verify_up=False, verify_down=True, timeout=300):
        self.stop_scylla_server(verify_up=verify_up, verify_down=verify_down, timeout=timeout)

    def restart_scylla_server(self, verify_up_before=False, verify_up_after=True, timeout=300, ignore_status=False):
        if verify_up_before:
            self.wait_db_up(timeout=timeout)
        self.remoter.run("supervisorctl restart scylla", timeout=timeout)
        if verify_up_after:
            self.wait_db_up(timeout=timeout)

    @cluster.log_run_info
    def restart_scylla(self, verify_up_before=False, verify_up_after=True, timeout=300):
        self.restart_scylla_server(verify_up_before=verify_up_before, verify_up_after=verify_up_after, timeout=timeout)

    @property
    def image(self) -> str:
        return self.parent_cluster.source_image


class DockerCluster(cluster.BaseCluster):  # pylint: disable=abstract-method

    def __init__(self, **kwargs):
        self._image = kwargs.get('docker_image', 'scylladb/scylla-nightly')
        self._version_tag = kwargs.get('docker_image_tag', 'latest')
        self.nodes = []
        self.credentials = kwargs.get('credentials')
        self._node_prefix = kwargs.get('node_prefix')
        self._node_img_tag = 'scylla-sct-img'
        self._context_path = os.path.join(os.path.dirname(__file__), '../docker/scylla-sct')
        self._create_node_image()
        super(DockerCluster, self).__init__(node_prefix=self._node_prefix,
                                            n_nodes=kwargs.get('n_nodes'),
                                            params=kwargs.get('params'),
                                            cluster_prefix=kwargs.get('cluster_prefix'),
                                            region_names=["localhost-dc"])  # no multi dc currently supported

    @property
    def source_image(self) -> str:
        return f"{self._image}:{self._version_tag}"

    def _create_node_image(self):
        self._update_image()
        private_key = self.credentials[0].key_file
        context_pub_key_path = os.path.join(self._context_path, 'scylla-test.pub')
        LOCALRUNNER.run(f"ssh-keygen -y -f {private_key} > {context_pub_key_path}; sed -ri "
                        f"'s/(ssh-rsa [^\\n]+)/\\1 test@localhost/g' {context_pub_key_path}")
        _docker(f'build --build-arg SOURCE_IMAGE={self.source_image} -t {self._node_img_tag} {self._context_path}',
                timeout=300)
        LOCALRUNNER.run(f'rm -f {context_pub_key_path}', ignore_status=True)

    @staticmethod
    def _clean_old_images():
        _docker('system prune --volumes -f')

    def _update_image(self):
        LOGGER.debug('update scylla image')
        _docker(f'pull {self._image}:{self._version_tag}', timeout=300)
        try:
            self._clean_old_images()
        except DockerCommandError as exc:
            LOGGER.info(f'Cleaning old images failed with {str(exc)}')

    def _create_container(self, node_name, is_seed=False, seed_ip=None):
        labels = f"--label 'test_id={cluster.Setup.test_id()}'"
        cmd = f'run --cpus="1" -h "{node_name}" --name "{node_name}" {labels} -d {self._node_img_tag}'
        if not is_seed and seed_ip:
            cmd = f'{cmd} --seeds="{seed_ip}"'
        _docker(cmd, timeout=30)
        # remove the message of the day
        _docker(f"""exec {node_name} bash -c "sed  '/\\/dev\\/stderr/d' /etc/bashrc -i" """)

    def _get_containers_by_prefix(self):
        c_ids = _docker('container ls -a -q --filter name={}'.format(self._node_prefix)).stdout
        if not c_ids:
            raise CannotFindContainers('name prefix: %s' % self._node_prefix)
        return [_ for _ in c_ids.split('\n') if _]

    @staticmethod
    def _get_connainer_name_by_id(c_id):
        return json.loads(_docker("inspect --format='{{{{json .Name}}}}' {}".format(c_id)).stdout).lstrip('/')

    def _create_node(self, node_name):
        return DockerNode(node_name,
                          parent_cluster=self,
                          ssh_login_info={'hostname': None,
                                          'user': 'scylla-test',
                                          'key_file': self.credentials[0].key_file},
                          base_logdir=self.logdir,
                          node_prefix=self.node_prefix)

    def _get_node_name_and_index(self):
        """Is important when node is added to replace some dead node"""
        node_names = [node.name for node in self.nodes]
        node_index = 0
        while True:
            node_name = '%s-%s' % (self.node_prefix, node_index)
            if node_name not in node_names:
                return node_name, node_index
            node_index += 1

    def _create_nodes(self, count, dc_idx=0, enable_auto_bootstrap=False):  # pylint: disable=unused-argument
        """
        Create nodes from docker containers
        :param count: count of nodes to create
        :param dc_idx: datacenter index
        :return: list of DockerNode objects
        """
        new_nodes = []
        for _ in range(count):
            node_name, node_index = self._get_node_name_and_index()
            is_seed = (node_index == 0)
            seed_ip = self.nodes[0].public_ip_address if not is_seed else None
            self._create_container(node_name, is_seed, seed_ip)
            new_node = self._create_node(node_name)
            new_node.enable_auto_bootstrap = enable_auto_bootstrap
            self.nodes.append(new_node)
            new_nodes.append(new_node)
        return new_nodes

    def _get_nodes(self):
        """
        Find the existing containers by node name prefix
        and create nodes from it.
        :return: list of DockerNode objects
        """
        c_ids = self._get_containers_by_prefix()
        for c_id in c_ids:
            node_name = self._get_connainer_name_by_id(c_id)
            LOGGER.debug('Node name: %s', node_name)
            new_node = self._create_node(node_name)
            if not new_node.is_running():
                new_node.start()
                new_node.wait_for_status_running()
            self.nodes.append(new_node)
        return self.nodes

    def add_nodes(self, count, ec2_user_data='', dc_idx=0, enable_auto_bootstrap=False):
        if cluster.Setup.REUSE_CLUSTER:
            return self._get_nodes()
        else:
            return self._create_nodes(count, dc_idx, enable_auto_bootstrap)

    def destroy(self):
        LOGGER.info('Destroy nodes')
        for node in self.nodes:
            node.destroy(force=True)


class ScyllaDockerCluster(cluster.BaseScyllaCluster, DockerCluster):  # pylint: disable=abstract-method

    def __init__(self, **kwargs):
        user_prefix = kwargs.get('user_prefix')
        cluster_prefix = cluster.prepend_user_prefix(user_prefix, 'db-cluster')
        node_prefix = cluster.prepend_user_prefix(user_prefix, 'db-node')

        super(ScyllaDockerCluster, self).__init__(node_prefix=node_prefix,
                                                  cluster_prefix=cluster_prefix,
                                                  **kwargs)

    def node_setup(self, node, verbose=False, timeout=3600):
        self.check_aio_max_nr(node)

        endpoint_snitch = self.params.get('endpoint_snitch')
        seed_address = ','.join(self.seed_nodes_ips)

        node.wait_ssh_up(verbose=verbose)
        if cluster.Setup.BACKTRACE_DECODING:
            node.install_scylla_debuginfo()

        self.node_config_setup(node, seed_address, endpoint_snitch)

        node.stop_scylla_server(verify_down=False)
        node.remoter.run('sudo rm -Rf /var/lib/scylla/data/*')  # Clear data folder to drop wrong cluster name data.
        node.start_scylla_server(verify_up=False)

        node.wait_db_up(verbose=verbose, timeout=timeout)
        node.check_nodes_status()
        self.clean_replacement_node_ip(node)

    @staticmethod
    def check_aio_max_nr(node: DockerNode, recommended_value: int = AIO_MAX_NR_RECOMMENDED_VALUE):
        """Verify that sysctl key `fs.aio-max-nr' set to recommended value.

        See https://github.com/scylladb/scylla/issues/5638 for details.
        """
        aio_max_nr = int(node.remoter.run("cat /proc/sys/fs/aio-max-nr").stdout)
        if aio_max_nr < recommended_value:
            raise ScyllaDockerRequirementError(
                f"{node}: value of sysctl key `fs.aio-max-nr' ({aio_max_nr}) "
                f"is less than recommended value ({recommended_value})")

    @cluster.wait_for_init_wrap
    def wait_for_init(self, node_list=None, verbose=False, timeout=None):   # pylint: disable=unused-argument,arguments-differ
        node_list = node_list if node_list else self.nodes
        for node in node_list:
            node.wait_for_status_running()
        self.wait_for_nodes_up_and_normal(nodes=node_list)

    def get_scylla_args(self):
        # pylint: disable=no-member
        append_scylla_args = self.params.get('append_scylla_args_oracle') if self.name.find('oracle') > 0 else \
            self.params.get('append_scylla_args')
        return re.sub(r'--blocked-reactor-notify-ms[ ]+[0-9]+', '', append_scylla_args)


class LoaderSetDocker(cluster.BaseLoaderSet, DockerCluster):

    def __init__(self, **kwargs):
        user_prefix = kwargs.get('user_prefix')
        node_prefix = cluster.prepend_user_prefix(user_prefix, 'loader-node')
        cluster_prefix = cluster.prepend_user_prefix(user_prefix, 'loader-set')

        cluster.BaseLoaderSet.__init__(self,
                                       params=kwargs.get("params"))
        DockerCluster.__init__(self,
                               node_prefix=node_prefix,
                               cluster_prefix=cluster_prefix, **kwargs)

    def node_setup(self, node, verbose=False, db_node_address=None, **kwargs):
        self.install_gemini(node=node)
        if self.params.get('client_encrypt'):
            node.config_client_encrypt()


def send_receive_files(self, src, dst, delete_dst=False, preserve_perm=True, preserve_symlinks=False):  # pylint: disable=too-many-arguments,unused-argument
    if src != dst:
        self.remoter.run(f'cp {src} {dst}')


class DockerMonitoringNode(cluster.BaseNode):  # pylint: disable=abstract-method,too-many-instance-attributes
    def __init__(self,  # pylint: disable=too-many-arguments
                 name,
                 parent_cluster,
                 base_logdir=None,
                 ssh_login_info=None,
                 node_prefix=None,
                 dc_idx=None):
        super(DockerMonitoringNode, self).__init__(name=name,
                                                   parent_cluster=parent_cluster,
                                                   base_logdir=base_logdir,
                                                   ssh_login_info=ssh_login_info,
                                                   node_prefix=node_prefix,
                                                   dc_idx=dc_idx)
        self.log = SDCMAdapter(LOGGER, extra={'prefix': str(self)})
        self._grafana_address = None

    def _init_remoter(self, ssh_login_info):  # pylint: disable=no-self-use
        self.remoter = LOCALRUNNER
        self.remoter.receive_files = types.MethodType(send_receive_files, self)
        self.remoter.send_files = types.MethodType(send_receive_files, self)

    def _init_port_mapping(self):  # pylint: disable=no-self-use
        pass

    def wait_ssh_up(self, verbose=True, timeout=500):
        pass

    def update_repo_cache(self):
        pass

    def _refresh_instance_state(self):
        return ["127.0.0.1"], ["127.0.0.1"]

    @property
    def grafana_address(self):
        """
        the communication address for usage between the test and grafana server
        :return:
        """
        # Under docker grafana is starting in port mapping mode and have no dedicated ip address
        # because this address is going to be used by RemoteWebDriver from RemoteWebDriverContainer
        # we can't provide 127.0.0.1 to it
        # Solution here is to get provide gateway from bridge network, since port mapping works on that ip address too.

        if self._grafana_address is not None:
            return self._grafana_address
        self._grafana_address = get_docker_bridge_gateway(self.remoter)
        return self._grafana_address


class MonitorSetDocker(cluster.BaseMonitorSet, DockerCluster):  # pylint: disable=abstract-method
    def __init__(self, **kwargs):
        user_prefix = kwargs.get('user_prefix')
        node_prefix = cluster.prepend_user_prefix(user_prefix, 'monitor-node')
        cluster_prefix = cluster.prepend_user_prefix(user_prefix, 'monitor-set')

        cluster.BaseMonitorSet.__init__(self,
                                        targets=kwargs.get('targets'),
                                        params=kwargs.get('params'))
        DockerCluster.__init__(self,
                               node_prefix=node_prefix,
                               cluster_prefix=cluster_prefix,
                               **kwargs)

    def add_nodes(self, count, ec2_user_data='', dc_idx=0, enable_auto_bootstrap=False):
        return self._create_nodes(count, dc_idx, enable_auto_bootstrap)

    def _create_nodes(self, count, dc_idx=0, enable_auto_bootstrap=False):  # pylint: disable=unused-argument
        """
        Create nodes from docker containers
        :param count: count of nodes to create
        :param dc_idx: datacenter index
        :return: list of DockerNode objects
        """
        new_nodes = []
        for _ in range(count):
            node_name, _ = self._get_node_name_and_index()
            new_node = self._create_node(node_name)
            self.nodes.append(new_node)
            new_nodes.append(new_node)
        return new_nodes

    @staticmethod
    def install_scylla_monitoring_prereqs(node):  # pylint: disable=invalid-name
        # since running local, don't install anything, just the monitor
        pass

    def _create_node(self, node_name):
        return DockerMonitoringNode(name=node_name,
                                    parent_cluster=self,
                                    base_logdir=self.logdir,
                                    node_prefix=self.node_prefix)

    def get_backtraces(self):
        pass

    def destroy(self):
        for node in self.nodes:
            try:
                self.stop_selenium_remote_webdriver(node)
                self.log.error(f"Stopping Selenium WebDriver succeded")
            except Exception as exc:  # pylint: disable=broad-except
                self.log.error(f"Stopping Selenium WebDriver failed with {str(exc)}")
            try:
                self.stop_scylla_monitoring(node)
                self.log.error(f"Stopping scylla monitoring succeeded")
            except Exception as exc:  # pylint: disable=broad-except
                self.log.error(f"Stopping scylla monitoring failed with {str(exc)}")
            try:
                node.remoter.run(f"sudo rm -rf '{self._monitor_install_path_base}'")
                self.log.error(f"Cleaning up scylla monitoring succeeded")
            except Exception as exc:  # pylint: disable=broad-except
                self.log.error(f"Cleaning up scylla monitoring failed with {str(exc)}")
