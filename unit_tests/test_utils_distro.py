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

from __future__ import absolute_import

import unittest

from sdcm.utils.distro import Distro, DistroError


DISTROS_OS_RELEASE = {
    "Debian 9": """\
PRETTY_NAME="Debian GNU/Linux 9 (stretch)"
NAME="Debian GNU/Linux"
VERSION_ID="9"
VERSION="9 (stretch)"
VERSION_CODENAME=stretch
ID=debian
HOME_URL="https://www.debian.org/"
SUPPORT_URL="https://www.debian.org/support"
BUG_REPORT_URL="https://bugs.debian.org/"
""",

    "Debian 10": """\
PRETTY_NAME="Debian GNU/Linux 10 (buster)"
NAME="Debian GNU/Linux"
VERSION_ID="10"
VERSION="10 (buster)"
VERSION_CODENAME=buster
ID=debian
HOME_URL="https://www.debian.org/"
SUPPORT_URL="https://www.debian.org/support"
BUG_REPORT_URL="https://bugs.debian.org/"
""",

    "CentOS 7": """\
NAME="CentOS Linux"
VERSION="7 (Core)"
ID="centos"
ID_LIKE="rhel fedora"
VERSION_ID="7"
PRETTY_NAME="CentOS Linux 7 (Core)"
ANSI_COLOR="0;31"
CPE_NAME="cpe:/o:centos:centos:7"
HOME_URL="https://www.centos.org/"
BUG_REPORT_URL="https://bugs.centos.org/"

CENTOS_MANTISBT_PROJECT="CentOS-7"
CENTOS_MANTISBT_PROJECT_VERSION="7"
REDHAT_SUPPORT_PRODUCT="centos"
REDHAT_SUPPORT_PRODUCT_VERSION="7"
""",

    "CentOS 8": """\
NAME="CentOS Linux"
VERSION="8 (Core)"
ID="centos"
ID_LIKE="rhel fedora"
VERSION_ID="8"
PLATFORM_ID="platform:el8"
PRETTY_NAME="CentOS Linux 8 (Core)"
ANSI_COLOR="0;31"
CPE_NAME="cpe:/o:centos:centos:8"
HOME_URL="https://www.centos.org/"
BUG_REPORT_URL="https://bugs.centos.org/"

CENTOS_MANTISBT_PROJECT="CentOS-8"
CENTOS_MANTISBT_PROJECT_VERSION="8"
REDHAT_SUPPORT_PRODUCT="centos"
REDHAT_SUPPORT_PRODUCT_VERSION="8"
""",

    "RHEL 7": """\
NAME="Red Hat Enterprise Linux Server"
VERSION="7.7 (Maipo)"
ID="rhel"
ID_LIKE="fedora"
VARIANT="Server"
VARIANT_ID="server"
VERSION_ID="7.7"
PRETTY_NAME="Red Hat Enterprise Linux Server 7.7 (Maipo)"
ANSI_COLOR="0;31"
CPE_NAME="cpe:/o:redhat:enterprise_linux:7.7:GA:server"
HOME_URL="https://www.redhat.com/"
BUG_REPORT_URL="https://bugzilla.redhat.com/"

REDHAT_BUGZILLA_PRODUCT="Red Hat Enterprise Linux 7"
REDHAT_BUGZILLA_PRODUCT_VERSION=7.7
REDHAT_SUPPORT_PRODUCT="Red Hat Enterprise Linux"
REDHAT_SUPPORT_PRODUCT_VERSION="7.7"
""",

    "RHEL 8": """\
NAME="Red Hat Enterprise Linux"
VERSION="8.1 (Ootpa)"
ID="rhel"
ID_LIKE="fedora"
VERSION_ID="8.1"
PLATFORM_ID="platform:el8"
PRETTY_NAME="Red Hat Enterprise Linux 8.1 (Ootpa)"
ANSI_COLOR="0;31"
CPE_NAME="cpe:/o:redhat:enterprise_linux:8.1:GA"
HOME_URL="https://www.redhat.com/"
BUG_REPORT_URL="https://bugzilla.redhat.com/"

REDHAT_BUGZILLA_PRODUCT="Red Hat Enterprise Linux 8"
REDHAT_BUGZILLA_PRODUCT_VERSION=8.1
REDHAT_SUPPORT_PRODUCT="Red Hat Enterprise Linux"
REDHAT_SUPPORT_PRODUCT_VERSION="8.1"
""",

    "OEL 7.3": """\
NAME="Oracle Linux Server"
VERSION="7.3"
ID="ol"
VERSION_ID="7.3"
PRETTY_NAME="Oracle Linux Server 7.3"
ANSI_COLOR="0;31"
CPE_NAME="cpe:/o:oracle:linux:7:3:server"
HOME_URL="https://linux.oracle.com/"
BUG_REPORT_URL="https://bugzilla.oracle.com/"

ORACLE_BUGZILLA_PRODUCT="Oracle Linux 7"
ORACLE_BUGZILLA_PRODUCT_VERSION=7.3
ORACLE_SUPPORT_PRODUCT="Oracle Linux"
ORACLE_SUPPORT_PRODUCT_VERSION=7.3
""",

    "Ubuntu 14.04": """\
NAME="Ubuntu"
VERSION="14.04.6 LTS, Trusty Tahr"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME="Ubuntu 14.04.6 LTS"
VERSION_ID="14.04"
HOME_URL="http://www.ubuntu.com/"
SUPPORT_URL="http://help.ubuntu.com/"
BUG_REPORT_URL="http://bugs.launchpad.net/ubuntu/"
""",

    "Ubuntu 16.04": """\
NAME="Ubuntu"
VERSION="16.04.6 LTS (Xenial Xerus)"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME="Ubuntu 16.04.6 LTS"
VERSION_ID="16.04"
HOME_URL="http://www.ubuntu.com/"
SUPPORT_URL="http://help.ubuntu.com/"
BUG_REPORT_URL="http://bugs.launchpad.net/ubuntu/"
VERSION_CODENAME=xenial
UBUNTU_CODENAME=xenial
""",

    "Ubuntu 18.04": """\
NAME="Ubuntu"
VERSION="18.04.3 LTS (Bionic Beaver)"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME="Ubuntu 18.04.3 LTS"
VERSION_ID="18.04"
HOME_URL="https://www.ubuntu.com/"
SUPPORT_URL="https://help.ubuntu.com/"
BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"
PRIVACY_POLICY_URL="https://www.ubuntu.com/legal/terms-and-policies/privacy-policy"
VERSION_CODENAME=bionic
UBUNTU_CODENAME=bionic
""",

    "Unknown": """\
ID=sillylinux
VERSION_ID=666
""",

    "Garbage": """\
ID ubuntu
VERSION_ID 18.04
""",
}


