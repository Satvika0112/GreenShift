"""
Agent 3 — DISPATCH
Kubernetes client initialisation.

Supports:
  - In-cluster config (when running inside Kubernetes with ServiceAccount)
  - Local kubeconfig (development from host or Docker Compose)
"""

import os
import socket
import logging
import threading
from typing import Optional
from urllib.parse import urlparse

from kubernetes import client, config
from kubernetes.client import ApiClient, BatchV1Api, CoreV1Api
from kubernetes.config.config_exception import ConfigException

from app.shared.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_api_client: Optional[ApiClient] = None
_configured: bool = False
_last_k8s_check_time: float = 0.0
_last_k8s_available: bool = False
K8S_CHECK_CACHE_TTL: float = 5.0


def is_running_in_container() -> bool:
    """Return True if executing inside a Docker / OCI container."""
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "rt") as f:
            content = f.read()
            return "docker" in content or "kubepods" in content or "containerd" in content
    except Exception:
        return False


def _can_resolve_host(hostname: str) -> bool:
    """Check if a hostname resolves via DNS or /etc/hosts."""
    try:
        socket.gethostbyname(hostname)
        return True
    except Exception:
        return False


def reset_kubernetes_client() -> None:
    """Reset cached Kubernetes clients (useful for testing or config reload)."""
    global _api_client, _configured, _last_k8s_check_time, _last_k8s_available
    with _lock:
        _api_client = None
        _configured = False
        _last_k8s_check_time = 0.0
        _last_k8s_available = False


def _load_kube_config() -> ApiClient:
    """
    Initialise Kubernetes API client once with thread safety.

    Handles:
      1. In-cluster ServiceAccount configuration (K8S_IN_CLUSTER=true)
      2. Local kubeconfig file (K8S_IN_CLUSTER=false)
      3. Automatic container-to-host gateway rewrite for 127.0.0.1 / localhost endpoints
      4. Explicit K8S_HOST_OVERRIDE and K8S_INSECURE_SKIP_TLS_VERIFY overrides
    """
    global _api_client, _configured

    if _configured and _api_client is not None:
        return _api_client

    with _lock:
        if _configured and _api_client is not None:
            return _api_client

        if settings.k8s_in_cluster:
            logger.info("Initializing in-cluster Kubernetes config (ServiceAccount in namespace: %s)", settings.k8s_namespace)
            try:
                config.load_incluster_config()
            except ConfigException as exc:
                err_msg = (
                    f"Failed to load in-cluster Kubernetes config: {exc}. "
                    "Ensure GreenShift is running inside a Pod with a valid ServiceAccount (greenshift-dispatcher)."
                )
                logger.error(err_msg)
                raise RuntimeError(err_msg) from exc
        else:
            kubeconfig_file = settings.kubeconfig_path or os.environ.get("KUBECONFIG")
            if kubeconfig_file:
                kubeconfig_file = os.path.expanduser(kubeconfig_file)
                logger.info("Loading local kubeconfig from custom path: %s", kubeconfig_file)
            else:
                default_path = os.path.expanduser("~/.kube/config")
                logger.info("Loading local kubeconfig from default location: %s", default_path)

            try:
                config.load_kube_config(config_file=kubeconfig_file)
            except (ConfigException, FileNotFoundError) as exc:
                err_msg = (
                    f"Failed to load local kubeconfig: {exc}. "
                    "For Docker Compose, verify that ~/.kube is mounted to /home/greenshift/.kube:ro "
                    "and that K8S_IN_CLUSTER=false."
                )
                logger.error(err_msg)
                raise RuntimeError(err_msg) from exc

        configuration = client.Configuration.get_default_copy()
        configuration.retries = 1

        # Handle host overrides / container networking
        if settings.k8s_host_override:
            logger.info("Applying explicit Kubernetes host override: %s", settings.k8s_host_override)
            configuration.host = settings.k8s_host_override
        elif not settings.k8s_in_cluster and is_running_in_container():
            parsed = urlparse(configuration.host)
            if parsed.hostname in ("127.0.0.1", "localhost"):
                port_suffix = f":{parsed.port}" if parsed.port else ""
                scheme = parsed.scheme or "https"
                if _can_resolve_host("desktop-control-plane"):
                    new_host = f"{scheme}://desktop-control-plane{port_suffix}"
                    logger.info("Container detected: Rewriting loopback K8s host %s -> %s", configuration.host, new_host)
                    configuration.host = new_host
                elif _can_resolve_host("host.docker.internal"):
                    new_host = f"{scheme}://host.docker.internal{port_suffix}"
                    logger.info("Container detected: Rewriting loopback K8s host %s -> %s", configuration.host, new_host)
                    configuration.host = new_host

        if settings.k8s_insecure_skip_tls_verify:
            logger.warning("Disabling Kubernetes SSL/TLS certificate verification (K8S_INSECURE_SKIP_TLS_VERIFY=true)")
            configuration.verify_ssl = False

        client.Configuration.set_default(configuration)

        logger.info(
            "Kubernetes client configured successfully | Mode: %s | Server: %s | Target Namespace: %s",
            "in-cluster" if settings.k8s_in_cluster else "local-kubeconfig",
            configuration.host,
            settings.k8s_namespace,
        )

        _api_client = ApiClient(configuration=configuration)
        _configured = True
        return _api_client


def get_api_client() -> ApiClient:
    """Return the singleton ApiClient."""
    return _load_kube_config()


def get_batch_v1() -> BatchV1Api:
    """Return a configured BatchV1Api client."""
    api_client = _load_kube_config()
    return BatchV1Api(api_client)


def get_core_v1() -> CoreV1Api:
    """Return a configured CoreV1Api client."""
    api_client = _load_kube_config()
    return CoreV1Api(api_client)


def check_kubernetes_available(force: bool = False) -> bool:
    """
    Verify Kubernetes API reachability by performing a lightweight API call.
    Cached for 5 seconds to prevent repeated timeouts in hot loops.

    Returns:
        True if Kubernetes API is reachable and responding, False otherwise.
    """
    global _last_k8s_check_time, _last_k8s_available
    import time
    now = time.time()
    if not force and _last_k8s_check_time > 0 and (now - _last_k8s_check_time < K8S_CHECK_CACHE_TTL):
        return _last_k8s_available

    try:
        core = get_core_v1()
        core.list_namespace(limit=1, _request_timeout=3)
        logger.debug("Kubernetes API health check passed (namespace list successful)")
        _last_k8s_available = True
    except Exception as exc:
        logger.debug("Kubernetes API health check failed: %s", exc)
        _last_k8s_available = False

    _last_k8s_check_time = now
    return _last_k8s_available
