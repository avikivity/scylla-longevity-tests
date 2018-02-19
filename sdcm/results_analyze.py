import os
import logging
import math
import yaml
import elasticsearch
from sortedcontainers import SortedDict
import jinja2
import pprint
from send_email import Email

logger = logging.getLogger(__name__)
pp = pprint.PrettyPrinter(indent=2)


class QueryFilter(object):
    """
    Definition of query filtering parameters
    """
    SETUP_PARAMS = ['n_db_nodes', 'n_loaders', 'n_monitor_nodes']
    SETUP_INSTANCE_PARAMS = ['instance_type_db', 'instance_type_loader', 'instance_type_monitor']
    CS_CMD = ('cassandra-stress', )
    CS_PRELOAD_CMD = ('preload-cassandra-stress', )
    CS_PARAMS = ('command', 'cl', 'rate threads', 'schema', 'mode', 'pop', 'duration')
    CS_PROFILE_PARAMS = ('command', 'profile', 'ops', 'rate threads', 'duration')

    def __init__(self, test_doc, is_gce=False):
        self.test_doc = test_doc
        self.test_type = test_doc['_type']
        self.is_gce = is_gce
        self.date_re = '/2018-*/'

    def setup_instance_params(self):
        return ['gce_' + param for param in self.SETUP_INSTANCE_PARAMS] if self.is_gce else self.SETUP_INSTANCE_PARAMS

    def test_details_params(self):
        return self.CS_CMD + self.CS_PRELOAD_CMD if \
            self.test_type.endswith('read') or self.test_type.endswith('mixed') else self.CS_CMD

    def cs_params(self):
        return self.CS_PROFILE_PARAMS if self.test_type.endswith('profiles') else self.CS_PARAMS

    def filter_setup_details(self):
        setup_details = ''
        for param in self.SETUP_PARAMS + self.setup_instance_params():
            if setup_details:
                setup_details += ' AND '
            setup_details += 'setup_details.{}: {}'.format(param, self.test_doc['_source']['setup_details'][param])
        return setup_details

    def filter_test_details(self):
        test_details = 'test_details.job_name:{}'.format(
            self.test_doc['_source']['test_details']['job_name'].split('/')[0])
        for cs in self.test_details_params():
            for param in self.cs_params():
                if param == 'rate threads':
                    test_details += ' AND test_details.{}.rate\ threads: {}'.format(
                        cs, self.test_doc['_source']['test_details'][cs][param])
                elif param == 'duration' and cs.startswith('preload'):
                    continue
                else:
                    param_val = self.test_doc['_source']['test_details'][cs][param]
                    if param in ['profile', 'ops']:
                        param_val = "\"{}\"".format(param_val)
                    test_details += ' AND test_details.{}.{}: {}'.format(cs, param, param_val)
        test_details += ' AND test_details.time_completed: {}'.format(self.date_re)
        return test_details

    def __call__(self, *args, **kwargs):
        try:
            return '{} AND {}'.format(self.filter_test_details(), self.filter_setup_details())
        except KeyError:
            logger.exception('Expected parameters for filtering are not found , test {} {}'.format(
                self.test_type, self.test_doc['_id']))
        return None