class TestDistro(unittest.TestCase):
    def test_unknown(self):
        self.assertTrue(Distro.UNKNOWN.is_unknown)
        distro = Distro.from_os_release(DISTROS_OS_RELEASE["Unknown"])
        self.assertTrue(distro.is_unknown)

    def test_debian9(self):
        self.assertTrue(Distro.DEBIAN9.is_debian9)
        distro = Distro.from_os_release(DISTROS_OS_RELEASE["Debian 9"])
        self.assertTrue(distro.is_debian9)
        self.assertTrue(distro.is_debian)

    def test_debian10(self):
        self.assertTrue(Distro.DEBIAN10.is_debian10)
        distro = Distro.from_os_release(DISTROS_OS_RELEASE["Debian 10"])
        self.assertTrue(distro.is_debian10)
        self.assertTrue(distro.is_debian)

    def test_centos7(self):
        self.assertTrue(Distro.CENTOS7.is_centos7)
        distro = Distro.from_os_release(DISTROS_OS_RELEASE["CentOS 7"])
        self.assertTrue(distro.is_centos7)
        self.assertTrue(distro.is_rhel_like)

    def test_centos8(self):
        self.assertTrue(Distro.CENTOS8.is_centos8)
        distro = Distro.from_os_release(DISTROS_OS_RELEASE["CentOS 8"])
        self.assertTrue(distro.is_centos8)
        self.assertTrue(distro.is_rhel_like)

    def test_rhel7(self):
        self.assertTrue(Distro.RHEL7.is_rhel7)
        distro = Distro.from_os_release(DISTROS_OS_RELEASE["RHEL 7"])
        self.assertTrue(distro.is_rhel7)
        self.assertTrue(distro.is_rhel_like)

    def test_rhel8(self):
        self.assertTrue(Distro.RHEL8.is_rhel8)
        distro = Distro.from_os_release(DISTROS_OS_RELEASE["RHEL 8"])
        self.assertTrue(distro.is_rhel8)
        self.assertTrue(distro.is_rhel_like)

    def test_oel7(self):
        self.assertTrue(Distro.OEL7.is_oel7)
        distro = Distro.from_os_release(DISTROS_OS_RELEASE["OEL 7.3"])
        self.assertTrue(distro.is_oel7)
        self.assertTrue(distro.is_rhel_like)

    def test_ubuntu14(self):
        self.assertTrue(Distro.UBUNTU14.is_ubuntu14)
        distro = Distro.from_os_release(DISTROS_OS_RELEASE["Ubuntu 14.04"])
        self.assertTrue(distro.is_ubuntu14)
        self.assertTrue(distro.is_ubuntu)

    def test_ubuntu16(self):
        self.assertTrue(Distro.UBUNTU16.is_ubuntu16)
        distro = Distro.from_os_release(DISTROS_OS_RELEASE["Ubuntu 16.04"])
        self.assertTrue(distro.is_ubuntu16)
        self.assertTrue(distro.is_ubuntu)

    def test_ubuntu18(self):
        self.assertTrue(Distro.UBUNTU18.is_ubuntu18)
        distro = Distro.from_os_release(DISTROS_OS_RELEASE["Ubuntu 18.04"])
        self.assertTrue(distro.is_ubuntu18)
        self.assertTrue(distro.is_ubuntu)

    def test_parsing_error(self):
        self.assertRaises(DistroError, Distro.from_os_release, DISTROS_OS_RELEASE["Garbage"])
