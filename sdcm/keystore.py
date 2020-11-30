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

import os
import json
from collections import namedtuple

import boto3
import paramiko
from mypy_boto3_s3.service_resource import S3ServiceResource


KEYSTORE_S3_BUCKET = "scylla-qa-keystore"

SSHKey = namedtuple("SSHKey", ["name", "public_key", "private_key"])


class KeyStore:
    def __init__(self):
        self.s3: S3ServiceResource = boto3.resource("s3")

    def get_file_contents(self, file_name):
        obj = self.s3.Object(KEYSTORE_S3_BUCKET, file_name)
        return obj.get()["Body"].read()

    def get_json(self, json_file):
        # deepcode ignore replace~read~decode~json.loads: is done automatically
        return json.loads(self.get_file_contents(json_file))

    def download_file(self, filename, dest_filename):
        with open(dest_filename, 'w') as file_obj:
            file_obj.write(self.get_file_contents(filename).decode())

    def get_email_credentials(self):
        return self.get_json("email_config.json")

    def get_elasticsearch_credentials(self):
        return self.get_json("es.json")

    def get_gcp_credentials(self):
        return self.get_json("gcp.json")

    def get_gcp_service_accounts(self):
        return self.get_json("gcp_service_accounts.json")

    def get_scylladb_upload_credentials(self):
        return self.get_json("scylladb_upload.json")

    def get_qa_users(self):
        return self.get_json("qa_users.json")

    def get_ssh_key_pair(self, name):
        return SSHKey(name=name,
                      public_key=self.get_file_contents(file_name=f"{name}.pub"),
                      private_key=self.get_file_contents(file_name=name))

    def get_ec2_ssh_key_pair(self):
        return self.get_ssh_key_pair(name="scylla-qa-ec2")

    def get_gce_ssh_key_pair(self):
        return self.get_ssh_key_pair(name="scylla-test")

    def get_qa_ssh_keys(self):
        return [
            self.get_ec2_ssh_key_pair(),
            self.get_gce_ssh_key_pair(),
        ]

    def get_housekeeping_db_credentials(self):
        return self.get_json("housekeeping-db.json")


def pub_key_from_private_key_file(key_file):
    return paramiko.rsakey.RSAKey.from_private_key_file(os.path.expanduser(key_file)).get_base64()
