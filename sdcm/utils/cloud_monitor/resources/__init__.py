from datetime import datetime


CLOUD_PROVIDERS = ("aws", "gce")


class CloudInstance:  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    pricing = None  # need to be set in the child class

    def __init__(self, cloud, name, instance_id, region_az, state, lifecycle, instance_type, owner, create_time, keep):  # pylint: disable=too-many-arguments
        self.cloud = cloud
        self.name = name
        self.instance_id = instance_id
        self.region_az = region_az
        self.state = state
        self.lifecycle = lifecycle
        self.instance_type = instance_type
        self.owner = owner.lower()
        self.create_time = create_time
        self.keep = keep  # keep alive
        self.price = self.pricing.get_instance_price(region=self.region, instance_type=self.instance_type,
                                                     state=self.state, lifecycle=self.lifecycle)

    @property
    def region(self):
        raise NotImplementedError

    def hours_running(self):
        if self.state == "running":
            dt_since_created = datetime.now(self.create_time.tzinfo) - self.create_time
            return int(dt_since_created.total_seconds()/3600)
        return 0

    @property
    def total_cost(self):
        return round(self.hours_running() * self.price, 1)

    @property
    def projected_daily_cost(self):
        return round(24 * self.price, 1)


class CloudResources:

    def __init__(self):
        self._grouped_by_cloud_provider = {prov: [] for prov in CLOUD_PROVIDERS}
        self.all = []
        self.get_all()

    def __getitem__(self, item):
        return self._grouped_by_cloud_provider[item]

    def __setitem__(self, key, value):
        self._grouped_by_cloud_provider[key] = value

    def get_all(self):
        """Should fill self.all and self._grouped_by_cloud_provider"""
        raise NotImplementedError
