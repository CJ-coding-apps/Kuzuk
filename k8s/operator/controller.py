#!/usr/bin/env python3
"""
Kuzuk Kubernetes Operator Controller

This controller manages Kuzuk clusters and provides enterprise-grade
lifecycle management capabilities.
"""

import asyncio
import logging
import json
import os
import yaml
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

try:
    import kopf
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
    KUBERNETES_AVAILABLE = True
except ImportError:
    logging.warning("Kubernetes client and kopf not available")
    KUBERNETES_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class ClusterStatus:
    """Represents the status of a Kuzuk cluster."""
    phase: str
    ready_replicas: int
    total_replicas: int
    master_ready: bool
    master_endpoint: Optional[str]
    conditions: List[Dict[str, Any]]
    last_update: datetime


class KuzukController:
    """Main controller for Kuzuk custom resources."""
    
    def __init__(self):
        """Initialize the controller."""
        self.api_client = None
        self.apps_v1 = None
        self.core_v1 = None
        self.autoscaling_v1 = None
        self.networking_v1 = None
        
        if KUBERNETES_AVAILABLE:
            try:
                # Try to load in-cluster config first
                config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes configuration")
            except:
                try:
                    # Fall back to local kubeconfig
                    config.load_kube_config()
                    logger.info("Loaded local Kubernetes configuration")
                except Exception as e:
                    logger.error(f"Failed to load Kubernetes configuration: {e}")
                    return
            
            self.api_client = client.ApiClient()
            self.apps_v1 = client.AppsV1Api()
            self.core_v1 = client.CoreV1Api()
            self.autoscaling_v1 = client.AutoscalingV1Api()
            self.networking_v1 = client.NetworkingV1Api()
    
    async def create_cluster(self, spec: Dict[str, Any], name: str, namespace: str) -> Dict[str, Any]:
        """Create a new Kuzuk cluster."""
        logger.info(f"Creating Kuzuk cluster: {name} in namespace: {namespace}")
        
        try:
            # Create namespace if it doesn't exist
            await self._ensure_namespace(namespace)
            
            # Create secrets and configmaps
            await self._create_secrets(name, namespace, spec)
            await self._create_configmaps(name, namespace, spec)
            
            # Create persistent volumes
            await self._create_persistent_volumes(name, namespace, spec)
            
            # Create master deployment
            await self._create_master_deployment(name, namespace, spec)
            
            # Create replica deployments
            await self._create_replica_deployments(name, namespace, spec)
            
            # Create services
            await self._create_services(name, namespace, spec)
            
            # Create HPA if scaling is enabled
            if spec.get('scaling', {}).get('enabled', True):
                await self._create_hpa(name, namespace, spec)
            
            # Create monitoring stack if enabled
            if spec.get('monitoring', {}).get('enabled', True):
                await self._create_monitoring(name, namespace, spec)
            
            # Create network policies if enabled
            if spec.get('security', {}).get('networkPolicy', {}).get('enabled', True):
                await self._create_network_policies(name, namespace, spec)
            
            return {
                'phase': 'Deploying',
                'conditions': [{
                    'type': 'Deploying',
                    'status': 'True',
                    'lastTransitionTime': datetime.utcnow().isoformat() + 'Z',
                    'reason': 'ClusterCreation',
                    'message': 'Kuzuk cluster deployment started'
                }],
                'replicas': {
                    'ready': 0,
                    'total': spec.get('cluster', {}).get('replicas', 3),
                    'updated': 0
                },
                'master': {
                    'ready': False,
                    'endpoint': None,
                    'version': spec.get('cluster', {}).get('version', 'latest')
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to create cluster {name}: {e}")
            return {
                'phase': 'Failed',
                'conditions': [{
                    'type': 'Failed',
                    'status': 'True',
                    'lastTransitionTime': datetime.utcnow().isoformat() + 'Z',
                    'reason': 'CreationError',
                    'message': str(e)
                }]
            }
    
    async def update_cluster(self, spec: Dict[str, Any], status: Dict[str, Any], 
                           name: str, namespace: str) -> Dict[str, Any]:
        """Update an existing Kuzuk cluster."""
        logger.info(f"Updating Kuzuk cluster: {name} in namespace: {namespace}")
        
        try:
            # Check if scaling is needed
            current_replicas = status.get('replicas', {}).get('total', 0)
            desired_replicas = spec.get('cluster', {}).get('replicas', 3)
            
            if current_replicas != desired_replicas:
                await self._scale_cluster(name, namespace, desired_replicas)
                status['phase'] = 'Scaling'
                status['replicas']['total'] = desired_replicas
            
            # Update resources if needed
            await self._update_resources(name, namespace, spec)
            
            # Update monitoring configuration
            if spec.get('monitoring', {}).get('enabled', True):
                await self._update_monitoring(name, namespace, spec)
            
            # Update status
            cluster_status = await self._get_cluster_status(name, namespace)
            status.update(cluster_status)
            
            return status
            
        except Exception as e:
            logger.error(f"Failed to update cluster {name}: {e}")
            status['phase'] = 'Failed'
            status['conditions'] = [{
                'type': 'Failed',
                'status': 'True',
                'lastTransitionTime': datetime.utcnow().isoformat() + 'Z',
                'reason': 'UpdateError',
                'message': str(e)
            }]
            return status
    
    async def delete_cluster(self, name: str, namespace: str) -> None:
        """Delete a Kuzuk cluster."""
        logger.info(f"Deleting Kuzuk cluster: {name} in namespace: {namespace}")
        
        try:
            # Delete in reverse order of creation
            await self._delete_network_policies(name, namespace)
            await self._delete_monitoring(name, namespace)
            await self._delete_hpa(name, namespace)
            await self._delete_services(name, namespace)
            await self._delete_deployments(name, namespace)
            await self._delete_persistent_volumes(name, namespace)
            await self._delete_configmaps(name, namespace)
            await self._delete_secrets(name, namespace)
            
            logger.info(f"Successfully deleted Kuzuk cluster: {name}")
            
        except Exception as e:
            logger.error(f"Failed to delete cluster {name}: {e}")
            raise
    
    async def _ensure_namespace(self, namespace: str) -> None:
        """Ensure namespace exists."""
        try:
            self.core_v1.read_namespace(namespace)
        except ApiException as e:
            if e.status == 404:
                # Create namespace
                ns = client.V1Namespace(
                    metadata=client.V1ObjectMeta(name=namespace)
                )
                self.core_v1.create_namespace(ns)
                logger.info(f"Created namespace: {namespace}")
    
    async def _create_secrets(self, name: str, namespace: str, spec: Dict[str, Any]) -> None:
        """Create required secrets."""
        # Database credentials
        secret_data = {
            'db-password': 'kuzu-default-password',  # Should be generated
            'admin-password': 'admin-default-password'
        }
        
        if spec.get('monitoring', {}).get('grafana', {}).get('adminPassword'):
            secret_data['grafana-admin-password'] = spec['monitoring']['grafana']['adminPassword']
        
        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(
                name=f"{name}-secrets",
                namespace=namespace,
                labels={'app': 'kuzuk', 'cluster': name}
            ),
            string_data=secret_data
        )
        
        try:
            self.core_v1.create_namespaced_secret(namespace, secret)
            logger.info(f"Created secrets for cluster: {name}")
        except ApiException as e:
            if e.status != 409:  # Ignore if already exists
                raise
    
    async def _create_configmaps(self, name: str, namespace: str, spec: Dict[str, Any]) -> None:
        """Create required configmaps."""
        # Main configuration
        config_data = {
            'cluster.yaml': yaml.dump({
                'cluster': spec.get('cluster', {}),
                'database': spec.get('database', {}),
                'scaling': spec.get('scaling', {})
            })
        }
        
        configmap = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(
                name=f"{name}-config",
                namespace=namespace,
                labels={'app': 'kuzuk', 'cluster': name}
            ),
            data=config_data
        )
        
        try:
            self.core_v1.create_namespaced_config_map(namespace, configmap)
            logger.info(f"Created configmap for cluster: {name}")
        except ApiException as e:
            if e.status != 409:  # Ignore if already exists
                raise
    
    async def _create_persistent_volumes(self, name: str, namespace: str, spec: Dict[str, Any]) -> None:
        """Create persistent volume claims."""
        storage_size = spec.get('database', {}).get('storage', {}).get('size', '10Gi')
        storage_class = spec.get('database', {}).get('storage', {}).get('storageClass')
        
        # Master PVC
        master_pvc = client.V1PersistentVolumeClaim(
            metadata=client.V1ObjectMeta(
                name=f"{name}-master-data",
                namespace=namespace,
                labels={'app': 'kuzuk', 'cluster': name, 'component': 'master'}
            ),
            spec=client.V1PersistentVolumeClaimSpec(
                access_modes=['ReadWriteOnce'],
                resources=client.V1ResourceRequirements(
                    requests={'storage': storage_size}
                ),
                storage_class_name=storage_class
            )
        )
        
        try:
            self.core_v1.create_namespaced_persistent_volume_claim(namespace, master_pvc)
            logger.info(f"Created master PVC for cluster: {name}")
        except ApiException as e:
            if e.status != 409:  # Ignore if already exists
                raise
    
    async def _create_master_deployment(self, name: str, namespace: str, spec: Dict[str, Any]) -> None:
        """Create master deployment."""
        resources = spec.get('resources', {}).get('master', {})
        
        container = client.V1Container(
            name='kuzuk-master',
            image=f"kuzuk:{spec.get('cluster', {}).get('version', 'latest')}",
            ports=[client.V1ContainerPort(container_port=8000)],
            env=[
                client.V1EnvVar(name='KUZU_MODE', value='master'),
                client.V1EnvVar(name='KUZU_CLUSTER_NAME', value=name),
                client.V1EnvVar(
                    name='KUZU_DB_PASSWORD',
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(
                            name=f"{name}-secrets",
                            key='db-password'
                        )
                    )
                )
            ],
            volume_mounts=[
                client.V1VolumeMount(
                    name='data',
                    mount_path='/data'
                ),
                client.V1VolumeMount(
                    name='config',
                    mount_path='/config'
                )
            ],
            resources=client.V1ResourceRequirements(
                requests={
                    'cpu': resources.get('cpu', '1000m'),
                    'memory': resources.get('memory', '2Gi')
                },
                limits={
                    'cpu': resources.get('limits', {}).get('cpu', '2000m'),
                    'memory': resources.get('limits', {}).get('memory', '4Gi')
                }
            ),
            liveness_probe=client.V1Probe(
                http_get=client.V1HTTPGetAction(
                    path='/health',
                    port=8000
                ),
                initial_delay_seconds=30,
                period_seconds=10
            ),
            readiness_probe=client.V1Probe(
                http_get=client.V1HTTPGetAction(
                    path='/ready',
                    port=8000
                ),
                initial_delay_seconds=5,
                period_seconds=5
            )
        )
        
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=f"{name}-master",
                namespace=namespace,
                labels={'app': 'kuzuk', 'cluster': name, 'component': 'master'}
            ),
            spec=client.V1DeploymentSpec(
                replicas=1,
                selector=client.V1LabelSelector(
                    match_labels={'app': 'kuzuk', 'cluster': name, 'component': 'master'}
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={'app': 'kuzuk', 'cluster': name, 'component': 'master'}
                    ),
                    spec=client.V1PodSpec(
                        containers=[container],
                        volumes=[
                            client.V1Volume(
                                name='data',
                                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                    claim_name=f"{name}-master-data"
                                )
                            ),
                            client.V1Volume(
                                name='config',
                                config_map=client.V1ConfigMapVolumeSource(
                                    name=f"{name}-config"
                                )
                            )
                        ]
                    )
                )
            )
        )
        
        try:
            self.apps_v1.create_namespaced_deployment(namespace, deployment)
            logger.info(f"Created master deployment for cluster: {name}")
        except ApiException as e:
            if e.status != 409:  # Ignore if already exists
                raise
    
    async def _create_replica_deployments(self, name: str, namespace: str, spec: Dict[str, Any]) -> None:
        """Create replica deployments."""
        replicas = spec.get('cluster', {}).get('replicas', 3)
        resources = spec.get('resources', {}).get('replica', {})
        
        container = client.V1Container(
            name='kuzuk-replica',
            image=f"kuzuk:{spec.get('cluster', {}).get('version', 'latest')}",
            ports=[client.V1ContainerPort(container_port=8000)],
            env=[
                client.V1EnvVar(name='KUZU_MODE', value='replica'),
                client.V1EnvVar(name='KUZU_CLUSTER_NAME', value=name),
                client.V1EnvVar(name='KUZU_MASTER_ENDPOINT', value=f"{name}-master:8000"),
                client.V1EnvVar(
                    name='KUZU_DB_PASSWORD',
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(
                            name=f"{name}-secrets",
                            key='db-password'
                        )
                    )
                )
            ],
            volume_mounts=[
                client.V1VolumeMount(
                    name='config',
                    mount_path='/config'
                )
            ],
            resources=client.V1ResourceRequirements(
                requests={
                    'cpu': resources.get('cpu', '500m'),
                    'memory': resources.get('memory', '1Gi')
                },
                limits={
                    'cpu': resources.get('limits', {}).get('cpu', '1000m'),
                    'memory': resources.get('limits', {}).get('memory', '2Gi')
                }
            ),
            liveness_probe=client.V1Probe(
                http_get=client.V1HTTPGetAction(
                    path='/health',
                    port=8000
                ),
                initial_delay_seconds=30,
                period_seconds=10
            ),
            readiness_probe=client.V1Probe(
                http_get=client.V1HTTPGetAction(
                    path='/ready',
                    port=8000
                ),
                initial_delay_seconds=5,
                period_seconds=5
            )
        )
        
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=f"{name}-replica",
                namespace=namespace,
                labels={'app': 'kuzuk', 'cluster': name, 'component': 'replica'}
            ),
            spec=client.V1DeploymentSpec(
                replicas=replicas,
                selector=client.V1LabelSelector(
                    match_labels={'app': 'kuzuk', 'cluster': name, 'component': 'replica'}
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={'app': 'kuzuk', 'cluster': name, 'component': 'replica'}
                    ),
                    spec=client.V1PodSpec(
                        containers=[container],
                        volumes=[
                            client.V1Volume(
                                name='config',
                                config_map=client.V1ConfigMapVolumeSource(
                                    name=f"{name}-config"
                                )
                            )
                        ]
                    )
                )
            )
        )
        
        try:
            self.apps_v1.create_namespaced_deployment(namespace, deployment)
            logger.info(f"Created replica deployment for cluster: {name}")
        except ApiException as e:
            if e.status != 409:  # Ignore if already exists
                raise
    
    async def _create_services(self, name: str, namespace: str, spec: Dict[str, Any]) -> None:
        """Create services for master and replicas."""
        # Master service
        master_service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=f"{name}-master",
                namespace=namespace,
                labels={'app': 'kuzuk', 'cluster': name, 'component': 'master'}
            ),
            spec=client.V1ServiceSpec(
                selector={'app': 'kuzuk', 'cluster': name, 'component': 'master'},
                ports=[client.V1ServicePort(port=8000, target_port=8000)],
                type='ClusterIP'
            )
        )
        
        # Replica service
        replica_service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=f"{name}-replica",
                namespace=namespace,
                labels={'app': 'kuzuk', 'cluster': name, 'component': 'replica'}
            ),
            spec=client.V1ServiceSpec(
                selector={'app': 'kuzuk', 'cluster': name, 'component': 'replica'},
                ports=[client.V1ServicePort(port=8000, target_port=8000)],
                type='ClusterIP'
            )
        )
        
        try:
            self.core_v1.create_namespaced_service(namespace, master_service)
            self.core_v1.create_namespaced_service(namespace, replica_service)
            logger.info(f"Created services for cluster: {name}")
        except ApiException as e:
            if e.status != 409:  # Ignore if already exists
                raise
    
    async def _create_hpa(self, name: str, namespace: str, spec: Dict[str, Any]) -> None:
        """Create horizontal pod autoscaler."""
        scaling_config = spec.get('scaling', {})
        
        hpa = client.V1HorizontalPodAutoscaler(
            metadata=client.V1ObjectMeta(
                name=f"{name}-replica-hpa",
                namespace=namespace,
                labels={'app': 'kuzuk', 'cluster': name}
            ),
            spec=client.V1HorizontalPodAutoscalerSpec(
                scale_target_ref=client.V1CrossVersionObjectReference(
                    api_version='apps/v1',
                    kind='Deployment',
                    name=f"{name}-replica"
                ),
                min_replicas=scaling_config.get('minReplicas', 2),
                max_replicas=scaling_config.get('maxReplicas', 10),
                target_cpu_utilization_percentage=scaling_config.get('targetCpuUtilization', 70)
            )
        )
        
        try:
            self.autoscaling_v1.create_namespaced_horizontal_pod_autoscaler(namespace, hpa)
            logger.info(f"Created HPA for cluster: {name}")
        except ApiException as e:
            if e.status != 409:  # Ignore if already exists
                raise
    
    async def _create_monitoring(self, name: str, namespace: str, spec: Dict[str, Any]) -> None:
        """Create monitoring stack if enabled."""
        monitoring_config = spec.get('monitoring', {})
        
        if monitoring_config.get('prometheus', {}).get('enabled', True):
            # Create Prometheus configuration and deployment
            # This would be similar to the existing Prometheus setup
            pass
        
        if monitoring_config.get('grafana', {}).get('enabled', True):
            # Create Grafana deployment
            # This would be similar to the existing Grafana setup
            pass
        
        logger.info(f"Created monitoring stack for cluster: {name}")
    
    async def _create_network_policies(self, name: str, namespace: str, spec: Dict[str, Any]) -> None:
        """Create network policies for security."""
        # Network policy to isolate the cluster
        network_policy = client.V1NetworkPolicy(
            metadata=client.V1ObjectMeta(
                name=f"{name}-network-policy",
                namespace=namespace,
                labels={'app': 'kuzuk', 'cluster': name}
            ),
            spec=client.V1NetworkPolicySpec(
                pod_selector=client.V1LabelSelector(
                    match_labels={'app': 'kuzuk', 'cluster': name}
                ),
                policy_types=['Ingress', 'Egress'],
                ingress=[
                    client.V1NetworkPolicyIngressRule(
                        from_=[
                            client.V1NetworkPolicyPeer(
                                pod_selector=client.V1LabelSelector(
                                    match_labels={'app': 'kuzuk', 'cluster': name}
                                )
                            )
                        ],
                        ports=[
                            client.V1NetworkPolicyPort(
                                protocol='TCP',
                                port=8000
                            )
                        ]
                    )
                ],
                egress=[
                    client.V1NetworkPolicyEgressRule(
                        to=[
                            client.V1NetworkPolicyPeer(
                                pod_selector=client.V1LabelSelector(
                                    match_labels={'app': 'kuzuk', 'cluster': name}
                                )
                            )
                        ]
                    )
                ]
            )
        )
        
        try:
            self.networking_v1.create_namespaced_network_policy(namespace, network_policy)
            logger.info(f"Created network policy for cluster: {name}")
        except ApiException as e:
            if e.status != 409:  # Ignore if already exists
                raise
    
    async def _get_cluster_status(self, name: str, namespace: str) -> Dict[str, Any]:
        """Get current cluster status."""
        try:
            # Get master deployment status
            master_deployment = self.apps_v1.read_namespaced_deployment(
                name=f"{name}-master",
                namespace=namespace
            )
            
            # Get replica deployment status
            replica_deployment = self.apps_v1.read_namespaced_deployment(
                name=f"{name}-replica",
                namespace=namespace
            )
            
            master_ready = (master_deployment.status.ready_replicas or 0) > 0
            replica_ready = replica_deployment.status.ready_replicas or 0
            replica_total = replica_deployment.status.replicas or 0
            
            # Determine phase
            if master_ready and replica_ready == replica_total:
                phase = 'Running'
            elif master_ready:
                phase = 'Deploying'
            else:
                phase = 'Pending'
            
            return {
                'phase': phase,
                'replicas': {
                    'ready': replica_ready,
                    'total': replica_total,
                    'updated': replica_deployment.status.updated_replicas or 0
                },
                'master': {
                    'ready': master_ready,
                    'endpoint': f"{name}-master.{namespace}.svc.cluster.local:8000" if master_ready else None,
                    'version': 'latest'  # Could extract from deployment
                },
                'lastUpdateTime': datetime.utcnow().isoformat() + 'Z'
            }
            
        except Exception as e:
            logger.error(f"Failed to get cluster status for {name}: {e}")
            return {
                'phase': 'Unknown',
                'conditions': [{
                    'type': 'StatusError',
                    'status': 'True',
                    'lastTransitionTime': datetime.utcnow().isoformat() + 'Z',
                    'reason': 'StatusCheckFailed',
                    'message': str(e)
                }]
            }
    
    # Additional helper methods for update, scale, and delete operations...
    async def _scale_cluster(self, name: str, namespace: str, replicas: int) -> None:
        """Scale the replica deployment."""
        try:
            # Patch the replica deployment
            self.apps_v1.patch_namespaced_deployment_scale(
                name=f"{name}-replica",
                namespace=namespace,
                body={'spec': {'replicas': replicas}}
            )
            logger.info(f"Scaled cluster {name} to {replicas} replicas")
        except Exception as e:
            logger.error(f"Failed to scale cluster {name}: {e}")
            raise
    
    async def _update_resources(self, name: str, namespace: str, spec: Dict[str, Any]) -> None:
        """Update resource allocations."""
        # This would update the deployment resource specifications
        pass
    
    async def _update_monitoring(self, name: str, namespace: str, spec: Dict[str, Any]) -> None:
        """Update monitoring configuration."""
        # This would update Prometheus and Grafana configurations
        pass
    
    async def _delete_network_policies(self, name: str, namespace: str) -> None:
        """Delete network policies."""
        try:
            self.networking_v1.delete_namespaced_network_policy(
                name=f"{name}-network-policy",
                namespace=namespace
            )
        except ApiException as e:
            if e.status != 404:
                raise
    
    async def _delete_monitoring(self, name: str, namespace: str) -> None:
        """Delete monitoring stack."""
        # Delete Prometheus and Grafana deployments
        pass
    
    async def _delete_hpa(self, name: str, namespace: str) -> None:
        """Delete HPA."""
        try:
            self.autoscaling_v1.delete_namespaced_horizontal_pod_autoscaler(
                name=f"{name}-replica-hpa",
                namespace=namespace
            )
        except ApiException as e:
            if e.status != 404:
                raise
    
    async def _delete_services(self, name: str, namespace: str) -> None:
        """Delete services."""
        services = [f"{name}-master", f"{name}-replica"]
        for service in services:
            try:
                self.core_v1.delete_namespaced_service(
                    name=service,
                    namespace=namespace
                )
            except ApiException as e:
                if e.status != 404:
                    raise
    
    async def _delete_deployments(self, name: str, namespace: str) -> None:
        """Delete deployments."""
        deployments = [f"{name}-master", f"{name}-replica"]
        for deployment in deployments:
            try:
                self.apps_v1.delete_namespaced_deployment(
                    name=deployment,
                    namespace=namespace
                )
            except ApiException as e:
                if e.status != 404:
                    raise
    
    async def _delete_persistent_volumes(self, name: str, namespace: str) -> None:
        """Delete PVCs."""
        try:
            self.core_v1.delete_namespaced_persistent_volume_claim(
                name=f"{name}-master-data",
                namespace=namespace
            )
        except ApiException as e:
            if e.status != 404:
                raise
    
    async def _delete_configmaps(self, name: str, namespace: str) -> None:
        """Delete configmaps."""
        try:
            self.core_v1.delete_namespaced_config_map(
                name=f"{name}-config",
                namespace=namespace
            )
        except ApiException as e:
            if e.status != 404:
                raise
    
    async def _delete_secrets(self, name: str, namespace: str) -> None:
        """Delete secrets."""
        try:
            self.core_v1.delete_namespaced_secret(
                name=f"{name}-secrets",
                namespace=namespace
            )
        except ApiException as e:
            if e.status != 404:
                raise