class ResultsAnalyzer(object):
    """
    Get performance test results from elasticsearch DB and analyze it to find a regression
    """

    PARAMS = ['op rate', 'latency mean', 'latency 99th percentile']

    def __init__(self, *args, **kwargs):
        self._conf = self._get_conf(os.path.abspath(__file__).replace('.py', '.yaml').rstrip('c'))
        self._url = self._conf.get('es_url')
        self._index = kwargs.get('index', self._conf.get('es_index'))
        self._es = elasticsearch.Elasticsearch([self._url])
        self._limit = 1000
        self._send_email = kwargs.get('send_email', True)
        self._email_recipients = kwargs.get('email_recipients', None)

    def _get_conf(self, conf_file):
        with open(conf_file) as cf:
            return yaml.safe_load(cf)

    def _remove_non_stat_keys(self, stats):
        for non_stat_key in ['loader_idx', 'cpu_idx', 'keyspace_idx']:
            if non_stat_key in stats:
                del stats[non_stat_key]
        return stats

    def _test_stats(self, test_doc):
        # check if stats exists
        if 'results' not in test_doc['_source'] or 'stats_average' not in test_doc['_source']['results'] or \
                'stats_total' not in test_doc['_source']['results']:
            logger.error('Cannot find results for test: {}!'.format(test_doc['_id']))
            return None
        stats_average = self._remove_non_stat_keys(test_doc['_source']['results']['stats_average'])
        stats_total = test_doc['_source']['results']['stats_total']
        if not stats_average or not stats_total:
            logger.error('Cannot find average/total results for test: {}!'.format(test_doc['_id']))
            return None
        # replace average by total value for op rate
        stats_average['op rate'] = stats_total['op rate']
        return stats_average

    def _test_version(self, test_doc):
        if 'versions' not in test_doc['_source'] or 'scylla-server' not in test_doc['_source']['versions']:
            logger.error('Scylla version is not found for test %s', test_doc['_id'])
            return None, None

        return (test_doc['_source']['versions']['scylla-server']['version'],
                test_doc['_source']['versions']['scylla-server']['date'])

    def _get_best_value(self, key, val1, val2):
        if key == self.PARAMS[0]:  # op rate
            return val1 if val1 > val2 else val2
        return val1 if val2 == 0 or val1 < val2 else val2  # latency

    def get_all(self):
        """
        Get all the test results in json format
        """
        return self._es.search(index=self._index, size=self._limit)

    def get_test_by_id(self, test_id):
        """
        Get test results by test id
        :param test_id: test id created by performance test
        :return: test results in json format
        """
        if not self._es.exists(index=self._index, doc_type='_all', id=test_id):
            logger.error('Test results not found: {}'.format(test_id))
            return None
        return self._es.get(index=self._index, doc_type='_all', id=test_id)

    def cmp(self, src, dst, version_dst, best_test_id):
        """
        Compare current test results with the best results
        :param src: current test results
        :param dst: previous best test results
        :param version_dst: scylla server version to compare with
        :param best_test_id: the best results test id(for each parameter)
        :return: dictionary with compare calculation results
        """
        cmp_res = dict(version_dst=version_dst, res=dict())
        for param in self.PARAMS:
            param_key_name = param.replace(' ', '_')
            status = 'Progress'
            try:
                delta = src[param] - dst[param]
                change_perc = int(math.fabs(delta) * 100 / dst[param])
                best_id = best_test_id[param]
                if (param.startswith('latency') and delta > 0) or (param == 'op rate' and delta < 0):
                    status = 'Regression'
                cmp_res['res'][param_key_name] = dict(percent='{}%'.format(change_perc),
                                                      val=src[param],
                                                      best_val=dst[param],
                                                      best_id=best_id,
                                                      status=status)
            except TypeError:
                logger.exception('Failed to compare {} results: {} vs {}, version {}'.format(
                    param, src[param], dst[param], version_dst))
        return cmp_res

    def check_regression(self, test_id, is_gce=False):
        """
        Get test results by id, filter similar results and calculate max values for each version,
        then compare with max in the test version and all the found versions.
        Save the analysis in log and send by email.
        :param test_id: test id created by performance test
        :param is_gce: is gce instance
        :return: True/False
        """
        # get test res
        doc = self.get_test_by_id(test_id)
        if not doc:
            logger.error('Cannot find test by id: {}!'.format(test_id))
            return False
        logger.info(pp.pformat(doc))

        test_stats = self._test_stats(doc)
        if not test_stats:
            return False

        # filter tests
        test_type = doc['_type']
        query = QueryFilter(doc, is_gce)()
        if not query:
            return False

        filter_path = ['hits.hits._id',
                       'hits.hits._source.results.stats_average',
                       'hits.hits._source.results.stats_total',
                       'hits.hits._source.versions.scylla-server']
        tests_filtered = self._es.search(index=self._index, doc_type=test_type, q=query, filter_path=filter_path,
                                         size=self._limit)
        if not tests_filtered:
            logger.info('Cannot find tests with the same parameters as {}'.format(test_id))
            return False

        # get the best res for all versions of this job
        group_by_version = dict()
        for tr in tests_filtered['hits']['hits']:
            if tr['_id'] == test_id:  # filter the current test
                continue
            if '_source' not in tr:  # non-valid record?
                logger.error('Skip non-valid test: %s', tr['_id'])
                continue
            (version, version_date) = self._test_version(tr)
            if not version:
                continue
            curr_test_stats = self._test_stats(tr)
            if not curr_test_stats:
                continue
            if version not in group_by_version:
                group_by_version[version] = dict(tests=SortedDict(), stats_best=dict(), best_test_id=dict())
                group_by_version[version]['stats_best'] = {k: 0 for k in self.PARAMS}
                group_by_version[version]['best_test_id'] = {k: tr['_id'] for k in self.PARAMS}
            group_by_version[version]['tests'][version_date] = curr_test_stats
            old_best = group_by_version[version]['stats_best']
            group_by_version[version]['stats_best'] =\
                {k: self._get_best_value(k, curr_test_stats[k], old_best[k])
                 for k in self.PARAMS if k in curr_test_stats and k in old_best}
            # replace best test id if best value changed
            for k in self.PARAMS:
                if k in curr_test_stats and k in old_best and\
                        group_by_version[version]['stats_best'][k] == curr_test_stats[k]:
                            group_by_version[version]['best_test_id'][k] = tr['_id']

        res_list = list()
        # compare with the best in the test version and all the previous versions
        test_version = doc['_source']['versions']['scylla-server']['version']
        for version in group_by_version.keys():
            if version == test_version and not len(group_by_version[test_version]['tests']):
                logger.info('No previous tests in the current version {} to compare'.format(test_version))
                continue
            cmp_res = self.cmp(test_stats,
                               group_by_version[version]['stats_best'],
                               version,
                               group_by_version[version]['best_test_id'])
            res_list.append(cmp_res)
        if not res_list:
            logger.info('No test results to compare with')
            return False

        # send results by email
        results = dict(test_type=test_type,
                       test_id=test_id,
                       test_version=doc['_source']['versions']['scylla-server'],
                       res_list=res_list)
        logger.info('Regression analysis:')
        logger.info(pp.pformat(results))

        dashboard_url = self._conf.get('kibana_url')
        for dash in ('dashboard_master', 'dashboard_releases'):
            dash_url = '{}{}'.format(dashboard_url, self._conf.get(dash))
            results.update({dash: dash_url})

        subject = 'Performance Regression Compare Results - {} - {}'.format(test_type.split('.')[-1], test_version)
        self.send_email(subject, results)

        return True

    @staticmethod
    def render_to_html(res):
        """
        Render analysis results to html template
        :param res: results dictionary
        :return: html string
        """
        loader = jinja2.FileSystemLoader(os.path.dirname(os.path.abspath(__file__)))
        env = jinja2.Environment(loader=loader, autoescape=True)
        template = env.get_template('results.html')
        html = template.render(dict(results=res))
        return html

    def send_email(self, subject, content, html=True):
        if self._send_email and self._email_recipients:
            logger.debug('Send email to {}'.format(self._email_recipients))
            content = self.render_to_html(content)
            em = Email(self._conf['email']['server'],
                       self._conf['email']['sender'],
                       self._email_recipients)
            em.send(subject, content, html)
