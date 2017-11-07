import os
import socket
import random
import logging
import prometheus_client

START = 'start'
STOP = 'stop'

logger = logging.getLogger(__name__)


def start_metrics_server():
    seed = os.getpid() / 100
    port = random.randint(8000 + seed, 10000 - seed)
    try:
        prometheus_client.start_http_server(port)
        ip = socket.gethostbyname(socket.gethostname())
        return '{}:{}'.format(ip, port)
    except Exception as ex:
        logger.error('Cannot start local http metrics server: %s', ex)
    return None


class NemesisMetrics(object):

    DISRUPT_COUNTER = 'nemesis_disruptions_counter'
    DISRUPT_GAUGE = 'nemesis_disruptions_gauge'

    def __init__(self):
        super(NemesisMetrics, self).__init__()
        self._disrupt_counter = self.create_counter(self.DISRUPT_COUNTER,
                                                    'Counter for nemesis disruption methods',
                                                    ['method', 'event'])
        self._disrupt_gauge = self.create_gauge(self.DISRUPT_GAUGE,
                                                'Gauge for nemesis disruption methods',
                                                ['method'])

    @staticmethod
    def create_counter(name, desc, param_list):
        try:
            return prometheus_client.Counter(name, desc, param_list)
        except Exception as ex:
            logger.error('Cannot create metrics counter: %s', ex)
        return None

    @staticmethod
    def create_gauge(name, desc, param_list):
        try:
            return prometheus_client.Gauge(name, desc, param_list)
        except Exception as ex:
            logger.error('Cannot create metrics gauge: %s', ex)
        return None

    def event_start(self, disrupt):
        try:
            self._disrupt_counter.labels(disrupt, START).inc()
            self._disrupt_gauge.labels(disrupt).inc()
        except Exception as ex:
            logger.exception('Cannot start metrics event: %s', ex)

    def event_stop(self, disrupt):
        try:
            self._disrupt_counter.labels(disrupt, STOP).inc()
            self._disrupt_gauge.labels(disrupt).dec()
        except Exception as ex:
            logger.exception('Cannot stop metrics event: %s', ex)