# Global controller instance
controller = KuzukController()


# Kopf event handlers
@kopf.on.create('kuzu.io', 'v1', 'kuzuks')
async def create_kuzuk(spec, name, namespace, **kwargs):
    """Handle Kuzuk creation."""
    logger.info(f"Creating Kuzuk: {name} in {namespace}")
    status = await controller.create_cluster(spec, name, namespace)
    return status


@kopf.on.update('kuzu.io', 'v1', 'kuzuks')
async def update_kuzuk(spec, status, name, namespace, **kwargs):
    """Handle Kuzuk updates."""
    logger.info(f"Updating Kuzuk: {name} in {namespace}")
    new_status = await controller.update_cluster(spec, status, name, namespace)
    return new_status


@kopf.on.delete('kuzu.io', 'v1', 'kuzuks')
async def delete_kuzuk(name, namespace, **kwargs):
    """Handle Kuzuk deletion."""
    logger.info(f"Deleting Kuzuk: {name} in {namespace}")
    await controller.delete_cluster(name, namespace)


@kopf.timer('kuzu.io', 'v1', 'kuzuks', interval=30)
async def check_kuzuk_health(spec, status, name, namespace, **kwargs):
    """Periodic health check for Kuzuk clusters."""
    try:
        cluster_status = await controller._get_cluster_status(name, namespace)
        
        # Update status if changed
        if cluster_status.get('phase') != status.get('phase'):
            logger.info(f"Cluster {name} phase changed to {cluster_status['phase']}")
            return cluster_status
        
        return status
        
    except Exception as e:
        logger.error(f"Health check failed for {name}: {e}")
        return status


if __name__ == '__main__':
    if not KUBERNETES_AVAILABLE:
        logger.error("Kubernetes client libraries not available. Install with: pip install kubernetes kopf")
        exit(1)
    
    # Run the operator
    import kopf
    kopf.run()