import logging
from ipaddress import ip_network
from functools import cached_property

import boto3
import botocore
from mypy_boto3_ec2 import EC2Client, EC2ServiceResource

from sdcm.keystore import KeyStore


LOGGER = logging.getLogger(__name__)


class AwsRegion:
    VPC_NAME = "SCT-vpc"
    VPC_CIDR = ip_network("10.0.0.0/16")
    SECURITY_GROUP_NAME = "SCT-sg"
    SUBNET_NAME = "SCT-subnet-{availability_zone}"
    INTERNET_GATEWAY_NAME = "SCT-igw"
    ROUTE_TABLE_NAME = "SCT-rt"
    KEY_PAIR_NAME = "scylla-qa-ec2"  # TODO: change legacy name to sct-keypair-aws

    def __init__(self, region_name):
        self.region_name = region_name
        self.client: EC2Client = boto3.client("ec2", region_name=region_name)
        self.resource: EC2ServiceResource = boto3.resource("ec2", region_name=region_name)

    @property
    def sct_vpc(self) -> EC2ServiceResource.Vpc:
        vpcs = self.client.describe_vpcs(Filters=[{"Name": "tag:Name", "Values": [self.VPC_NAME]}])
        LOGGER.debug(f"Found VPCs: {vpcs}")
        existing_vpcs = vpcs.get("Vpcs", [])
        if len(existing_vpcs) == 0:
            return None
        assert len(existing_vpcs) == 1, \
            f"More than 1 VPC with {self.VPC_NAME} found in {self.region_name}: {existing_vpcs}"
        return self.resource.Vpc(existing_vpcs[0]["VpcId"])  # pylint: disable=no-member

    def create_vpc(self):
        LOGGER.info("Going to create VPC...")
        if self.sct_vpc:
            LOGGER.warning(f"VPC '{self.VPC_NAME}' already exists!  Id: '{self.sct_vpc.vpc_id}'.")
            return self.sct_vpc.vpc_id
        else:
            result = self.client.create_vpc(CidrBlock=str(self.VPC_CIDR), AmazonProvidedIpv6CidrBlock=True)
            vpc_id = result["Vpc"]["VpcId"]
            vpc = self.resource.Vpc(vpc_id)  # pylint: disable=no-member
            vpc.create_tags(Tags=[{"Key": "Name", "Value": self.VPC_NAME}])
            LOGGER.info("'%s' with id '%s' created. Waiting until it becomes available...", self.VPC_NAME, vpc_id)
            vpc.wait_until_available()
            return vpc_id

    @cached_property
    def availability_zones(self):
        response = self.client.describe_availability_zones()
        return [zone["ZoneName"]for zone in response['AvailabilityZones'] if zone["State"] == "available"]

    @cached_property
    def vpc_ipv6_cidr(self):
        return ip_network(self.sct_vpc.ipv6_cidr_block_association_set[0]["Ipv6CidrBlock"])

    def az_subnet_name(self, region_az):
        return self.SUBNET_NAME.format(availability_zone=region_az)

    def sct_subnet(self, region_az) -> EC2ServiceResource.Subnet:
        subnet_name = self.az_subnet_name(region_az)
        subnets = self.client.describe_subnets(Filters=[{"Name": "tag:Name", "Values": [subnet_name]}])
        LOGGER.debug(f"Found Subnets: {subnets}")
        existing_subnets = subnets.get("Subnets", [])
        if len(existing_subnets) == 0:
            return None
        assert len(existing_subnets) == 1, \
            f"More than 1 Subnet with {subnet_name} found in {self.region_name}: {existing_subnets}!"
        return self.resource.Subnet(existing_subnets[0]["SubnetId"])  # pylint: disable=no-member

    def create_subnet(self, region_az, ipv4_cidr, ipv6_cidr):
        LOGGER.info(f"Creating subnet for {region_az}...")
        subnet_name = self.az_subnet_name(region_az)
        if self.sct_subnet(region_az):
            subnet_id = self.sct_subnet(region_az).subnet_id
            LOGGER.warning(f"Subnet '{subnet_name}' already exists!  Id: '{subnet_id}'.")
        else:

            result = self.client.create_subnet(CidrBlock=str(ipv4_cidr), Ipv6CidrBlock=str(ipv6_cidr),
                                               VpcId=self.sct_vpc.vpc_id, AvailabilityZone=region_az)
            subnet_id = result["Subnet"]["SubnetId"]
            subnet = self.resource.Subnet(subnet_id)  # pylint: disable=no-member
            subnet.create_tags(Tags=[{"Key": "Name", "Value": subnet_name}])
            LOGGER.info("Configuring to automatically assign public IPv4 and IPv6 addresses...")
            self.client.modify_subnet_attribute(
                MapPublicIpOnLaunch={"Value": True},
                SubnetId=subnet_id
            )
            # for some reason boto3 throws error when both AssignIpv6AddressOnCreation and MapPublicIpOnLaunch are used
            self.client.modify_subnet_attribute(
                AssignIpv6AddressOnCreation={"Value": True},
                SubnetId=subnet_id
            )
            LOGGER.info("'%s' with id '%s' created.", subnet_name, subnet_id)

    def create_subnets(self):
        num_subnets = len(self.availability_zones)
        ipv4_cidrs = list(self.VPC_CIDR.subnets(6))[:num_subnets]
        ipv6_cidrs = list(self.vpc_ipv6_cidr.subnets(8))[:num_subnets]
        for i, az_name in enumerate(self.availability_zones):
            self.create_subnet(region_az=az_name, ipv4_cidr=ipv4_cidrs[i], ipv6_cidr=ipv6_cidrs[i])

    @property
    def sct_internet_gateway(self) -> EC2ServiceResource.InternetGateway:
        igws = self.client.describe_internet_gateways(Filters=[{"Name": "tag:Name",
                                                                "Values": [self.INTERNET_GATEWAY_NAME]}])
        LOGGER.debug(f"Found Internet gateways: {igws}")
        existing_igws = igws.get("InternetGateways", [])
        if len(existing_igws) == 0:
            return None
        assert len(existing_igws) == 1, \
            f"More than 1 Internet Gateway with {self.INTERNET_GATEWAY_NAME} found " \
            f"in {self.region_name}: {existing_igws}!"
        return self.resource.InternetGateway(existing_igws[0]["InternetGatewayId"])  # pylint: disable=no-member

    def create_internet_gateway(self):
        LOGGER.info("Creating Internet Gateway..")
        if self.sct_internet_gateway:
            LOGGER.warning(f"Internet Gateway '{self.INTERNET_GATEWAY_NAME}' already exists! "
                           f"Id: '{self.sct_internet_gateway.internet_gateway_id}'.")
        else:
            result = self.client.create_internet_gateway()
            igw_id = result["InternetGateway"]["InternetGatewayId"]
            igw = self.resource.InternetGateway(igw_id)  # pylint: disable=no-member
            igw.create_tags(Tags=[{"Key": "Name", "Value": self.INTERNET_GATEWAY_NAME}])
            LOGGER.info("'%s' with id '%s' created. Attaching to '%s'",
                        self.INTERNET_GATEWAY_NAME, igw_id, self.sct_vpc.vpc_id)
            igw.attach_to_vpc(VpcId=self.sct_vpc.vpc_id)

    @cached_property
    def sct_route_table(self) -> EC2ServiceResource.RouteTable:
        route_tables = self.client.describe_route_tables(Filters=[{"Name": "tag:Name",
                                                                   "Values": [self.ROUTE_TABLE_NAME]}])
        LOGGER.debug(f"Found Route Tables: {route_tables}")
        existing_rts = route_tables.get("RouteTables", [])
        if len(existing_rts) == 0:
            return None
        assert len(existing_rts) == 1, \
            f"More than 1 Route Table with {self.ROUTE_TABLE_NAME} found " \
            f"in {self.region_name}: {existing_rts}!"
        return self.resource.RouteTable(existing_rts[0]["RouteTableId"])  # pylint: disable=no-member

    def configure_route_table(self):
        # add route to Internet: 0.0.0.0/0 -> igw
        LOGGER.info("Configuring main Route Table...")
        if self.sct_route_table:
            LOGGER.warning(f"Route Table '{self.ROUTE_TABLE_NAME}' already exists! "
                           f"Id: '{self.sct_route_table.route_table_id}'.")
        else:
            route_tables = list(self.sct_vpc.route_tables.all())
            assert len(route_tables) == 1, f"Only one main route table should exist for {self.VPC_NAME}. " \
                                           f"Found {len(route_tables)}!"
            route_table: EC2ServiceResource.RouteTable = route_tables[0]
            route_table.create_tags(Tags=[{"Key": "Name", "Value": self.ROUTE_TABLE_NAME}])
            LOGGER.info("Setting routing of all outbound traffic via Internet Gateway...")
            route_table.create_route(DestinationCidrBlock="0.0.0.0/0",
                                     GatewayId=self.sct_internet_gateway.internet_gateway_id)
            route_table.create_route(DestinationIpv6CidrBlock="::/0",
                                     GatewayId=self.sct_internet_gateway.internet_gateway_id)
            LOGGER.info("Going to associate all Subnets with the Route Table...")
            for az_name in self.availability_zones:
                subnet_id = self.sct_subnet(az_name).subnet_id
                LOGGER.info("Associating Route Table with '%s' [%s]...", self.az_subnet_name(az_name), subnet_id)
                route_table.associate_with_subnet(SubnetId=subnet_id)

    @property
    def sct_security_group(self) -> EC2ServiceResource.SecurityGroup:
        security_groups = self.client.describe_security_groups(Filters=[{"Name": "tag:Name",
                                                                         "Values": [self.SECURITY_GROUP_NAME]}])
        LOGGER.debug(f"Found Security Groups: {security_groups}")
        existing_sgs = security_groups.get("SecurityGroups", [])
        if len(existing_sgs) == 0:
            return None
        assert len(existing_sgs) == 1, \
            f"More than 1 Security group with {self.SECURITY_GROUP_NAME} found " \
            f"in {self.region_name}: {existing_sgs}!"
        return self.resource.SecurityGroup(existing_sgs[0]["GroupId"])  # pylint: disable=no-member

    def create_security_group(self):
        """

        Custom TCP	TCP	9093	0.0.0.0/0	Allow alert manager for all
        Custom TCP	TCP	9093	::/0	Allow alert manager for all

        """
        LOGGER.info("Creating Security Group...")
        if self.sct_security_group:
            LOGGER.warning(f"Security Group '{self.SECURITY_GROUP_NAME}' already exists! "
                           f"Id: '{self.sct_internet_gateway.internet_gateway_id}'.")
        else:
            result = self.client.create_security_group(Description='Security group that is used by SCT',
                                                       GroupName=self.SECURITY_GROUP_NAME,
                                                       VpcId=self.sct_vpc.vpc_id)
            sg_id = result["GroupId"]
            security_group = self.resource.SecurityGroup(sg_id)  # pylint: disable=no-member
            security_group.create_tags(Tags=[{"Key": "Name", "Value": self.SECURITY_GROUP_NAME}])
            LOGGER.info("'%s' with id '%s' created. ", self.SECURITY_GROUP_NAME, self.sct_security_group.group_id)
            LOGGER.info("Creating common ingress rules...")
            security_group.authorize_ingress(
                IpPermissions=[
                    {
                        "IpProtocol": "-1",
                        "UserIdGroupPairs": [
                            {
                                "Description": "Allow ALL traffic inside the Security group",
                                "GroupId": sg_id,
                                "UserId": security_group.owner_id
                            }
                        ]
                    },
                    {
                        "FromPort": 22,
                        "ToPort": 22,
                        "IpProtocol": "tcp",
                        "IpRanges": [{'CidrIp': '0.0.0.0/0', 'Description': 'SSH connectivity to the instances'}],
                        "Ipv6Ranges": [{'CidrIpv6': '::/0', 'Description': 'SSH connectivity to the instances'}]
                    },
                    {
                        "FromPort": 3000,
                        "ToPort": 3000,
                        "IpProtocol": "tcp",
                        "IpRanges": [{'CidrIp': '0.0.0.0/0', 'Description': 'Allow Grafana for ALL'}],
                        "Ipv6Ranges": [{'CidrIpv6': '::/0', 'Description': 'Allow Grafana for ALL'}]
                    },
                    {
                        "FromPort": 9042,
                        "ToPort": 9042,
                        "IpProtocol": "tcp",
                        "IpRanges": [{'CidrIp': '0.0.0.0/0', 'Description': 'Allow CQL for ALL'}],
                        "Ipv6Ranges": [{'CidrIpv6': '::/0', 'Description': 'Allow CQL for ALL'}]
                    },
                    {
                        "FromPort": 9142,
                        "ToPort": 9142,
                        "IpProtocol": "tcp",
                        "IpRanges": [{'CidrIp': '0.0.0.0/0', 'Description': 'Allow SSL CQL for ALL'}],
                        "Ipv6Ranges": [{'CidrIpv6': '::/0', 'Description': 'Allow SSL CQL for ALL'}]
                    },
                    {
                        "FromPort": 9100,
                        "ToPort": 9100,
                        "IpProtocol": "tcp",
                        "IpRanges": [{'CidrIp': '0.0.0.0/0', 'Description': 'Allow node_exporter on Db nodes for ALL'}],
                        "Ipv6Ranges": [{'CidrIpv6': '::/0', 'Description': 'Allow node_exporter on Db nodes for ALL'}]
                    },
                    {
                        "FromPort": 8080,
                        "ToPort": 8080,
                        "IpProtocol": "tcp",
                        "IpRanges": [{'CidrIp': '0.0.0.0/0', 'Description': 'Allow Alternator for ALL'}],
                        "Ipv6Ranges": [{'CidrIpv6': '::/0', 'Description': 'Allow Alternator for ALL'}]
                    },
                    {
                        "FromPort": 9090,
                        "ToPort": 9090,
                        "IpProtocol": "tcp",
                        "IpRanges": [{'CidrIp': '0.0.0.0/0', 'Description': 'Allow Prometheus for ALL'}],
                        "Ipv6Ranges": [{'CidrIpv6': '::/0', 'Description': 'Allow  Prometheus for ALL'}]
                    },
                    {
                        "FromPort": 9180,
                        "ToPort": 9180,
                        "IpProtocol": "tcp",
                        "IpRanges": [{'CidrIp': '0.0.0.0/0', 'Description': 'Allow Prometheus API for ALL'}],
                        "Ipv6Ranges": [{'CidrIpv6': '::/0', 'Description': 'Allow Prometheus API for ALL'}]
                    },
                    {
                        "FromPort": 7000,
                        "ToPort": 7000,
                        "IpProtocol": "tcp",
                        "IpRanges": [{'CidrIp': '0.0.0.0/0',
                                      'Description': 'Allow Inter-node communication (RPC) for ALL'}],
                        "Ipv6Ranges": [{'CidrIpv6': '::/0',
                                        'Description': 'Allow Inter-node communication (RPC) for ALL'}]
                    },
                    {
                        "FromPort": 7001,
                        "ToPort": 7001,
                        "IpProtocol": "tcp",
                        "IpRanges": [{'CidrIp': '0.0.0.0/0',
                                      'Description': 'Allow SSL inter-node communication (RPC) for ALL'}],
                        "Ipv6Ranges": [{'CidrIpv6': '::/0',
                                        'Description': 'Allow SSL inter-node communication (RPC) for ALL'}]
                    },
                    {
                        "FromPort": 7199,
                        "ToPort": 7199,
                        "IpProtocol": "tcp",
                        "IpRanges": [{'CidrIp': '0.0.0.0/0', 'Description': 'Allow JMX management for ALL'}],
                        "Ipv6Ranges": [{'CidrIpv6': '::/0', 'Description': 'Allow JMX management for ALL'}]
                    },
                    {
                        "FromPort": 10001,
                        "ToPort": 10001,
                        "IpProtocol": "tcp",
                        "IpRanges": [{'CidrIp': '0.0.0.0/0',
                                      'Description': 'Allow Scylla Manager Agent REST API  for ALL'}],
                        "Ipv6Ranges": [{'CidrIpv6': '::/0',
                                        'Description': 'Allow Scylla Manager Agent REST API for ALL'}]
                    },
                    {
                        "FromPort": 56090,
                        "ToPort": 56090,
                        "IpProtocol": "tcp",
                        "IpRanges": [{'CidrIp': '0.0.0.0/0',
                                      'Description': 'Allow Scylla Manager Agent Prometheus API for ALL'}],
                        "Ipv6Ranges": [{'CidrIpv6': '::/0',
                                        'Description': 'Allow Scylla Manager Agent Prometheus API for ALL'}]
                    },
                    {
                        "IpProtocol": "-1",
                        "IpRanges": [{'CidrIp': '172.0.0.0/11',
                                      'Description': 'Allow traffic from Scylla Cloud lab while VPC peering for ALL'}],
                    }
                ]
            )

    @property
    def sct_keypair(self):
        try:
            key_pairs = self.client.describe_key_pairs(KeyNames=[self.KEY_PAIR_NAME])
        except botocore.exceptions.ClientError as ex:
            if "InvalidKeyPair.NotFound" in str(ex):
                return None
            else:
                raise
        LOGGER.debug(f"Found key pairs: {key_pairs}")
        existing_key_pairs = key_pairs.get("KeyPairs", [])
        assert len(existing_key_pairs) == 1, \
            f"More than 1 Key Pair with {self.KEY_PAIR_NAME} found " \
            f"in {self.region_name}: {existing_key_pairs}!"
        return self.resource.KeyPair(existing_key_pairs[0]["KeyName"])  # pylint: disable=no-member

    def create_key_pair(self):
        LOGGER.info("Creating SCT Key Pair...")
        if self.sct_keypair:
            LOGGER.warning(f"SCT Key Pair already exists in {self.region_name}!")
        else:
            ks = KeyStore()
            sct_key_pair = ks.get_ec2_ssh_key_pair()
            self.resource.import_key_pair(KeyName=self.KEY_PAIR_NAME,  # pylint: disable=no-member
                                          PublicKeyMaterial=sct_key_pair.public_key)
            LOGGER.info("SCT Key Pair created.")

    def configure(self):
        LOGGER.info(f"Configuring '{self.region_name}' region...")
        self.create_vpc()
        self.create_subnets()
        self.create_internet_gateway()
        self.configure_route_table()
        self.create_security_group()
        self.create_key_pair()
        LOGGER.info("Region configured successfully.")


if __name__ == "__main__":
    AWS_REGION = AwsRegion(region_name="eu-west-2")
    AWS_REGION.configure()
