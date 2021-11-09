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
import abc
import contextlib
import datetime
import time
from textwrap import dedent
from typing import Any, Callable, List, Dict, Optional

import boto3
from botocore.exceptions import ClientError
from mypy_boto3_ec2 import EC2ServiceResource, EC2Client
from mypy_boto3_ec2.service_resource import Instance
from mypy_boto3_ec2.type_defs import InstanceTypeDef, SpotFleetLaunchSpecificationTypeDef, \
    RequestSpotLaunchSpecificationTypeDef, SpotFleetRequestConfigDataTypeDef

from sdcm.provision.aws.constants import SPOT_REQUEST_TIMEOUT, SPOT_REQUEST_WAITING_TIME, STATUS_FULFILLED, \
    SPOT_STATUS_UNEXPECTED_ERROR, SPOT_PRICE_TOO_LOW, FLEET_LIMIT_EXCEEDED_ERROR, SPOT_CAPACITY_NOT_AVAILABLE_ERROR
from sdcm.provision.common.provisioner import TagsType


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class GlobalDictOfInstances(dict, metaclass=Singleton):
    @abc.abstractmethod
    def _create_instance(self, item: str) -> Any:
        pass

    def __getitem__(self, item: str) -> Any:
        if item_value := self.get(item, None):
            return item_value
        item_value = self._create_instance(item)
        self[item] = item_value
        return item_value


class Ec2ServicesDict(GlobalDictOfInstances):
    def _create_instance(self, item: str) -> EC2ServiceResource:
        return boto3.session.Session(region_name=item).resource('ec2')

    __getitem__: Callable[[str], EC2ServiceResource]


class Ec2ClientsDict(GlobalDictOfInstances):
    def _create_instance(self, item: str) -> EC2Client:
        return boto3.client(service_name='ec2', region_name=item)

    __getitem__: Callable[[str], EC2Client]


class Ec2ServiceResourcesDict(GlobalDictOfInstances):
    def _create_instance(self, item: str) -> EC2ServiceResource:
        return boto3.resource('ec2', region_name=item)

    __getitem__: Callable[[str], EC2ServiceResource]


ec2_services = Ec2ServicesDict()
ec2_clients = Ec2ClientsDict()
ec2_resources = Ec2ServiceResourcesDict()


def get_subnet_info(region_name: str, subnet_id: str):
    resp = ec2_clients[region_name].describe_subnets(SubnetIds=[subnet_id])
    return [subnet for subnet in resp['Subnets'] if subnet['SubnetId'] == subnet_id][0]


def convert_tags_to_aws_format(tags: TagsType) -> List[Dict[str, str]]:
    return [{'Key': str(name), 'Value': str(value)} for name, value in tags.items()]


def convert_tags_to_filters(tags: TagsType) -> List[Dict[str, str]]:
    return [{'Name': 'tag:{}'.format(name), 'Values': value if isinstance(
        value, list) else [value]} for name, value in tags.items()]


def find_instance_descriptions_by_tags(region_name: str, tags: TagsType) -> List[InstanceTypeDef]:
    client: EC2Client = ec2_clients[region_name]
    response = client.describe_instances(Filters=convert_tags_to_filters(tags))
    return [instance for reservation in response['Reservations'] for instance in reservation['Instances']]


def find_instances_by_tags(region_name: str, tags: TagsType, states: List[str] = None) -> List[Instance]:
    instances = []
    for instance_description in find_instance_descriptions_by_tags(region_name=region_name, tags=tags):
        if states and instance_description['State']['Name'] not in states:
            continue
        instances.append(find_instance_by_id(region_name=region_name, instance_id=instance_description['InstanceId']))
    return instances


def find_instance_by_id(region_name: str, instance_id: str) -> Instance:
    return ec2_resources[region_name].Instance(id=instance_id)  # pylint: disable=no-member


def set_tags_on_instances(region_name: str, instance_ids: List[str], tags: TagsType):
    end_time = time.perf_counter() + 20
    while end_time > time.perf_counter():
        with contextlib.suppress(ClientError):
            ec2_clients[region_name].create_tags(  # pylint: disable=no-member
                Resources=instance_ids,
                Tags=convert_tags_to_aws_format(tags))
            return True
    return False


def wait_for_provision_request_done(
        region_name: str, request_ids: List[str], is_fleet: bool,
        timeout: float = SPOT_REQUEST_TIMEOUT,
        wait_interval: float = SPOT_REQUEST_WAITING_TIME):
    waiting_time = 0
    provisioned_instance_ids = []
    while not provisioned_instance_ids and waiting_time < timeout:
        time.sleep(wait_interval)
        if is_fleet:
            provisioned_instance_ids = get_provisioned_fleet_instance_ids(
                region_name=region_name, request_ids=request_ids)
        else:
            provisioned_instance_ids = get_provisioned_spot_instance_ids(
                region_name=region_name, request_ids=request_ids)
        if provisioned_instance_ids is None:
            break
        waiting_time += wait_interval
    return provisioned_instance_ids


