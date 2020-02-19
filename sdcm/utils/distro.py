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

import enum
import logging


LOGGER = logging.getLogger(__name__)


class DistroError(Exception):
    pass


@enum.unique
class Distro(enum.Enum):
    UNKNOWN = (None, None)
    CENTOS7 = ("centos", "7")
    CENTOS8 = ("centos", "8")
    RHEL7 = ("rhel", "7")
    RHEL8 = ("rhel", "8")
    OEL7 = ("ol", "7")
    DEBIAN8 = ("debian", "8")
    DEBIAN9 = ("debian", "9")
    DEBIAN10 = ("debian", "10")
    UBUNTU14 = ("ubuntu", "14.04")
    UBUNTU16 = ("ubuntu", "16.04")
    UBUNTU18 = ("ubuntu", "18.04")

    @classmethod
    def _missing_(cls, value):
        LOGGER.error("%s: missed key for %s", cls.__name__, value)
        return cls.UNKNOWN

    @classmethod
    def from_os_release(cls, os_release: str):
        """Parse /etc/os-release file and return Distro instance.

        Example of /etc/os-release (Debian 9):
          PRETTY_NAME="Debian GNU/Linux 9 (stretch)"
          NAME="Debian GNU/Linux"
          VERSION_ID="9"
          VERSION="9 (stretch)"
          VERSION_CODENAME=stretch
          ID=debian
          HOME_URL="https://www.debian.org/"
          SUPPORT_URL="https://www.debian.org/support"
          BUG_REPORT_URL="https://bugs.debian.org/"
        """
        parsed = {}
        for line in os_release.splitlines():
            if not line.strip():  # skip empty lines
                continue
            try:
                key, value = line.split("=", 1)
            except ValueError:
                raise DistroError(f"Unable to parse /etc/os-release line: `{line}'")
            value = value.strip('"')
            parsed[key] = value
        distro_id = parsed.get("ID")
        distro_version_id = parsed.get("VERSION_ID")

        # Don't remove minor version for Ubuntu (e.g., keep `16.04' and `18.04' as is.)
        if distro_id != "ubuntu" and distro_version_id is not None:
            distro_version_id = distro_version_id.split(".", 1)[0]

        # Use a nice feature of Enum here:
        #   https://docs.python.org/3/library/enum.html#programmatic-access-to-enumeration-members-and-their-attributes
        distro = cls((distro_id, distro_version_id))

        if distro == cls.UNKNOWN:
            LOGGER.error("Unable to detect Linux distribution name")
        else:
            LOGGER.info(f"Detected Linux distribution: {distro.name}")

        return distro

    @property
    def is_unknown(self):
        return self == self.UNKNOWN

    @property
    def is_centos7(self):
        return self == self.CENTOS7

    @property
    def is_centos8(self):
        return self == self.CENTOS8

    @property
    def is_rhel7(self):
        return self == self.RHEL7

    @property
    def is_rhel8(self):
        return self == self.RHEL8

    @property
    def is_oel7(self):
        return self == self.OEL7

    @property
    def is_rhel_like(self):
        return self.value[0] in ("centos", "rhel", "ol", )  # pylint: disable=unsubscriptable-object

    @property
    def is_ubuntu14(self):
        return self == self.UBUNTU14

    @property
    def is_ubuntu16(self):
        return self == self.UBUNTU16

    @property
    def is_ubuntu18(self):
        return self == self.UBUNTU18

    @property
    def is_ubuntu(self):
        return self.value[0] == "ubuntu"  # pylint: disable=unsubscriptable-object

    @property
    def is_debian8(self):
        return self == self.DEBIAN8

    @property
    def is_debian9(self):
        return self == self.DEBIAN9

    @property
    def is_debian10(self):
        return self == self.DEBIAN10

    @property
    def is_debian(self):
        return self.value[0] == "debian"  # pylint: disable=unsubscriptable-object
