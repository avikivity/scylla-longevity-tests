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

import os
import uuid
import logging
from typing import Optional
from functools import cached_property

from sdcm.remote import shell_script_cmd
from sdcm.utils.common import list_logs_by_test_id, get_free_port
from sdcm.utils.docker_utils import ContainerManager, Container, DockerException


JEPSEN_IMAGE = "tjake/jepsen"
JEPSEN_RESULTS_PORT = 8080
DB_SSH_KEY = "db_node_ssh_key"

LOGGER = logging.getLogger(__name__)


class JepsenResults:
    _containers = {}

    name = f"jepsen_results-{uuid.uuid4()!s:.8}"
    tags = {}

    def jepsen_container_run_args(self) -> dict:
        exposed_port = get_free_port(ports_to_try=(JEPSEN_RESULTS_PORT, 0, ))
        return dict(image=JEPSEN_IMAGE,
                    entrypoint="/bin/cat",
                    tty=True,
                    name=f"{self.name}-jepsen",
                    ports={f"{JEPSEN_RESULTS_PORT}/tcp": {"HostIp": "0.0.0.0", "HostPort": exposed_port, }, })

    @cached_property
    def _jepsen_container(self) -> Container:
        return ContainerManager.run_container(self, "jepsen")

    def runcmd(self, command: str, detach: bool = False) -> None:
        LOGGER.info("Execute `%s' inside Jepsen container", command)
        res = self._jepsen_container.exec_run(["sh", "-c", command], stream=True, detach=detach)
        for line in res.output:
            LOGGER.info(line.decode("utf-8").rstrip())
        if res.exit_code:
            raise DockerException(f"{self._jepsen_container}: {res.output.decode('utf-8')}")

    @property
    def jepsen_results_port(self) -> Optional[int]:
        return ContainerManager.get_container_port(self, "jepsen", JEPSEN_RESULTS_PORT)

    @staticmethod
    def get_jepsen_data_archive_link(test_id):
        if jepsen_data := [log["link"] for log in list_logs_by_test_id(test_id) if "jepsen-data" in log["type"]]:
            LOGGER.info("Found Jepsen data archives for %s: %s", test_id, jepsen_data)
            return jepsen_data[-1]
        LOGGER.warning("No any archive with Jepsen data for %s", test_id)
        return None

    def restore_jepsen_data(self, test_id):
        if jepsen_data_link := self.get_jepsen_data_archive_link(test_id):
            LOGGER.info("Restore Jepsen data and download all dependecies.")
            self.runcmd(f"wget --no-verbose -O jepsen_data.tar.gz {jepsen_data_link}")
            self.runcmd("tar xzf jepsen_data.tar.gz")
            self.runcmd("cd jepsen-scylla && lein deps")
            return True
        return False

    def run_jepsen_web_server(self, detach: bool = False) -> None:
        if detach:
            ContainerManager.set_container_keep_alive(self, "jepsen")
        self.runcmd(command="cd jepsen-scylla && lein run serve", detach=detach)

    def __del__(self):
        ContainerManager.destroy_all_containers(self)


def general_jepsen_setup(jepsen_node, db_nodes, jepsen_scylla_repo):
    remoter = jepsen_node.remoter
    remoter.sudo("apt-get install -y libjna-java gnuplot graphviz git")
    remoter.run(shell_script_cmd(f"""\
        curl -O https://raw.githubusercontent.com/technomancy/leiningen/stable/bin/lein
        chmod +x lein
        ./lein
        git clone {jepsen_scylla_repo} jepsen-scylla
    """))
    for db_node in db_nodes:
        remoter.run(f"ssh-keyscan -t rsa {db_node.ip_address} >> ~/.ssh/known_hosts")
    remoter.send_files(os.path.expanduser(db_nodes[0].ssh_login_info["key_file"]), DB_SSH_KEY)


def get_jepsen_cmd(db_nodes, test='test', additional_option=''):
    """
    Generate a general jepsen commandline
    """
    nodes = " ".join(f"--node {node.ip_address}" for node in db_nodes)
    creds = f"--username {db_nodes[0].ssh_login_info['user']} --ssh-private-key ~/{DB_SSH_KEY}"
    return f"cd ~/jepsen-scylla && ~/lein run {test} {additional_option} {nodes} {creds} --no-install-scylla"
