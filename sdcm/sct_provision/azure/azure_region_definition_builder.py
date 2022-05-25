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
# Copyright (c) 2022 ScyllaDB
from typing import Dict

from sdcm.sct_provision.common.types import NodeTypeType
from sdcm.sct_provision.region_definition_builder import ConfigParamsMap, DefinitionBuilder

db_map = ConfigParamsMap(image_id="azure_image_db",
                         type="azure_instance_type_db",
                         user_name="azure_image_username",
                         root_disk_size="azure_root_disk_size_db")

loader_map = ConfigParamsMap(image_id="azure_image_loader",
                             type="azure_instance_type_loader",
                             user_name="ami_loader_user",
                             root_disk_size="azure_root_disk_size_loader")

monitor_map = ConfigParamsMap(image_id="azure_image_monitor",
                              type="azure_instance_type_monitor",
                              user_name="ami_monitor_user",
                              root_disk_size="azure_root_disk_size_monitor")

mapper: Dict[NodeTypeType, ConfigParamsMap] = {"scylla-db": db_map,
                                               "loader": loader_map,
                                               "monitor": monitor_map}


class AzureDefinitionBuilder(DefinitionBuilder):
    BACKEND = "azure"
    SCT_PARAM_MAPPER = mapper
    REGION_MAP = "azure_region_name"