def get_provisioned_fleet_instance_ids(region_name: str, request_ids: List[str]) -> Optional[List[str]]:
    try:
        resp = ec2_clients[region_name].describe_spot_fleet_requests(SpotFleetRequestIds=request_ids)
    except Exception:  # pylint: disable=broad-except
        return []
    for req in resp['SpotFleetRequestConfigs']:
        if req['SpotFleetRequestState'] == 'active' and req.get('ActivityStatus', None) == STATUS_FULFILLED:
            continue
        if 'ActivityStatus' in req and req['ActivityStatus'] == SPOT_STATUS_UNEXPECTED_ERROR:
            current_time = datetime.datetime.now().timetuple()
            search_start_time = datetime.datetime(
                current_time.tm_year, current_time.tm_mon, current_time.tm_mday)
            resp = ec2_clients[region_name].describe_spot_fleet_request_history(
                SpotFleetRequestId=req['SpotFleetRequestId'],
                StartTime=search_start_time,
                MaxResults=10,
            )
            errors = [i['EventInformation']['EventSubType'] for i in resp['HistoryRecords']]
            for error in [FLEET_LIMIT_EXCEEDED_ERROR, SPOT_CAPACITY_NOT_AVAILABLE_ERROR]:
                if error in errors:
                    return None
        return []
    provisioned_instances = []
    for request_id in request_ids:
        try:
            resp = ec2_clients[region_name].describe_spot_fleet_instances(SpotFleetRequestId=request_id)
        except Exception:  # pylint: disable=broad-except
            return None
        provisioned_instances.extend([inst['InstanceId'] for inst in resp['ActiveInstances']])
    return provisioned_instances


def get_provisioned_spot_instance_ids(region_name: str, request_ids: List[str]) -> Optional[List[str]]:
    """
    Return list of provisioned instances if all requests where fulfilled
      if any of the requests failed it will return empty list
      if any of the requests failed critically and could not be fulfilled return None
    """
    try:
        resp = ec2_clients[region_name].describe_spot_instance_requests(SpotInstanceRequestIds=request_ids)
    except Exception:  # pylint: disable=broad-except
        return []
    provisioned = []
    for req in resp['SpotInstanceRequests']:
        if req['Status']['Code'] != STATUS_FULFILLED or req['State'] != 'active':
            if req['Status']['Code'] in [SPOT_PRICE_TOO_LOW, SPOT_CAPACITY_NOT_AVAILABLE_ERROR]:
                # This code tells that query is not going to be fulfilled
                # And we need to stop the cycle
                return None
            return []
        provisioned.append(req['InstanceId'])
    return provisioned


#  pylint: disable=too-many-arguments
def create_spot_fleet_instance_request(
        region_name: str,
        count: int,
        price: float,
        fleet_role: str,
        instance_parameters: SpotFleetLaunchSpecificationTypeDef,
        valid_until: datetime.datetime = None) -> str:
    params = SpotFleetRequestConfigDataTypeDef(
        LaunchSpecifications=[instance_parameters],
        IamFleetRole=fleet_role,
        SpotPrice=str(price),
        TargetCapacity=count,
    )
    if valid_until:
        params['ValidUntil'] = valid_until
    resp = ec2_clients[region_name].request_spot_fleet(DryRun=False, SpotFleetRequestConfig=params)
    return resp['SpotFleetRequestId']


#  pylint: disable=too-many-arguments
def create_spot_instance_request(
        region_name: str,
        count: int,
        price: Optional[float],
        instance_parameters: RequestSpotLaunchSpecificationTypeDef,
        full_availability_zone: str,
        valid_until: datetime.datetime = None,
        duration: int = None,
) -> List[str]:
    params = {
        'DryRun': False,
        'InstanceCount': count,
        'Type': 'one-time',
        'LaunchSpecification': instance_parameters,
        'AvailabilityZoneGroup': full_availability_zone,
    }
    if duration:
        params['BlockDurationMinutes'] = duration
    if price:
        params['SpotPrice'] = str(price)
    if valid_until:
        params['ValidUntil'] = valid_until
    resp = ec2_clients[region_name].request_spot_instances(**params)
    return [req['SpotInstanceRequestId'] for req in resp['SpotInstanceRequests']]


def sort_by_index(item: dict) -> str:
    for tag in item['Tags']:
        if tag['Key'] == 'NodeIndex':
            return tag['Value']
    return '0'


