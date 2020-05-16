import os
import tempfile
from collections import defaultdict
from copy import deepcopy
import jinja2
from sdcm.keystore import KeyStore
from sdcm.utils.cloud_monitor.resources import CLOUD_PROVIDERS
from sdcm.utils.cloud_monitor.resources.instances import CloudInstances
from sdcm.utils.cloud_monitor.resources.static_ips import StaticIPs


class BaseReport:

    def __init__(self, cloud_instances: CloudInstances, static_ips: StaticIPs, html_template: str):
        self.cloud_instances = cloud_instances
        self.static_ips = static_ips
        self.html_template = html_template

    @property
    def templates_dir(self):
        cur_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(cur_path, "templates")

    def _jinja_render_template(self, **kwargs):
        loader = jinja2.FileSystemLoader(self.templates_dir)
        env = jinja2.Environment(loader=loader, autoescape=True, extensions=['jinja2.ext.loopcontrols'],
                                 finalize=lambda x: x if x != 0 else "")
        template = env.get_template(self.html_template)
        html = template.render(**kwargs)
        return html

    def render_template(self):
        return self._jinja_render_template(**vars(self))

    def to_html(self):
        return self.render_template()

    def to_file(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         prefix='cloud-report_', delete=False, suffix='.html') as report_file:
            report_file.write(self.to_html())
            return report_file.name


class CloudResourcesReport(BaseReport):
    def __init__(self, cloud_instances: CloudInstances, static_ips: StaticIPs):
        super(CloudResourcesReport, self).__init__(cloud_instances, static_ips, html_template="cloud_resources.html")
        stats = dict(num_running_instances=0,
                     num_stopped_instances=0,
                     unused_static_ips=0,
                     num_used_static_ips=0,
                     )
        self.report = {cloud_provider: deepcopy(stats) for cloud_provider in CLOUD_PROVIDERS}

    def to_html(self):
        for cloud_provider in CLOUD_PROVIDERS:
            num_running_instances = len([i for i in self.cloud_instances[cloud_provider] if i.state == "running"])
            num_stopped_instances = len([i for i in self.cloud_instances[cloud_provider] if i.state == "stopped"])
            num_unused_static_ips = len([i for i in self.static_ips[cloud_provider] if not i.is_used])
            self.report[cloud_provider]["num_running_instances"] = num_running_instances
            self.report[cloud_provider]["num_stopped_instances"] = num_stopped_instances
            self.report[cloud_provider]["num_unused_static_ips"] = num_unused_static_ips
            self.report[cloud_provider]["num_used_static_ips"] = len(self.static_ips[cloud_provider])
        return self.render_template()


class PerUserSummaryReport(BaseReport):
    def __init__(self, cloud_instances: CloudInstances, static_ips: StaticIPs):
        super(PerUserSummaryReport, self).__init__(cloud_instances, static_ips, html_template="per_user_summary.html")
        self.report = {"results": {"qa": {}, "others": {}}, "cloud_providers": CLOUD_PROVIDERS}
        self.qa_users = KeyStore().get_qa_users()

    def user_type(self, user_name: str):
        return "qa" if user_name in self.qa_users else "others"

    def to_html(self):
        for cloud_provider in CLOUD_PROVIDERS:
            for instance in self.cloud_instances[cloud_provider]:
                user_type = self.user_type(instance.owner)
                results = self.report["results"]
                if instance.owner not in results[user_type]:
                    stats = dict(num_running_instances_spot=0, num_running_instances_on_demand=0,
                                 num_stopped_instances=0)
                    results[user_type][instance.owner] = {cp: deepcopy(stats) for cp in self.report["cloud_providers"]}
                    results[user_type][instance.owner]["num_instances_keep_alive"] = 0
                    results[user_type][instance.owner]["total_cost"] = 0
                    results[user_type][instance.owner]["projected_daily_cost"] = 0
                if instance.state == "running":
                    if instance.lifecycle == "spot":
                        results[user_type][instance.owner][cloud_provider]["num_running_instances_spot"] += 1
                    else:
                        results[user_type][instance.owner][cloud_provider]["num_running_instances_on_demand"] += 1
                    results[user_type][instance.owner]["total_cost"] += instance.total_cost
                    results[user_type][instance.owner]["projected_daily_cost"] += instance.projected_daily_cost
                if instance.state == "stopped":
                    results[user_type][instance.owner][cloud_provider]["num_stopped_instances"] += 1
                if instance.keep:
                    results[user_type][instance.owner]["num_instances_keep_alive"] += 1
        return self.render_template()


class GeneralReport(BaseReport):
    def __init__(self, cloud_instances: CloudInstances, static_ips: StaticIPs):
        super(GeneralReport, self).__init__(cloud_instances, static_ips, html_template="base.html")
        self.cloud_resources_report = CloudResourcesReport(cloud_instances=cloud_instances, static_ips=static_ips)
        self.per_user_report = PerUserSummaryReport(cloud_instances, static_ips)

    def to_html(self):
        cloud_resources_html = self.cloud_resources_report.to_html()
        per_user_report_html = self.per_user_report.to_html()
        return self._jinja_render_template(body=cloud_resources_html + per_user_report_html)


class DetailedReport(BaseReport):
    """Attached as HTML file"""

    def __init__(self, cloud_instances: CloudInstances, static_ips: StaticIPs, user=None):
        super(DetailedReport, self).__init__(cloud_instances, static_ips, html_template="per_user.html")
        self.user = user
        self.report = defaultdict(list)

    def to_html(self):
        for instance in self.cloud_instances.all:
            self.report[instance.owner].append(instance)
        if self.user:
            self.report = {self.user: self.report.get(self.user)}
        resources_html = self.render_template()
        self.html_template = "base.html"
        return self._jinja_render_template(body=resources_html)
