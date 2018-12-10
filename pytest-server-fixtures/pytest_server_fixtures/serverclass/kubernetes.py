"""
Kubernetes server class implementation.
"""
from __future__ import absolute_import

import os
import logging
import uuid

from kubernetes import config
from kubernetes import client as k8sclient
from kubernetes.client.rest import ApiException
from retry import retry
from pytest_server_fixtures import CONFIG
from .common import (ServerClass,
                     merge_dicts,
                     ServerFixtureNotRunningException,
                     ServerFixtureNotTerminatedException)

log = logging.getLogger(__name__)

IN_CLUSTER = os.path.exists('/var/run/secrets/kubernetes.io/namespace')
NAMESPACE = CONFIG.k8s_namespace

if IN_CLUSTER:
    config.load_incluster_config()
    if not namespace:
        with open('/var/run/secrets/kubernetes.io/namespace', 'r') as f:
            namespace = f.read().strip()
        log.info("SERVER_FIXTURES_K8S_NAMESPACE is not set, using current namespace '%s'", namespace)


class NotRunningInKubernetesException(Exception):
    """Thrown when code is not running as a Pod inside a Kubernetes cluster."""
    pass


class KubernetesServer(ServerClass):
    """Kubernetes server class."""

    def __init__(self, server_type, get_cmd, env, image, labels={}):
        super(KubernetesServer, self).__init__(get_cmd, env)
        if not IN_CLUSTER:
            raise NotRunningInKubernetesException()

        self._image = image
        self._run_cmd = get_cmd()
        self._labels = merge_dicts(labels, {
            'server-fixtures': 'kubernetes-server-fixtures',
            'server-fixtures/server-type': server_type,
            'server-fixtures/session-id': CONFIG.session_id,
        })

        self._v1api = k8sclient.CoreV1Api()

    def launch(self):
        try:
            log.debug('%s Launching pod' % self._log_prefix)
            self._create_pod()
            self._wait_until_running()
            log.debug('%s Pod is running' % self._log_prefix)
        except ApiException as e:
            log.warning('%s Error while launching pod: %s', self._log_prefix, e)
            raise

    def run(self):
        pass

    def teardown(self):
        self._delete_pod()
        # TODO: provide an flag to skip the wait to speed up the tests?
        self._wait_until_teardown()

    @property
    def hostname(self):
        status = self._get_pod_status()
        if status.phase != 'Running':
            raise ServerFixtureNotRunningException()
        return status.pod_ip

    @property
    def namespace(self):
        return namespace

    @property
    def labels(self):
        return self._labels

    def _get_pod_spec(self):
        container = k8sclient.V1Container(
            name='fixture',
            image=self._image,
            command=self._run_cmd
        )

        return k8sclient.V1PodSpec(
            containers=[container]
        )

    def _create_pod(self):
        try:
            pod = k8sclient.V1Pod()
            pod.metadata = k8sclient.V1ObjectMeta(name=self.name, labels=self._labels)
            pod.spec = self._get_pod_spec()
            self._v1api.create_namespaced_pod(namespace=self.namespace, body=pod)
        except ApiException as e:
            log.error("%s Failed to create pod: %s", self._log_prefix, e.reason)
            raise

    def _delete_pod(self):
        try:
            body = k8sclient.V1DeleteOptions()
            # delete the pod without waiting
            body.grace_period_seconds = 1
            self._v1api.delete_namespaced_pod(namespace=self.namespace, name=self.name, body=body)
        except ApiException as e:
            log.error("%s Failed to delete pod: %s", self._log_prefix, e.reason)

    def _get_pod_status(self):
        try:
            resp = self._v1api.read_namespaced_pod_status(namespace=self.namespace, name=self.name)
            return resp.status
        except ApiException as e:
            log.error("%s Failed to read pod status: %s", self._log_prefix, e.reason)
            raise

    @retry(ServerFixtureNotRunningException, tries=28, delay=1, backoff=2, max_delay=10)
    def _wait_until_running(self):
        current_phase = self._get_pod_status().phase
        log.debug("%s Waiting for pod status 'Running' (current='%s')", self._log_prefix, current_phase)
        if current_phase != 'Running':
            raise ServerFixtureNotRunningException()

    @retry(ServerFixtureNotTerminatedException, tries=28, delay=1, backoff=2, max_delay=10)
    def _wait_until_teardown(self):
        try:
            self._get_pod_status()
            raise ServerFixtureNotTerminatedException()
        except ApiException as e:
            if e.status == 404:
                return
            raise

    @property
    def _log_prefix(self):
        return "[K8S %s:%s]" % (self.namespace, self.name)