def network_config_ipv6_workaround_script():
    return dedent("""
        if grep -qi "ubuntu" /etc/os-release; then
            echo "On Ubuntu we don't need this workaround, so done"
        else
            BASE_EC2_NETWORK_URL=http://169.254.169.254/latest/meta-data/network/interfaces/macs/
            MAC=`curl -s ${BASE_EC2_NETWORK_URL}`
            IPv6_CIDR=`curl -s ${BASE_EC2_NETWORK_URL}${MAC}/subnet-ipv6-cidr-blocks`

            while ! ls /etc/sysconfig/network-scripts/ifcfg-eth0; do sleep 1; done

            if ! grep -qi "amazon linux" /etc/os-release; then
                ip route add $IPv6_CIDR dev eth0
                echo "ip route add $IPv6_CIDR dev eth0" >> /etc/sysconfig/network-scripts/init.ipv6-global
            fi

            if grep -q IPV6_AUTOCONF /etc/sysconfig/network-scripts/ifcfg-eth0; then
                sed -i 's/^IPV6_AUTOCONF=[^ ]*/IPV6_AUTOCONF=yes/' /etc/sysconfig/network-scripts/ifcfg-eth0
            else
                echo "IPV6_AUTOCONF=yes" >> /etc/sysconfig/network-scripts/ifcfg-eth0
                echo "echo \"IPV6_AUTOCONF=yes\" >> /etc/sysconfig/network-scripts/ifcfg-eth0" >>/CMDS
            fi

            if grep -q IPV6_DEFROUTE /etc/sysconfig/network-scripts/ifcfg-eth0; then
                sed -i 's/^IPV6_DEFROUTE=[^ ]*/IPV6_DEFROUTE=yes/' /etc/sysconfig/network-scripts/ifcfg-eth0
            else
                echo "IPV6_DEFROUTE=yes" >> /etc/sysconfig/network-scripts/ifcfg-eth0
            fi

            systemctl restart network
        fi
    """)


def configure_eth1_script():
    return dedent(r"""
        if grep -qi "ubuntu" /etc/os-release; then

            ETH1_IP_ADDRESS=`ip route show | grep eth1 | grep -oPm1 'src \K[0-9]*\.[0-9]*\.[0-9]*\.[0-9]*'`
            ETH1_CIDR_BLOCK=`ip route show | grep eth1 | grep -oPm1 '\K[0-9]*\.[0-9]*\.[0-9]*\.[0-9]*/[0-9]*'`
            ETH1_SUBNET=`echo ${ETH1_CIDR_BLOCK} | grep -oP '\\K/\\d+'`

            bash -c "echo '
            network:
              version: 2
              renderer: networkd
              ethernets:
                eth0:
                  dhcp4: yes
                  dhcp6: yes
                eth1:
                  addresses:
                   - ${ETH1_IP_ADDRESS}${ETH1_SUBNET}
                  dhcp4: no
                  dhcp6: no
                  routes:
                   - to: 0.0.0.0/0
                     via: 10.0.0.1 # Default gateway
                     table: 2
                   - to: ${ETH1_CIDR_BLOCK}
                     scope: link
                     table: 2
                  routing-policy:
                    - from: ${ETH1_IP_ADDRESS}/32
                      table: 2
            ' > /etc/netplan/51-eth1.yaml"

            netplan --debug apply

        else

            BASE_EC2_NETWORK_URL=http://169.254.169.254/latest/meta-data/network/interfaces/macs/
            NUMBER_OF_ENI=`curl -s ${BASE_EC2_NETWORK_URL} | wc -w`
            for mac in `curl -s ${BASE_EC2_NETWORK_URL}`
            do
                DEVICE_NUMBER=`curl -s ${BASE_EC2_NETWORK_URL}${mac}/device-number`
                if [[ "$DEVICE_NUMBER" == "1" ]]; then
                   ETH1_MAC=${mac}
                fi
            done
            if [[ ! "${DEVICE_NUMBER}x" == "x" ]]; then
               ETH1_IP_ADDRESS=`curl -s ${BASE_EC2_NETWORK_URL}${ETH1_MAC}/local-ipv4s`
               ETH1_CIDR_BLOCK=`curl -s ${BASE_EC2_NETWORK_URL}${ETH1_MAC}/subnet-ipv4-cidr-block`
            fi
            bash -c "echo 'GATEWAYDEV=eth0' >> /etc/sysconfig/network"
            echo "
            DEVICE="eth1"
            BOOTPROTO="dhcp"
            ONBOOT="yes"
            TYPE="Ethernet"
            USERCTL="yes"
            PEERDNS="yes"
            IPV6INIT="no"
            PERSISTENT_DHCLIENT="1"
            " > /etc/sysconfig/network-scripts/ifcfg-eth1
            echo "
            default via 10.0.0.1 dev eth1 table 2
            ${ETH1_CIDR_BLOCK} dev eth1 src ${ETH1_IP_ADDRESS} table 2
            " > /etc/sysconfig/network-scripts/route-eth1
            echo "
            from ${ETH1_IP_ADDRESS}/32 table 2
            " > /etc/sysconfig/network-scripts/rule-eth1
            systemctl restart network

        fi
    """)


def configure_set_preserve_hostname_script():
    return 'grep "preserve_hostname: true" /etc/cloud/cloud.cfg 1>/dev/null 2>&1 ' \
           '|| echo "preserve_hostname: true" >> /etc/cloud/cloud.cfg\n'
